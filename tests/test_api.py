import pytest

from mopidy_youtube import youtube

from tests import apis, get_backend, my_vcr


def setup_entry_api(api, config, headers):
    youtube.Entry.api = api["class"](proxy=config["proxy"], headers=headers)
    api["class"].youtube_api_key = api["config"]["youtube"]["youtube_api_key"]
    youtube.Entry.cache.clear()
    return


@pytest.mark.parametrize("api", apis)
def test_api_search(api, config, headers):
    with my_vcr.use_cassette(f"tests/fixtures/{api['name']}/api_search.yaml"):
        setup_entry_api(api, config, headers)

        backend_inst = get_backend(config=config, api_config=api["config"])
        assert isinstance(youtube.Entry.api, api["class"])

        search_result = backend_inst.library.search(query={"omit-any": ["chvrches"]})
        assert search_result is None

        search_result = backend_inst.library.search(query={"any": ["chvrches"]})
        # assert len(search_result.tracks) == 18
        videos = [
            video
            for video in youtube.Entry.search("chvrches")
            if isinstance(video, youtube.Video)
        ]
        assert len(videos) > 0
        assert videos[0]._title  # should be ready
        assert videos[0]._channel  # should be ready
        assert videos[0]._length  # should be ready

        # video = youtube.Video.get("7U_LhzgwJ4U")
        # assert video in videos  # cached


@pytest.mark.parametrize("api", apis)
def test_api_list_related_videos(api, config, headers):
    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/api_list_related_videos.yaml"
    ):
        setup_entry_api(api, config, headers)

        related_videos = youtube.Entry.api.list_related_videos("h_uyq8oGDvU")

        assert isinstance(related_videos, dict)
        assert isinstance(related_videos["items"], list)
        assert len(related_videos["items"]) > 0


@pytest.mark.parametrize("api", apis)
def test_api_list_videos(api, config, headers):
    with my_vcr.use_cassette(f"tests/fixtures/{api['name']}/api_list_videos.yaml"):
        setup_entry_api(api, config, headers)

        videos = youtube.Entry.api.list_videos(
            ["_mTRvJ9fugM", "h_uyq8oGDvU", "LvXoB1S45j0"]
        )
        assert len(videos["items"]) == 3


@pytest.mark.parametrize("api", apis)
def test_api_list_playlists(api, config, headers):
    with my_vcr.use_cassette(f"tests/fixtures/{api['name']}/api_list_playlists.yaml"):
        setup_entry_api(api, config, headers)

        playlists = youtube.Entry.api.list_playlists(
            [
                "PLJD13y84Bd032qVrq7CHBLEfKZZtp-u1j",
                "PLJD13y84Bd01Q8b8ONfwNMLD3pVBcqwMq",
            ]
        )

        assert len(playlists["items"]) == 2


@pytest.mark.parametrize("api", apis)
def test_api_list_playlistitems(api, config, headers):
    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/api_list_playlistitems.yaml"
    ):
        setup_entry_api(api, config, headers)

        playlistitems = youtube.Entry.api.list_playlistitems(
            "PLJD13y84Bd032qVrq7CHBLEfKZZtp-u1j", None, 20
        )

        assert len(playlistitems["items"]) == 20


def test_japi_list_playlistitems_retries_incomplete_page(config, headers, monkeypatch):
    # YouTube intermittently serves a video-less "shell" playlist page that
    # raises KeyError while parsing; list_playlistitems should re-fetch instead
    # of letting a single bad response yield an empty playlist.
    from mopidy_youtube.apis import youtube_japi

    api = youtube_japi.jAPI(proxy=config["proxy"], headers=headers)

    class _Resp:
        status_code = 200

        def __init__(self, tag):
            self.text = tag

    responses = iter([_Resp("shell"), _Resp("complete")])
    monkeypatch.setattr(api.session, "get", lambda *a, **k: next(responses))
    monkeypatch.setattr(
        youtube_japi.jAPI, "_find_yt_data", staticmethod(lambda text: {"page": text})
    )

    def fake_traverse(data, path):
        if data["page"] == "shell":
            raise KeyError  # incomplete shell page — no playlistVideoListRenderer
        return ["v1", "v2"]

    monkeypatch.setattr(youtube_japi, "traverse", fake_traverse)
    monkeypatch.setattr(
        youtube_japi.jAPI, "json_to_items", staticmethod(lambda extracted: list(extracted))
    )

    result = youtube_japi.jAPI.list_playlistitems("PLfake", None, 20)

    assert result["items"] == ["v1", "v2"]  # retried past the shell page


def test_japi_list_playlistitems_gives_up_cleanly(config, headers, monkeypatch):
    # If every attempt is an unparseable shell page, return an empty-but-valid
    # result rather than raising or returning a bare list.
    from mopidy_youtube.apis import youtube_japi

    api = youtube_japi.jAPI(proxy=config["proxy"], headers=headers)

    class _Resp:
        status_code = 200
        text = "shell"

    monkeypatch.setattr(api.session, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(
        youtube_japi.jAPI, "_find_yt_data", staticmethod(lambda text: {"page": text})
    )

    def always_fail(data, path):
        raise KeyError

    monkeypatch.setattr(youtube_japi, "traverse", always_fail)

    result = youtube_japi.jAPI.list_playlistitems("PLfake", None, 20)

    assert result == {"nextPageToken": None, "items": []}


@pytest.mark.parametrize("api", apis)
def test_api_list_channelplaylists(api, config, headers):
    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/api_list_channelplaylists.yaml"
    ):
        setup_entry_api(api, config, headers)

        channel_playlists = youtube.Entry.api.list_channelplaylists(
            "UCZtGOj7FTHPd2txgnbJS2kQ"
        )

        assert isinstance(channel_playlists, dict)
        assert isinstance(channel_playlists["items"], list)
        assert len(channel_playlists["items"]) > 0

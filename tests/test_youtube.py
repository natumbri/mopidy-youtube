import pytest

from mopidy_youtube import youtube

from tests import apis, my_vcr
from tests.test_api import setup_entry_api


@pytest.mark.parametrize("api", apis)
def test_youtube_search(api, config, headers):

    with my_vcr.use_cassette(f"tests/fixtures/{api['name']}/youtube_search.yaml"):
        setup_entry_api(api, config, headers)
        youtube.Video.search_results = config["youtube"]["search_results"]
        youtube.Playlist.playlist_max_videos = config["youtube"]["playlist_max_videos"]
        search_results = youtube.Entry.search(
            "test playlist"
        )  # search needs to generate at least 1 playlist

        assert isinstance(search_results, list)

        playlists = [
            search_result
            for search_result in search_results
            if isinstance(search_result, youtube.Playlist)
        ]
        videos = [
            search_result
            for search_result in search_results
            if isinstance(search_result, youtube.Video)
        ]

        assert len(playlists) + len(videos) == len(search_results)

        assert videos[0].title.get()

        assert videos[0]._title
        assert videos[0]._thumbnails
        assert videos[0]._channel
        if api["name"] in ["japi", "music"]:
            assert videos[0]._length

        assert playlists[0]._title
        assert playlists[0]._thumbnails
        assert playlists[0]._channel
        if api["name"] in ["japi", "music"]:
            assert playlists[0]._video_count


@pytest.mark.parametrize("api", apis)
def test_youtube_get_video(api, config, headers):

    with my_vcr.use_cassette(f"tests/fixtures/{api['name']}/youtube_get_video.yaml"):
        setup_entry_api(api, config, headers)

        video = youtube.Video.get("e1YqueG2gtQ")

        assert video.length.get()
        assert video.related_videos.get()
        assert video.thumbnails.get()
        assert video.is_video is True
        assert video.channel.get()

        # get again, should fetch from cache, _length should be ready
        video2 = youtube.Video.get("e1YqueG2gtQ")

        assert video2 is video
        assert video2._length


@pytest.mark.parametrize("api", apis)
def test_audio_url(api, config, headers, youtube_dl_mock_with_video):

    setup_entry_api(api, config, headers)
    youtube.Video.proxy = None
    video = youtube.Video.get("e1YqueG2gtQ")

    assert video.audio_url.get()


@pytest.mark.parametrize("api", apis)
def test_audio_url_fail(api, config, headers, youtube_dl_mock):

    setup_entry_api(api, config, headers)
    youtube.Video.proxy = None

    youtube_dl_mock.YoutubeDL.side_effect = Exception("Removed")

    video = youtube.Video.get("unknown")

    assert not video.audio_url.get()


@pytest.mark.parametrize("api", apis)
def test_youtube_get_playlist(api, config, headers):

    with my_vcr.use_cassette(f"tests/fixtures/{api['name']}/youtube_get_playlist.yaml"):
        setup_entry_api(api, config, headers)
        youtube.Playlist.playlist_max_videos = config["youtube"]["playlist_max_videos"]
        pl = youtube.Playlist.get("PLJD13y84Bd032qVrq7CHBLEfKZZtp-u1j")

        assert pl.video_count.get()
        assert pl.thumbnails.get()
        assert pl.is_video is False
        assert pl.channel.get()

        assert len(pl.videos.get()) == 20
        assert pl.videos.get()[0].title.get()

        # Playlist.videos starts loading video info in the background
        video = pl.videos.get()[0]  # don't know what videos[0] will be
        assert video._title
        assert video._channel
        assert video._length

        # don't know what the length will be because we don't know what videos[0] is
        # not sure where the order is non-deterministic
        # assert video.length.get() == 277

        # don't know what the length will be because we don't know what videos[0] is
        # not sure where the order is non-deterministic
        assert isinstance(video.title.get(), str)
        assert isinstance(video.channel.get(), str)
        assert isinstance(video.length.get(), int)

        pl2 = youtube.Playlist.get("PLJD13y84Bd032qVrq7CHBLEfKZZtp-u1j")

        assert pl2 is pl  # fetch from cache
        assert pl._videos  # should be ready


@pytest.mark.parametrize("api", apis)
def test_youtube_channel_playlists(api, config, headers):

    with my_vcr.use_cassette(
        f"tests/fixtures/{api['name']}/youtube_channel_playlists.yaml"
    ):
        setup_entry_api(api, config, headers)
        channel_playlists = youtube.Channel.playlists("UCZtGOj7FTHPd2txgnbJS2kQ")

        assert isinstance(channel_playlists, list)
        assert len(channel_playlists) > 0

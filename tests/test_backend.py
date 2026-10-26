import json
import pathlib
from unittest import mock

import pykka
import requests
from mopidy import backend as backend_api
from mopidy.models import Track, TlTrack

from mopidy_youtube import backend, frontend, web
from mopidy_youtube.async_utils import is_future_set
from mopidy_youtube.apis.ytm_item_to_video import ytm_item_to_video
from mopidy_youtube.apis.youtube_music import Music
from mopidy_youtube.comms import Client


def make_config():
    return {
        "core": {"cache_dir": "/tmp/mopidy-cache", "data_dir": "/tmp/mopidy-data"},
        "http": {"enabled": True, "hostname": "::", "port": 6680},
        "youtube": {
            "enabled": True,
            "allow_cache": True,
            "youtube_api_key": None,
            "channel_id": None,
            "search_results": 15,
            "playlist_max_videos": 20,
            "api_enabled": False,
            "musicapi_enabled": False,
            "musicapi_cookie": None,
            "musicapi_browser_authentication_file": None,
            "musicapi_cookiefile": None,
            "history_enabled": False,
            "autoplay_enabled": False,
            "strict_autoplay": False,
            "max_autoplay_length": 600,
            "max_degrees_of_separation": 3,
            "youtube_dl_package": "yt_dlp",
        },
        "proxy": {},
    }


def test_backend_initializes_expected_provider_objects():
    instance = backend.YouTubeBackend(config=make_config(), audio=None)

    assert instance.uri_schemes == ("youtube", "yt")
    assert isinstance(instance.library, backend.YouTubeLibraryProvider)
    assert isinstance(instance.library, backend_api.LibraryProvider)
    assert isinstance(instance.playback, backend.YouTubePlaybackProvider)
    assert isinstance(instance.playback, backend_api.PlaybackProvider)


def test_video_uses_safe_default_search_limits_before_backend_config_runs():
    assert backend.youtube.Video.search_results >= 1
    assert backend.youtube.Playlist.playlist_max_videos >= 1


def test_backend_clamps_non_positive_config_limits_to_safe_minimums():
    config = make_config()
    config["youtube"]["search_results"] = 0
    config["youtube"]["playlist_max_videos"] = -5

    instance = backend.YouTubeBackend(config=config, audio=None)

    assert backend.youtube.Video.search_results == 1
    assert backend.youtube.Playlist.playlist_max_videos == 1
    assert instance.uri_schemes == ("youtube", "yt")


def test_core_listener_prefetches_audio_for_every_youtube_video_in_tracklist():
    config = make_config()
    core = mock.Mock()
    core.tracklist.get_tracks.return_value.get.return_value = [
        mock.Mock(uri="youtube:video:nvlTJrNJ5lA"),
        mock.Mock(uri="spotify:track:abc123"),
        mock.Mock(uri="yt:video:LvXoB1S45j0"),
    ]

    listener = backend.YouTubeCoreListener(config=config, core=core)

    with mock.patch("mopidy_youtube.backend.youtube.Video.get") as get_video:
        video_one = mock.Mock()
        video_two = mock.Mock()
        get_video.side_effect = [video_one, video_two]

        listener.tracklist_changed()

    assert get_video.call_count == 2
    get_video.assert_any_call("nvlTJrNJ5lA")
    get_video.assert_any_call("LvXoB1S45j0")


def test_history_listener_respects_history_enabled_flag():
    config = make_config()
    config["youtube"]["history_enabled"] = False
    core = mock.Mock()
    core.autoplayed = []
    core.tracklist.get_tracks.return_value.get.return_value = []

    listener = backend.YouTubeCoreListener(config=config, core=core)
    tl_track = mock.Mock()
    tl_track.track.uri = "youtube:video:nvlTJrNJ5lA"
    tl_track.track.length = 300000

    with mock.patch("mopidy_youtube.listener.listener.send") as send:
        listener.track_playback_ended(tl_track, 200000)

    send.assert_not_called()

    config["youtube"]["history_enabled"] = True
    with mock.patch("mopidy_youtube.listener.listener.send") as send:
        listener.track_playback_ended(tl_track, 200000)

    send.assert_called_once()


def test_tracklist_changed_prefetches_youtube_audio_in_background():
    config = make_config()
    core = mock.Mock()
    core.tracklist.get_tracks.return_value.get.return_value = []
    listener_instance = backend.YouTubeCoreListener(config=config, core=core)

    executor = mock.Mock()
    with mock.patch.object(
        backend.YouTubeCoreListener,
        "_prefetch_executor",
        executor,
        create=True,
    ):
        listener_instance.tracklist_changed()

    executor.submit.assert_called_once_with(listener_instance._prefetch_youtube_audio)
    core.tracklist.get_tracks.assert_not_called()


def test_prefetch_limits_queue_work_to_a_small_window():
    config = make_config()
    core = mock.Mock()
    ids = [f"{i:011d}" for i in range(20)]
    core.tracklist.get_tracks.return_value.get.return_value = [
        mock.Mock(uri=f"youtube:video:{video_id}") for video_id in ids
    ]
    listener = backend.YouTubeCoreListener(config=config, core=core)

    with mock.patch("mopidy_youtube.listener.youtube.Video.get") as get_video:
        get_video.return_value = mock.Mock(audio_url=None)
        listener._prefetch_youtube_audio()

    assert get_video.call_count == listener._prefetch_limit
    get_video.assert_any_call(ids[0])
    get_video.assert_any_call(ids[1])
    get_video.assert_any_call(ids[2])


def test_music_list_related_videos_submits_playlist_lookup_in_background():
    executor = mock.Mock()
    with mock.patch(
        "mopidy_youtube.apis.youtube_music.ThreadPoolExecutor",
        return_value=executor,
    ):
        with mock.patch(
            "mopidy_youtube.apis.youtube_music.youtube_japi.jAPI.list_related_videos",
            return_value={"items": []},
        ):
            with mock.patch("mopidy_youtube.apis.youtube_music.ytmusic") as ytmusic_mock:
                ytmusic_mock.get_watch_playlist.return_value = {"related": "related-id"}
                ytmusic_mock.get_song_related.return_value = [
                    {"contents": [{"videoId": "abc123", "title": "Example Track"}]}
                ]
                ytmusic_mock.get_song.return_value = {
                    "videoDetails": {
                        "videoId": "abc123",
                        "title": "Example Track",
                        "lengthSeconds": "42",
                        "thumbnail": {"thumbnails": [{"url": "https://example.com/thumb.jpg"}]},
                        "author": "Example Artist",
                    }
                }

                Music.list_related_videos("video-id")

    assert executor.submit.call_args[0][0] == Music.list_playlists
    assert isinstance(executor.submit.call_args[0][1], set)


def test_music_rebuilds_ytmusic_client_when_session_changes():
    with mock.patch("mopidy_youtube.apis.youtube_music.YTMusic") as ytmusic_factory:
        Music.session = object()
        Music._ytmusic_session = None
        ytmusic_factory.side_effect = [mock.Mock(), mock.Mock()]

        Music._ensure_ytmusic()
        Music.session = object()
        Music._ensure_ytmusic()

    assert ytmusic_factory.call_count == 2


def test_ytmusic_item_to_video_uses_song_duration_and_thumbnail_payload():
    item = {
        "videoId": "abc123defgh",
        "title": "Example Track",
        "song_duration": "225",
        "artists": [{"name": "Example Artist", "id": "artist-1"}],
        "thumbnail": {"thumbnails": [{"url": "https://example.com/thumb.jpg"}]},
    }

    converted = ytm_item_to_video(item)

    assert converted["contentDetails"]["duration"] == "PT0H03M45S"
    assert converted["snippet"]["thumbnails"]["default"]["url"] == "https://example.com/thumb.jpg"


def test_video_track_number_uses_playlist_index_for_album_tracks():
    video = backend.youtube.Video()
    video.id = "abc123defgh"
    video.__dict__["_album"] = pykka.ThreadingFuture()
    video._album.set({"name": "Example Album", "uri": "youtube:playlist:PL1234567890"})
    video.api = mock.Mock()
    video.api.list_playlistitems.return_value = {
        "items": [
            {"id": {"videoId": "zzz99988877"}},
            {"id": {"videoId": "abc123defgh"}},
            {"id": {"videoId": "yyy55544433"}},
        ]
    }

    assert video.track_no.get() == 1
    video.api.list_playlistitems.assert_called_once_with("PL1234567890", "", 50)


def test_autoplayer_keeps_autoplay_history_on_the_actor_instance():
    config = make_config()
    config["youtube"]["autoplay_enabled"] = True
    core = mock.Mock()
    core.autoplayed = pykka.ThreadingFuture()
    core.autoplayed.set([])
    core.tracklist.get_repeat.return_value.get.return_value = False
    core.tracklist.get_random.return_value.get.return_value = False
    core.tracklist.get_consume.return_value.get.return_value = False
    core.tracklist.get_tl_tracks.return_value.get.return_value = [
        TlTrack(tlid=1, track=Track(uri="youtube:video:dQw4w9WgXcQ", name="Current"))
    ]

    player = frontend.YouTubeAutoplayer(config=config, core=core)

    assert player.autoplayed == []
    player.autoplayed.append("abc123")
    assert player.autoplayed == ["abc123"]


def test_async_future_counts_none_as_resolved():
    future = pykka.ThreadingFuture()
    future.set(None)

    assert future._result is not None
    assert is_future_set(future) is True


def test_client_instances_do_not_share_a_single_session_state():
    Client.session = None

    first = Client(proxy="http://proxy-a.example:8080", headers={"x-test": "first"})
    second = Client(proxy="http://proxy-b.example:8080", headers={"x-test": "second"})

    assert first.session is not second.session
    assert first.session.proxies["http"] == "http://proxy-a.example:8080"
    assert second.session.proxies["http"] == "http://proxy-b.example:8080"
    assert first.session.headers["x-test"] == "first"
    assert second.session.headers["x-test"] == "second"


def test_client_session_preserves_existing_headers_and_adds_configured_ones():
    session = requests.Session()
    session.headers.update({"Accept-Encoding": "gzip"})

    Client._create_session(proxy="http://proxy.example:8080", headers={"x-test": "yes"}, session=session)

    assert session.headers["Accept-Encoding"] == "gzip"
    assert session.headers["x-test"] == "yes"
    assert session.proxies["http"] == "http://proxy.example:8080"


def test_video_audio_url_uses_requested_formats_url_when_direct_url_missing():
    video = backend.youtube.Video()
    video.id = "abc123defgh"
    video.proxy = None
    video.api = mock.Mock()
    video.api.session = mock.Mock()

    fake_ydl = mock.MagicMock()
    fake_ydl.__enter__.return_value = fake_ydl
    fake_ydl.extract_info.return_value = {
        "id": "abc123defgh",
        "title": "Example",
        "requested_formats": [{"url": "https://example.com/audio.mp4"}],
    }

    with mock.patch("mopidy_youtube.youtube.youtube_dl", None), mock.patch(
        "mopidy_youtube.youtube.importlib.import_module"
    ) as import_module, mock.patch(
        "mopidy_youtube.youtube.os.listdir", return_value=[]
    ), mock.patch(
        "mopidy_youtube.youtube.youtube_dl", None, create=True
    ):
        import_module.return_value.YoutubeDL.return_value = fake_ydl
        assert video.audio_url.get() == "https://example.com/audio.mp4"


def test_video_audio_url_handles_nested_requested_formats_payloads():
    info = {
        "id": "abc123defgh",
        "title": "Example",
        "requested_formats": [
            {"format_id": "audio", "formats": [{"url": "https://example.com/nested-audio.mp4"}]}
        ],
    }

    assert backend.youtube.Video._extract_audio_url(info) == "https://example.com/nested-audio.mp4"


def test_playback_translate_uri_returns_resolved_audio_url():
    provider = backend.YouTubePlaybackProvider(audio=None, backend=mock.Mock())
    video = mock.Mock()
    video.audio_url.get.return_value = "https://example.com/audio.webm"

    with mock.patch("mopidy_youtube.backend.youtube.Video.get", return_value=video):
        assert provider.translate_uri("youtube:video:testid") == "https://example.com/audio.webm"


def test_index_template_uses_event_parameter_for_context_menu_target():
    html_path = pathlib.Path(__file__).resolve().parents[1] / "mopidy_youtube" / "www" / "index.html"

    html = html_path.read_text(encoding="utf-8")

    assert "const target = e.target;" in html
    assert "event.target" not in html


def test_index_handler_handles_current_mopidy_track_metadata_shape(tmp_path):
    root = tmp_path / "webcache"
    root.mkdir()
    (root / "track.jpg").write_bytes(b"fake-jpg")
    (root / "track.json").write_text(
        json.dumps({
            "name": "Example Title",
            "artists": [{"name": "Example Artist"}],
            "album": {"name": "Example Album"},
        }),
        encoding="utf-8",
    )

    handler = web.IndexHandler.__new__(web.IndexHandler)
    handler.root = str(root)
    entries = list(handler.uri_generator())

    assert entries == [("track", "Example Title", "jpg")]


def test_autoplay_uses_mopidy_4_tl_track_object():
    config = make_config()
    config["youtube"]["autoplay_enabled"] = True
    config["youtube"]["strict_autoplay"] = False
    config["youtube"]["max_autoplay_length"] = 600

    core = mock.Mock()
    core.autoplayed = []
    core.tracklist.get_repeat.return_value.get.return_value = False
    core.tracklist.get_random.return_value.get.return_value = False
    core.tracklist.get_consume.return_value.get.return_value = False
    core.tracklist.get_tl_tracks.return_value.get.return_value = [
        TlTrack(tlid=1, track=Track(uri="youtube:video:current", name="Current"))
    ]

    player = frontend.YouTubeAutoplayer(config=config, core=core)
    tl_track = TlTrack(tlid=1, track=Track(uri="youtube:video:current", name="Current"))

    current_video = mock.Mock()
    current_video.id = "current"
    current_video.title.get.return_value = "Current"
    current_video.related_videos.get.return_value = [
        mock.Mock(
            id="next-video",
            title=mock.Mock(get=mock.Mock(return_value="Next")),
            length=mock.Mock(get=mock.Mock(return_value=180000)),
        )
    ]

    with mock.patch("mopidy_youtube.frontend.youtube.Video.get", return_value=current_video):
        player.track_playback_started(tl_track)

    core.tracklist.add.assert_called_once()
    assert player.max_autoplay_length == 600000
    assert core.tracklist.add.call_args.kwargs["uris"] == ["youtube:video:next-video"]


def test_library_lookup_returns_single_track_for_video_uri():
    provider = backend.YouTubeLibraryProvider(backend=mock.Mock())

    with mock.patch("mopidy_youtube.backend.youtube.Video.get") as get_video:
        video = mock.Mock()
        video.title.get.return_value = "Example Title"
        video.length.get.return_value = 123456
        video.channel = mock.Mock()
        video.channel.name = "Example Channel"
        video.artist = None
        video.uri = "youtube:video:nvlTJrNJ5lA"
        video.id = "nvlTJrNJ5lA"
        get_video.return_value = video

        with mock.patch(
            "mopidy_youtube.library.convert_video_to_track",
            return_value=mock.Mock(uri="youtube:video:nvlTJrNJ5lA", name="Example Title"),
        ) as convert:
            result = provider.lookup("youtube:video:nvlTJrNJ5lA")

    assert len(result) == 1
    assert result[0].uri == "youtube:video:nvlTJrNJ5lA"
    convert.assert_called_once_with(video)

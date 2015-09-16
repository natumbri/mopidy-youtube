from __future__ import unicode_literals

import mock

import pafy

import pytest

import vcr

from mopidy_youtube import youtube


@pytest.yield_fixture
def pafy_mock():
    patcher = mock.patch.object(youtube, 'pafy', spec=pafy)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def pafy_mock_with_video(pafy_mock):
    video_mock = pafy_mock.new.return_value
    video_mock.bigthumb = 'big thumb'
    video_mock.bigthumbhd = 'big thumb in hd'
    video_mock.getbestaudio.return_value.url = 'http://example.com/'
    video_mock.length = 2000
    video_mock.title = 'a title'
    video_mock.videoid = 'a video id'

    return pafy_mock


@vcr.use_cassette('tests/fixtures/youtube_playlist.yaml')
def test_playlist_resolver(pafy_mock_with_video):
    pl = youtube.Playlist.get('PLOxORm4jpOQfMU7bpfGCzDyLropIYEHuR')

    assert len(pl.videos.get()) == 60

    # get again, should fetch from cache, _videos should be ready
    pl2 = youtube.Playlist.get('PLOxORm4jpOQfMU7bpfGCzDyLropIYEHuR')

    assert pl2 is pl
    assert pl._videos

    # Playlist.videos starts loading video info in the background. Get
    # the first video's length to wait until this is finished
    assert pl.videos.get()[0].length.get() == 400


@vcr.use_cassette('tests/fixtures/youtube_search.yaml')
def test_search_yt(pafy_mock_with_video):
    videos = youtube.API.search('chvrches')

    assert len(videos) == 15


def test_resolve_track(pafy_mock_with_video):
    video = youtube.Video.get('TU3b1qyEGsE')

    assert video.pafy.get()


def test_resolve_track_failed(pafy_mock):
    pafy_mock.new.side_effect = Exception('Removed')

    video = youtube.Video.get('unknown')

    assert not video.pafy.get()


def test_resolve_track_stream(pafy_mock_with_video):
    video = youtube.Video.get('TU3b1qyEGsE')

    assert video.audio_url

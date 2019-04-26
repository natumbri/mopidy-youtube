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
def test_get_playlist():
    youtube.API.youtube_api_key = 'fake_key'
    
    pl = youtube.Playlist.get('PLOxORm4jpOQfMU7bpfGCzDyLropIYEHuR')

    assert len(pl.videos.get()) == 49
    return
    assert pl.videos.get()[0].title.get()

    # Playlist.videos starts loading video info in the background
    video = pl.videos.get()[0]
    assert video._length                # should be ready
    assert video.length.get() == 400

    pl2 = youtube.Playlist.get('PLOxORm4jpOQfMU7bpfGCzDyLropIYEHuR')

    assert pl2 is pl                    # fetch from cache
    assert pl._videos                   # should be ready


@vcr.use_cassette('tests/fixtures/youtube_search.yaml')
def test_search():
    youtube.API.youtube_api_key = 'fake_key'
    youtube.Video.search_results = 15
    videos = youtube.Entry.search('chvrches')

    assert len(videos) == 15
    assert videos[0]._title             # should be ready
    assert videos[0]._channel           # should be ready

    video = youtube.Video.get('e1YqueG2gtQ')

    assert video in videos              # cached


@vcr.use_cassette('tests/fixtures/youtube_get_video.yaml')
def test_get_video():
    video = youtube.Video.get('e1YqueG2gtQ')

    assert video.length.get()

    # get again, should fetch from cache, _length should be ready
    video2 = youtube.Video.get('e1YqueG2gtQ')

    assert video2 is video
    assert video2._length


def test_audio_url(pafy_mock_with_video):
    video = youtube.Video.get('e1YqueG2gtQ')

    assert video.audio_url.get()


def test_audio_url_fail(pafy_mock):
    pafy_mock.new.side_effect = Exception('Removed')

    video = youtube.Video.get('unknown')

    assert not video.audio_url.get()

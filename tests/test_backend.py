from __future__ import unicode_literals

import mock

import youtube_dl

import pytest

import vcr

from mopidy_youtube import backend
from mopidy_youtube.backend import YouTubeLibraryProvider


@pytest.yield_fixture
def youtube_dl_mock():
    patcher = mock.patch.object(backend, 'youtube_dl', spec=youtube_dl)
    yield patcher.start()
    patcher.stop()


@pytest.fixture
def youtube_dl_mock_with_video(youtube_dl_mock):
    video_mock = youtube_dl_mock.new.return_value
    video_mock.bigthumb = 'big thumb'
    video_mock.bigthumbhd = 'big thumb in hd'
    video_mock.getbestaudio.return_value.url = 'http://example.com/'
    video_mock.length = 2000
    video_mock.title = 'a title'
    video_mock.videoid = 'a video id'

    return youtube_dl_mock


@vcr.use_cassette('tests/fixtures/youtube_playlist_resolve.yaml')
def test_playlist_resolver(youtube_dl_mock_with_video):
    provider = YouTubeLibraryProvider(mock.PropertyMock())
    tracks = provider.lookup('PLOxORm4jpOQfMU7bpfGCzDyLropIYEHuR')

    assert len(tracks) == 104


@vcr.use_cassette('tests/fixtures/youtube_search.yaml')
def test_search_yt(youtube_dl_mock_with_video):
    videos = backend.search_youtube('chvrches')

    assert len(videos) == 15


@vcr.use_cassette('tests/fixtures/lookup_video_uri.yaml')
def test_lookup_video_uri(caplog):
    provider = YouTubeLibraryProvider(mock.PropertyMock())

    tracks = provider.lookup('C0DPdy98e4c')

    assert tracks
    track = tracks[0]
    
    assert track.title == 'TEST VIDEO'
    assert track.uri == 'yt:https://www.youtube.com/watch?v=C0DPdy98e4c'

from __future__ import unicode_literals

import unittest

import mock

import vcr

from mopidy_youtube import Extension
from mopidy_youtube import youtube


class ExtensionTest(unittest.TestCase):
    def test_get_default_config(self):
        ext = Extension()

        config = ext.get_default_config()

        self.assertIn('[youtube]', config)
        self.assertIn('enabled = true', config)

    @vcr.use_cassette('tests/fixtures/youtube_playlist.yaml')
    def test_playlist_resolver(self):
        with mock.patch('mopidy_youtube.youtube.pafy'):
            pl = youtube.Playlist.get('PLOxORm4jpOQfMU7bpfGCzDyLropIYEHuR')
            self.assertEquals(len(pl.videos.get()), 60)

            # get again, should fetch from cache, _videos should be ready
            pl2 = youtube.Playlist.get('PLOxORm4jpOQfMU7bpfGCzDyLropIYEHuR')
            self.assertIs(pl2, pl)
            self.assertTrue(pl._videos, 60)

            # Playlist.videos starts loading video info in the background. Get
            # the first video's length to wait until this is finished
            self.assertEquals(pl.videos.get()[0].length.get(), 400)

    @vcr.use_cassette('tests/fixtures/youtube_search.yaml')
    def test_search_yt(self):
        with mock.patch('mopidy_youtube.youtube.pafy'):
            videos = youtube.API.search('chvrches')
            self.assertEquals(len(videos), 15)

    def test_resolve_track(self):
        with mock.patch('mopidy_youtube.youtube.pafy'):
            video = youtube.Video.get('TU3b1qyEGsE')
            self.assertTrue(video.pafy.get())

    def test_resolve_track_failed(self):
        with mock.patch('mopidy_youtube.youtube.pafy') as pafy:
            pafy.new.side_effect = Exception('Removed')
            video = youtube.Video.get('unknown')
            self.assertFalse(video.pafy.get())

    def test_resolve_track_stream(self):
        with mock.patch('mopidy_youtube.youtube.pafy'):
            video = youtube.Video.get('TU3b1qyEGsE')
            self.assertTrue(video.audio_url)

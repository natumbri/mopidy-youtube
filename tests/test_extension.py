from __future__ import unicode_literals

import unittest

import mock
import vcr

from mopidy_youtube import Extension
from mopidy_youtube.backend import resolve_playlist
from mopidy_youtube.backend import search_youtube
from mopidy_youtube.backend import resolve_track


class ExtensionTest(unittest.TestCase):
    def test_get_default_config(self):
        ext = Extension()

        config = ext.get_default_config()

        self.assertIn('[youtube]', config)
        self.assertIn('enabled = true', config)

    @vcr.use_cassette('tests/fixtures/youtube_playlist_resolve.yaml')
    def test_playlist_resolver(self):
        with mock.patch('mopidy_youtube.backend.pafy'):
            videos = resolve_playlist('PLOxORm4jpOQfMU7bpfGCzDyLropIYEHuR')
            self.assertEquals(len(videos), 104)

    @vcr.use_cassette('tests/fixtures/youtube_search.yaml')
    def test_search_yt(self):
        with mock.patch('mopidy_youtube.backend.pafy'):
            videos = search_youtube('chvrches')
            self.assertEquals(len(videos), 15)

    @vcr.use_cassette('tests/fixtures/resolve_track.yaml')
    def test_resolve_track(self):
        with mock.patch('mopidy_youtube.backend.pafy'):
            video = resolve_track('TU3b1qyEGsE')
            self.assertTrue(video)

    @vcr.use_cassette('tests/fixtures/resolve_track_failed.yaml')
    def test_resolve_track_failed(self):
        with mock.patch('mopidy_youtube.backend.pafy') as pafy:
            pafy.new.side_effect = Exception('Removed')
            video = resolve_track('unknown')
            self.assertFalse(video)

    @vcr.use_cassette('tests/fixtures/resolve_track_stream.yaml')
    def test_resolve_track_stream(self):
        with mock.patch('mopidy_youtube.backend.pafy'):
            video = resolve_track('TU3b1qyEGsE', True)
            self.assertTrue(video)

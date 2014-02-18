from __future__ import unicode_literals

import unittest
from mopidy_youtube import Extension


class ExtensionTest(unittest.TestCase):

    def test_get_default_config(self):
        ext = Extension()

        config = ext.get_default_config()

        self.assertIn('[youtube]', config)
        self.assertIn('enabled = true', config)

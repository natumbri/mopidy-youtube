from __future__ import unicode_literals

from mopidy_youtube import Extension


def test_get_default_config():
    ext = Extension()

    config = ext.get_default_config()

    assert '[youtube]' in config
    assert 'enabled = true' in config
    assert 'api_key = AIzaSyAl1Xq9DwdE_KD4AtPaE4EJl3WZe2zCqg4' in config

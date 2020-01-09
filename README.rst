**************
Mopidy-YouTube
**************

.. image:: https://img.shields.io/pypi/v/Mopidy-YouTube.svg?style=flat
    :target: https://pypi.python.org/pypi/Mopidy-YouTube/
    :alt: Latest PyPI version

.. image:: https://img.shields.io/travis/mopidy/mopidy-youtube/develop.svg?style=flat
    :target: https://travis-ci.org/mopidy/mopidy-youtube
    :alt: Travis CI build status

.. image:: https://img.shields.io/coveralls/mopidy/mopidy-youtube/develop.svg?style=flat
    :target: https://coveralls.io/r/mopidy/mopidy-youtube?branch=develop
    :alt: Test coverage

Mopidy extension that plays sound from YouTube.


Installation
============

Make sure you already have the GStreamer plugins, especially the "bad"
collection of plugins. For example, on Debian/Ubuntu you can install it
by running::

    sudo apt-get install gstreamer1.0-plugins-bad
    
Install by running::

    pip install Mopidy-YouTube


Configuration
=============

If you want modipy-youtube to use the YouTube API, before starting Mopidy, 
you must set ``api_enabled = True``, and add your Google API key to your Mopidy configuration file::

    [youtube]
    enabled = true
    youtube_api_key = <api key you got from Google>

Other configuration options are::

    threads_max = 16
    search_results = 15
    playlist_max_videos = 20
    api_enabled = false

If api_enabled is ``True`` but the youtube_api_key supplied is not valid, the 
plugin will report an error and the API will not be used.

Usage
=====

Simply use search for filename in your MPD client or add YouTube URL to
playlist prefixed by ``yt:``.

Example video::

    yt:http://www.youtube.com/watch?v=Njpw2PVb1c0

Example for playlist::

    yt:http://www.youtube.com/playlist?list=PLeCg_YDclAETQHa8VyFUHKC_Ly0HUWUnq


Troubleshooting
===============

If the extension is slow, try setting lower values for threads_max, search_results 
and playlist_max_videos.

If resolving of URIs stops working, always try to update the youtube-dl library
first::

   pip install --upgrade youtube-dl


Project resources
=================

- `Source code <https://github.com/natumbri/mopidy-youtube>`_
- `Issue tracker <https://github.com/natumbri/mopidy-youtube/issues>`_


Credits
=======

- Original author: `Janez Troha <https://github.com/dz0ny>`_
- Current maintainer: `Nikolas Tumbri <https://github.com/natumbri>`_
- `Contributors <https://github.com/natumbri/mopidy-youtube/graphs/contributors>`_


Changelog
=========

v2.1.0a (2019-10-26)
-------------------

- Last version that supports Mopidy 2

- Last version in Python 2.7

- Major overhaul.

- Improved performance.

- Works with or without YouTube API key.

v2.0.2 (2016-01-19)
-------------------

- Fix resolving of ``youtube:video`` URIs when looking up tracks. (Fixes: #21,
  PR: #50)

- Ensure ``None`` doesn't get includes in track image lists. (PR: #48)

v2.0.1 (2015-08-19)
-------------------

- Update links to GitHub repository.

- Don't return ``None`` values to Mopidy when lookup or search returns invalid
  data. In Mopidy 1.0, this caused a crash. In Mopidy 1.1, this caused warnings
  about the YouTube backend returning invalid data. (Fixes: #28, PR: #35)

v2.0.0 (2015-04-01)
-------------------

- Require Mopidy >= 1.0.

- Update to work with the new playback API in Mopidy 1.0.

- Update to work with the new search API in Mopidy 1.0.

v1.0.2 (2015-01-02)
-------------------

- Changelog missing.

v1.0.1 (2014-05-28)
-------------------

- Changelog missing.

v0.1.0 (2014-03-06)
-------------------

- Initial release.

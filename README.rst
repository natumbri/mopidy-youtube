****************************
Mopidy-YouTube
****************************

.. image:: https://img.shields.io/pypi/v/Mopidy-YouTube
    :target: https://pypi.org/project/Mopidy-YouTube/
    :alt: Latest PyPI version

.. image:: https://img.shields.io/circleci/build/gh/natumbri/mopidy-youtube
    :target: https://circleci.com/gh/natumbri/mopidy-youtube
    :alt: CircleCI build status

.. image:: https://img.shields.io/codecov/c/gh/natumbri/mopidy-youtube
    :target: https://codecov.io/gh/natumbri/mopidy-youtube
    :alt: Test coverage

Mopidy extension that plays sound from YouTube.


Installation
============

Install from PyPI by running::

    python3 -m pip install Mopidy-Youtube==3.0

Install from github by running::

    python3 -m pip install https://github.com/natumbri/mopidy-youtube/archive/develop.zip


Make sure you already have the GStreamer plugins, especially the "bad"
collection of plugins. For example, on Debian/Ubuntu you can install it
by running::

    sudo apt-get install gstreamer1.0-plugins-bad


Configuration
=============

Before starting Mopidy, you must add configuration for
Mopidy-YouTube to your Mopidy configuration file::

    [youtube]
    enabled = true

If you want modipy-youtube to use the YouTube API, before starting Mopidy, 
you must add your Google API key to your Mopidy configuration file
and set api_enabled = true::

    [youtube]
    youtube_api_key = <api key you got from Google>
    api_enabled = false

Other configuration options are::

    [youtube]
    threads_max = 16
    search_results = 15
    playlist_max_videos = 20


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
first.


Project resources
=================

- `Source code <https://github.com/natumbri/mopidy-youtube>`_
- `Issue tracker <https://github.com/natumbri/mopidy-youtube/issues>`_
- `Changelog <https://github.com/natumbri/mopidy-youtube/blob/master/CHANGELOG.rst>`_


Credits
=======

- Original author: `Janez Troha <https://github.com/dz0ny>`_
- Current maintainer: `Nikolas Tumbri <https://github.com/natumbri>`_
- `Contributors <https://github.com/natumbri/mopidy-youtube/graphs/contributors>`_


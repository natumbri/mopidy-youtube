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


Maintainer wanted
=================

Mopidy-YouTube is currently kept on life support by the Mopidy core
developers. It is in need of a more dedicated maintainer.

If you want to be the maintainer of Mopidy-YouTube, please:

1. Make 2-3 good pull requests improving any part of the project.

2. Read and get familiar with all of the project's open issues.

3. Send a pull request removing this section and adding yourself as the
   "Current maintainer" in the "Credits" section below. In the pull request
   description, please refer to the previous pull requests and state that
   you've familiarized yourself with the open issues.

As a maintainer, you'll be given push access to the repo and the authority to
make releases to PyPI when you see fit.


Installation
============

Make sure you already have the GStreamer plugins, especially the "bad"
collection of plugins. For example, on Debian/Ubuntu you can install it
by running::

    sudo apt-get install gstreamer1.0-plugins-bad
    
For older versions of Mopidy (pre v2.0), install the plugins by running::

    sudo apt-get install gstreamer0.10-plugins-bad

Install by running::

    pip install Mopidy-YouTube


Configuration
=============

Before starting Mopidy, you must add your Google API key
to your Mopidy configuration file::

    [youtube]
    enabled = true
    youtube_api_key = <api key you got from Google>
    threads_max = 2
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

If resolving of URIs stops working, always try to update the pafy library
first::

   pip install --upgrade pafy


Project resources
=================

- `Source code <https://github.com/mopidy/mopidy-youtube>`_
- `Issue tracker <https://github.com/mopidy/mopidy-youtube/issues>`_


Credits
=======

- Original author: `Janez Troha <https://github.com/dz0ny>`_
- Current maintainer: None. Maintainer wanted, see section above.
- `Contributors <https://github.com/mopidy/mopidy-youtube/graphs/contributors>`_


Changelog
=========

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

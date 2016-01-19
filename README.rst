**************
Mopidy-YouTube
**************

.. image:: https://img.shields.io/pypi/v/Mopidy-YouTube.svg?style=flat
    :target: https://pypi.python.org/pypi/Mopidy-YouTube/
    :alt: Latest PyPI version

.. image:: https://img.shields.io/pypi/dm/Mopidy-YouTube.svg?style=flat
    :target: https://pypi.python.org/pypi/Mopidy-YouTube/
    :alt: Number of PyPI downloads

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
collection of plugins. For example, on Debian/Ubuntu you can install it by
running::

    sudo apt-get install gstreamer0.10-plugins-bad

Install by running::

    pip install Mopidy-YouTube


Configuration
=============

No configuration needed. The only supported config value is ``youtube/enabled``
which can be set to ``false`` to disable the extension.


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

**************
Mopidy-Youtube
**************

.. image:: https://img.shields.io/pypi/v/Mopidy-Youtube.svg?style=flat
    :target: https://pypi.python.org/pypi/Mopidy-Youtube/
    :alt: Latest PyPI version

.. image:: https://img.shields.io/pypi/dm/Mopidy-Youtube.svg?style=flat
    :target: https://pypi.python.org/pypi/Mopidy-Youtube/
    :alt: Number of PyPI downloads

.. image:: https://img.shields.io/travis/mopidy/mopidy-youtube/develop.svg?style=flat
    :target: https://travis-ci.org/mopidy/mopidy-youtube
    :alt: Travis CI build status

.. image:: https://img.shields.io/coveralls/mopidy/mopidy-youtube/develop.svg?style=flat
   :target: https://coveralls.io/r/mopidy/mopidy-youtube?branch=develop
   :alt: Test coverage


Mopidy extension that plays sound from Youtube.


Installation
============

Make sure you already have the GStreamer plugins, if not you can install it by
running::

    $ sudo apt-get install gstreamer0.10-plugins-bad


Install by running::

    $ pip install Mopidy-Youtube


How to use
==========

Simply use search for filename in your MPD client or add Youtube url to
playlist prefixed by ``yt:``.

Example: ``yt:http://www.youtube.com/watch?v=Njpw2PVb1c0``

Example for playlist:
``yt:http://www.youtube.com/playlist?list=PLeCg_YDclAETQHa8VyFUHKC_Ly0HUWUnq``


If resolving stops working
==========================

Update pafy library::

   pip install pafy -U


Project resources
=================

- `Source code <https://github.com/mopidy/mopidy-youtube>`_
- `Issue tracker <https://github.com/mopidy/mopidy-youtube/issues>`_
- `Download development snapshot <https://github.com/mopidy/mopidy-youtube/archive/develop.tar.gz#egg=Mopidy-Youtube-dev>`_


Changelog
=========

v2.0.1 (UNRELEASED)
-------------------

- Update links to GitHub repository.

- Don't return ``None`` values to Mopidy when lookup or search returns invalid
  data. In Mopidy 1.0, this caused a crash. In Mopidy 1.1, this caused warnings
  about the YouTube backend returning invalid data. (PR: #35)

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

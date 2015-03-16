.. image:: https://badge.waffle.io/dz0ny/mopidy-youtube.png?label=ready&title=Ready 
 :target: https://waffle.io/dz0ny/mopidy-youtube
 :alt: 'Stories in Ready'
****************************
Mopidy-Youtube
****************************

.. image:: https://pypip.in/v/Mopidy-Youtube/badge.png
    :target: https://pypi.python.org/pypi/Mopidy-Youtube/
    :alt: Latest PyPI version

.. image:: https://pypip.in/d/Mopidy-Youtube/badge.png
    :target: https://pypi.python.org/pypi/Mopidy-Youtube/
    :alt: Number of PyPI downloads

.. image:: https://travis-ci.org/dz0ny/mopidy-youtube.png?branch=master
    :target: https://travis-ci.org/dz0ny/mopidy-youtube
    :alt: Travis CI build status

.. image:: https://img.shields.io/coveralls/dz0ny/mopidy-youtube.svg
   :target: https://coveralls.io/r/dz0ny/mopidy-youtube?branch=master
   :alt: Test coverage

Mopidy extension that plays sound from Youtube


Installation
============

Make sure you already have the gstreamer plugins, if not you can install it by running::

    $ sudo apt-get install gstreamer0.10-plugins-bad


Install by running::

    $ pip install Mopidy-Youtube


Use
=============

Simply use search for filename in your MPD client or add Youtube url to playlist prefixed by ``yt:``.

Example: ``yt:http://www.youtube.com/watch?v=Njpw2PVb1c0``

Example for playlist: ``yt:http://www.youtube.com/playlist?list=PLeCg_YDclAETQHa8VyFUHKC_Ly0HUWUnq``


Project resources
=================

- `Source code <https://github.com/dz0ny/mopidy-youtube>`_
- `Issue tracker <https://github.com/dz0ny/mopidy-youtube/issues>`_
- `Download development snapshot <https://github.com/dz0ny/mopidy-youtube/archive/master.tar.gz#egg=Mopidy-Youtube-dev>`_


Changelog
=========

v0.1.0
----------------------------------------

- Initial release.

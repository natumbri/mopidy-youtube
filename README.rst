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

These installation 'instructions' are for unixy systems. It may be possible to 
install it on other systems, using other commands.  You should have a working 
`mopidy` installation before you install `mopidy-youtube`.

Depending on how your unixy system is configured, you may need to install as
superuser (eg, using `sudo`).

Install from PyPI by running::

    python3 -m pip install Mopidy-Youtube

Install from github by running::

    python3 -m pip install https://github.com/natumbri/mopidy-youtube/archive/develop.zip


Install `youtube-dl` (or a compatible package) from PyPI by running, for example::

    python3 -m pip install --upgrade youtube-dl

For more information about youtube-dl, see https://github.com/ytdl-org/youtube-dl
Other compatible (and possibly more up-to-date) libraries may include 
`yt-dlp` (https://github.com/yt-dlp/yt-dlp) and `youtube-dlc`.

If you wish to use an alternate youtube-dl library, in your configuration file
you must set the `youtube_dl_package` option:: 

    [youtube]
    youtube_dl_package = [name] : alternative package to replace "youtube-dl"


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

If you want to cache files, set allow_cache to true. The cache directory
will be the one specified for cache_dir in mopidy [core] configuration::

    allow_cache = true

Only tracks (and their related metadata and image) that are added to the
mopidy track list will be cached.  Search results are not cached.
If you want to use cached images, mopidy-HTTP must be enabled and configured
correctly.  It is bundled with Mopidy and enabled by default.

If you want mopidy-youtube to use the YouTube API, before starting Mopidy, 
you must add your Google API key to your Mopidy configuration file
and set api_enabled = true::

    youtube_api_key = <api key you got from Google>
    api_enabled = true

If you want mopidy-youtube to use YouTube Music, instead of regular YouTube, set
musicapi_enabled = true::

    musicapi_enabled = true  

The musicapi may be used with or without the youtube api.  

To use the YouTube Music api, you will also need to install an additional python
package (`ytmusicapi` >= 0.19).  Install `ytmusicapi` from PyPI, for example, 
by running::

    python3 -m pip install --upgrade ytmusicapi   

If you want to see the YouTube playlists of a channel in your mopidy library,
you need to include the channel ID in your config file::

    channel_id = <channel id>

If you want to see your own channel's private YouTube Music playlists in your
mopidy library, you need to::

    - set channel_id to the id for your own channel
    - enable the music api and 
    - set a musicapi_cookie.  

You can obtain the cookie by process mentioned in the `ytmusicapi readme <https://ytmusicapi.readthedocs.io/en/latest/setup.html#copy-authentication-headers>`_.
You only have to look out for Cookie in the network tab, not all the headers, and include
it in your config file as musicapi_cookie::

    musicapi_cookie = <cookie>  
    
mopidy-youtube can automatically play 'related' tracks after the last track in the play queue
is played.  If you want mopidy-youtube to autoplay related videos, set autoplay_enabled = true::

	[youtube]
	autoplay_enabled = true
	
If autoplay is enabled, other options are::

	strict_autoplay = [true/false]
	max_autoplay_length = [maximum length of track in seconds or None]  : defaults to 600s
	max_degrees_of_separation = [defaults to 3]

If the option strict_autoplay is set, the current tracklist is ignored and the
most related video automatically played afterwards.

The max_autoplay_length option sets the maximum length of a track that will be played
by the autoplayer.  Any interger value is acceptable; the default is 600s.
If you don't want a maximum length, include the following in mopidy.conf::

        max_autoplay_length =

Max degrees of separation controls how distantly related to the track that triggered autoplay
(the 'seed' track) the autoplayed tracks can be. For example, with the value set to the default
of 3, the first track autoplayed will be related to the seed track (one degree of separation).
The second track autoplayed will be related to the first track autoplayed (two degrees of
separation). The third track autoplayed will be related to the second track autoplayed (three
degrees of separation, the maximum). The fourth track autoplayed will be related to the seed
track (back to one degree of separation).

Other configuration options are::

    [youtube]
    threads_max = 16            : number of parallel threads to run
    search_results = 15         : maximum number of search results to return
    playlist_max_videos = 20    : maximum number of videos in a playlist to return


Usage
=====

Simply use search for filename in your MPD client or add YouTube URL or URI to
playlist prefixed by ``yt:`` or ``youtube:``.

Example video::

    [yt|youtube]:<url to youtube video>
    [yt|youtube]:video:<id>
    [yt|youtube]:video/<title>.<id>

Example for playlist::

    [yt|youtube]:<url to youtube playlist>
    [yt|youtube]:playlist:<id>
    [yt|youtube]:playlist/<title>.<id>


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


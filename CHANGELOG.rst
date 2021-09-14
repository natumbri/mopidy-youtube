*********
Changelog
*********

v3.4 (2021-04-11)
========================================

- youtube channel support
- tidy up autoplay
- fix some thumbnail stuff
- deprecate scrAPI and bs4API in favour of jAPI
- try to reduce trips to end points
- add caching (and related web client)


v3.3 (2021-04-11)
========================================

- revised backend and other fixes

v3.2 (2020-12-22)
========================================

- release to fix breaking changes and other minor bugs

v3.1 (2020-07-24)
========================================

- first python3 revision

v3.0 (2020-03-06)
========================================

- Initial python3 release.

v2.1.0 (TBA)
-------------------

- Last version that supports Mopidy 2.

- Last version in Python 2.7

- Major overhaul.

- Improved performance.

- Works with or without YouTube API key.

- Fixes many issues.

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

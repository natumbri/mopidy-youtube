from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Collection

    import requests


class YouTubeApi(Protocol):
    """What the rest of the extension needs from a source of YouTube data.

    There are three implementations: the YouTube Data API (`youtube_api.API`),
    scraping of the website (`youtube_japi.jAPI`) and YouTube Music
    (`youtube_music.Music`). All of them return payloads shaped like Data API v3
    responses (`{"items": [...]}` with `snippet` and `contentDetails`), and
    `{"items": []}`, never `None`, when there is nothing to return.
    """

    @property
    def session(self) -> requests.Session: ...

    def search(self, q: str) -> dict[str, Any]: ...

    def list_videos(self, ids: list[str]) -> dict[str, Any]: ...

    def list_playlists(self, ids: Collection[str]) -> dict[str, Any]: ...

    def list_playlistitems(
        self, playlist_id: str, page: str | None, max_results: int
    ) -> dict[str, Any]: ...

    def list_channelplaylists(self, channel_id: str | None) -> dict[str, Any]: ...

    def list_related_videos(self, video_id: str) -> dict[str, Any]: ...

    def close(self) -> None: ...


class UnconfiguredApi:
    """Stands in for the api until the backend has started."""

    @property
    def session(self) -> requests.Session:
        raise self._error()

    def search(self, q: str) -> dict[str, Any]:
        raise self._error()

    def list_videos(self, ids: list[str]) -> dict[str, Any]:
        raise self._error()

    def list_playlists(self, ids: Collection[str]) -> dict[str, Any]:
        raise self._error()

    def list_playlistitems(
        self, playlist_id: str, page: str | None, max_results: int
    ) -> dict[str, Any]:
        raise self._error()

    def list_channelplaylists(self, channel_id: str | None) -> dict[str, Any]:
        raise self._error()

    def list_related_videos(self, video_id: str) -> dict[str, Any]:
        raise self._error()

    def close(self) -> None:
        pass

    @staticmethod
    def _error() -> RuntimeError:
        return RuntimeError("the YouTube api has not been started")

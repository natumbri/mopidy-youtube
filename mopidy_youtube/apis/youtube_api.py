from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mopidy_youtube import logger
from mopidy_youtube.apis.client import Client
from mopidy_youtube.context import context

if TYPE_CHECKING:
    from collections.abc import Collection


class API(Client):
    """
    Direct access to YouTube Data API
    see https://developers.google.com/youtube/v3/docs/
    """

    endpoint = "https://www.googleapis.com/youtube/v3/"

    def __init__(
        self, proxy: str | None, headers: dict[str, str], api_key: str
    ) -> None:
        super().__init__(proxy, headers)
        self.api_key = api_key

    def search(self, q: str) -> dict[str, Any]:
        """
        search for both videos and playlists using a single API call
        see https://developers.google.com/youtube/v3/docs/search
        """

        query = {
            "part": "id, snippet",
            "fields": "items(id, snippet(title, thumbnails(default), channelTitle))",
            "maxResults": context.search_results,
            "type": "video,playlist",
            "q": q,
            "key": self.api_key,
        }
        logger.debug(f"youtube_api 'search' triggered session.get: {q}")
        result = self.session.get(self.endpoint + "search", params=query)
        return result.json()

    def list_related_videos(self, video_id: str) -> dict[str, Any]:
        """
        queries related videos for a given video_id using a single API call
        https://developers.google.com/youtube/v3/docs/search
        """

        query = {
            "relatedToVideoId": video_id,
            "part": "snippet",
            "maxResults": 20,
            "type": "video",
            "key": self.api_key,
        }
        logger.debug(
            f"youtube_api 'list_related_videos' triggered session.get: {video_id}"
        )
        result = self.session.get(self.endpoint + "search", params=query)
        return result.json()

    def list_videos(self, ids: list[str]) -> dict[str, Any]:
        """
        list videos
        see https://developers.google.com/youtube/v3/docs/videos/list
        """

        query = {
            "part": "id,snippet,contentDetails",
            "fields": "items(id,snippet(title,channelTitle,channelId),"
            "contentDetails(duration))",
            "id": ",".join(ids),
            "key": self.api_key,
        }
        logger.debug(f"youtube_api 'list_videos' triggered session.get: {ids}")
        result = self.session.get(self.endpoint + "videos", params=query)
        return result.json()

    def list_playlists(self, ids: Collection[str]) -> dict[str, Any]:
        """
        list playlists
        see https://developers.google.com/youtube/v3/docs/playlists/list
        """

        query = {
            "part": "id,snippet,contentDetails",
            "fields": "items(id,snippet(title,thumbnails,channelTitle),"
            "contentDetails(itemCount))",
            "id": ",".join(ids),
            "key": self.api_key,
        }
        logger.debug(f"youtube_api 'list_playlists' triggered session.get: {ids}")
        result = self.session.get(self.endpoint + "playlists", params=query)
        return result.json()

    def list_playlistitems(
        self, playlist_id: str, page: str | None, max_results: int
    ) -> dict[str, Any]:
        """
        list playlist items
        see https://developers.google.com/youtube/v3/docs/playlistItems/list
        """

        query = {
            "part": "id,snippet",
            "fields": "nextPageToken,"
            "items(snippet(title, resourceId(videoId), videoOwnerChannelTitle))",
            "maxResults": max_results,
            "playlistId": playlist_id,
            "key": self.api_key,
            "pageToken": page,
        }
        logger.debug(
            f"youtube_api 'list_playlistitems' triggered session.get: {playlist_id}"
        )
        result = self.session.get(self.endpoint + "playlistItems", params=query)
        return result.json()

    def list_channelplaylists(self, channel_id: str | None) -> dict[str, Any]:
        """
        list channel playlists
        see https://developers.google.com/youtube/v3/docs/playlists/list
        """

        query = {
            "part": "id,snippet,contentDetails",
            "fields": "items(id,snippet(title),contentDetails(itemCount))",
            "maxResults": 50,
            "channelId": channel_id,
            "key": self.api_key,
        }
        logger.debug(
            f"youtube_api 'list_channelplaylists' triggered session.get: {channel_id}"
        )
        result = self.session.get(self.endpoint + "playlists", params=query)
        return result.json()

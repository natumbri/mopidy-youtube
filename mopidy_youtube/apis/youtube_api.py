from mopidy_youtube import logger
from mopidy_youtube.youtube import Client, Video

youtube_api_key = None


class API(Client):
    """
    Direct access to YouTube Data API
    see https://developers.google.com/youtube/v3/docs/
    """

    endpoint = "https://www.googleapis.com/youtube/v3/"

    @classmethod
    def search(cls, q):
        """
        search for both videos and playlists using a single API call
        see https://developers.google.com/youtube/v3/docs/search
        """

        query = {
            "part": "id, snippet",
            "fields": "items(id, snippet(title, thumbnails(default), channelTitle))",
            "maxResults": Video.search_results,
            "type": "video,playlist",
            "q": q,
            "key": youtube_api_key,
        }
        logger.info("session.get triggered: search")
        result = cls.session.get(API.endpoint + "search", params=query)
        return result.json()

    @classmethod
    def list_related_videos(cls, video_id):
        """
        queries related videos to a given video_id using a single API call
        https://developers.google.com/youtube/v3/docs/search
        """

        query = {
            "relatedToVideoId": video_id,
            "part": "snippet",
            "maxResults": 20,
            "type": "video",
            "key": youtube_api_key,
        }
        logger.info("session.get triggered: list_related_videos")
        result = cls.session.get(API.endpoint + "search", params=query)
        return result.json()

    @classmethod
    def list_videos(cls, ids):
        """
        list videos
        see https://developers.google.com/youtube/v3/docs/videos/list
        """

        query = {
            "part": "id,snippet,contentDetails",
            "fields": "items(id,snippet(title,channelTitle),"
            + "contentDetails(duration))",
            "id": ",".join(ids),
            "key": youtube_api_key,
        }
        logger.info("session.get triggered: list_videos")
        result = cls.session.get(API.endpoint + "videos", params=query)
        return result.json()

    @classmethod
    def list_playlists(cls, ids):
        """
        list playlists
        see https://developers.google.com/youtube/v3/docs/playlists/list
        """

        query = {
            "part": "id,snippet,contentDetails",
            "fields": "items(id,snippet(title,thumbnails,channelTitle),"
            + "contentDetails(itemCount))",
            "id": ",".join(ids),
            "key": youtube_api_key,
        }
        logger.info("session.get triggered: list_playlists")
        result = cls.session.get(API.endpoint + "playlists", params=query)
        return result.json()

    @classmethod
    def list_playlistitems(cls, id, page, max_results):
        """
        list playlist items
        see https://developers.google.com/youtube/v3/docs/playlistItems/list
        """

        query = {
            "part": "id,snippet",
            "fields": "nextPageToken,"
            + "items(snippet(title, resourceId(videoId), videoOwnerChannelTitle))",
            "maxResults": max_results,
            "playlistId": id,
            "key": youtube_api_key,
            "pageToken": page,
        }
        logger.info("session.get triggered: list_playlistitems")
        result = cls.session.get(API.endpoint + "playlistItems", params=query)
        return result.json()

    @classmethod
    def list_channelplaylists(cls, channel_id):
        """
        list channel playlists
        see https://developers.google.com/youtube/v3/docs/playlists/list
        """

        query = {
            "part": "id,snippet,contentDetails",
            "fields": "items(id,snippet(title)," + "contentDetails(itemCount))",
            "maxResults": 50,
            "channelId": channel_id,
            "key": youtube_api_key,
        }
        logger.info("session.get triggered: list_channelplaylists")
        result = cls.session.get(API.endpoint + "playlists", params=query)
        return result.json()

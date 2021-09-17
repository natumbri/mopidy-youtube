from mopidy_youtube import logger
from mopidy_youtube.comms import Client
from mopidy_youtube.youtube import Video


class API(Client):
    """
    Direct access to YouTube Data API
    see https://developers.google.com/youtube/v3/docs/
    """

    youtube_api_key = None
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
            "key": cls.youtube_api_key,
        }
        logger.debug(f"youtube_api 'search' triggered session.get: {q}")
        result = cls.session.get(API.endpoint + "search", params=query)
        return result.json()

    @classmethod
    def list_related_videos(cls, video_id):
        """
        queries related videos for a given video_id using a single API call
        https://developers.google.com/youtube/v3/docs/search
        """

        query = {
            "relatedToVideoId": video_id,
            "part": "snippet",
            "maxResults": 20,
            "type": "video",
            "key": cls.youtube_api_key,
        }
        logger.debug(
            f"youtube_api 'list_related_videos' triggered session.get: {video_id}"
        )
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
            "key": cls.youtube_api_key,
        }
        logger.debug(f"youtube_api 'list_videos' triggered session.get: {ids}")
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
            "key": cls.youtube_api_key,
        }
        logger.debug(f"youtube_api 'list_playlists' triggered session.get: {ids}")
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
            "key": cls.youtube_api_key,
            "pageToken": page,
        }
        logger.debug(f"youtube_api 'list_playlistitems' triggered session.get: {id}")
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
            "key": cls.youtube_api_key,
        }
        logger.debug(
            f"youtube_api 'list_channelplaylists' triggered session.get: {channel_id}"
        )
        result = cls.session.get(API.endpoint + "playlists", params=query)
        return result.json()

# -*- coding: utf-8 -*-

from mopidy_youtube import logger
from youtube import Client
from youtube import Video

youtube_api_key = None

# Direct access to YouTube Data API
# https://developers.google.com/youtube/v3/docs/
#
class API(Client):
    endpoint = 'https://www.googleapis.com/youtube/v3/'

    # search for both videos and playlists using a single API call
    # https://developers.google.com/youtube/v3/docs/search
    #
    @classmethod
    def search(cls, q):
        query = {
            'part': 'id, snippet',
            'fields':
                'items(id, snippet(title, thumbnails(default), channelTitle))',  # noqa: E501
            'maxResults': Video.search_results,
            'type': 'video,playlist',
            'q': q,
            'key': youtube_api_key
        }
        logger.info('session.get triggered: search')
        result = cls.session.get(API.endpoint + 'search', params=query)
        return result.json()

    # list videos
    # https://developers.google.com/youtube/v3/docs/videos/list
    @classmethod
    def list_videos(cls, ids):
        query = {
            'part': 'id,snippet,contentDetails',
            'fields': 'items(id,snippet(title,channelTitle),'
                      + 'contentDetails(duration))',
            'id': ','.join(ids),
            'key': youtube_api_key
        }
        logger.info('session.get triggered: list_videos')
        result = cls.session.get(API.endpoint + 'videos', params=query)
        return result.json()

    # list playlists
    # https://developers.google.com/youtube/v3/docs/playlists/list
    @classmethod
    def list_playlists(cls, ids):
        query = {
            'part': 'id,snippet,contentDetails',
            'fields': 'items(id,snippet(title,thumbnails,channelTitle),'
                      + 'contentDetails(itemCount))',
            'id': ','.join(ids),
            'key': youtube_api_key
        }
        logger.info('session.get triggered: list_playlists')
        result = cls.session.get(API.endpoint + 'playlists', params=query)
        return result.json()

    # list playlist items
    # https://developers.google.com/youtube/v3/docs/playlistItems/list
    @classmethod
    def list_playlistitems(cls, id, page, max_results):
        query = {
            'part': 'id,snippet',
            'fields': 'nextPageToken,'
                      + 'items(snippet(title, resourceId(videoId), channelTitle))',
            'maxResults': max_results,
            'playlistId': id,
            'key': youtube_api_key,
            'pageToken': page,
        }
        logger.info('session.get triggered: list_playlistitems')
        result = cls.session.get(API.endpoint + 'playlistItems', params=query)
        return result.json()


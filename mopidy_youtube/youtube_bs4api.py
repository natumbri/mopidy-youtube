# -*- coding: utf-8 -*-

import json
import re

from bs4 import BeautifulSoup

from mopidy_youtube import logger

from youtube import Client, Video
from youtube_scrapi import scrAPI

# Use BS4 instead of regex
class bs4API(scrAPI):

    @classmethod
    def run_search(cls, query):
        items = []
        regex = (
            r'(?:(?:(?P<durationHours>[0-9]+)\:)?'
            r'(?P<durationMinutes>[0-9]+)\:'
            r'(?P<durationSeconds>[0-9]{2}))'
        )
        result = cls.session.get(scrAPI.endpoint+'results', params=query)
        if result.status_code == 200:
            soup = BeautifulSoup(result.text, "html.parser")
            videos = soup.find_all("div", {'class': 'yt-lockup-video'})
            for video in videos:
                duration = cls.format_duration(re.match(regex, video.find(class_ = "video-time").text))
                item = {
                    'id': {
                        'kind': 'youtube#video',
                        'videoId': video['data-context-item-id']
                    },
                    'contentDetails': {
                        'duration': 'PT'+duration,
                    },
                    'snippet': {
                        'title': video.find(class_ = "yt-lockup-title").next.text,
                        # TODO: full support for thumbnails
                        'thumbnails': {
                            'default': {
                                'url': "https://i.ytimg.com/vi/"+video['data-context-item-id']+"/default.jpg",
                                'width': 120,
                                'height': 90,
                            },
                        },
                        'channelTitle': video.find(class_ = "yt-lockup-byline").text,
                        # 'uploadDate': video.find(class_ = "yt-lockup-meta-info").find_all("li")[0].text,
                        # 'views': video.find(class_ = "yt-lockup-meta-info").find_all("li")[1].text,
                        # 'url': 'https://www.youtube.com'+video.find(class_ = "yt-lockup-title").next['href'] 
                    },
                }

                # if video.find(class_ = "yt-lockup-description") is not None:
                #   item['snippet']['description'] = video.find(class_ = "yt-lockup-description").text or "NA"
                # else:
                #   item['snippet']['description'] = "NA"

                items.append(item)

            playlists = soup.find_all("div", {'class': 'yt-lockup-playlist'})
            for playlist in playlists:
                item = {
                    'id': {
                        'kind': 'youtube#playlist',
                        'playlistId': playlist.find(class_ = "yt-lockup-title").next['href'].partition("list=")[2]
                    },
                    'contentDetails': {
                        'itemCount': playlist.find(class_ = 'formatted-video-count-label').text.split(" ")[0]
                    },
                    'snippet': {
                        'title': playlist.find(class_ = "yt-lockup-title").next.text,
                        # TODO: full support for thumbnails
                        'thumbnails': {
                            'default': {
                                'url': (
                                    "https://i.ytimg.com/vi/" +
                                    playlist.find(class_ = 'yt-lockup-thumbnail').find("a")['href'].partition('v=')[2].partition('&')[0] +
                                    '/default.jpg'), 
                                'width': 120,
                                'height': 90
                            },
                        },
                        'channelTitle': playlist.find(class_ = "yt-lockup-byline").text,
                        # 'url': 'https://www.youtube.com/playlist?list='+info['id']['playlistId'] 

                    },
                }
                # don't append radiolist playlists 
                if str(item['id']['playlistId']).startswith('PL'):
                    items.append(item)

        return items

    # list playlist items
    #
    @classmethod
    def run_list_playlistitems(cls, query):
        items = []

        regex = (
            r'(?:(?:(?P<durationHours>[0-9]+)\:)?'
            r'(?P<durationMinutes>[0-9]+)\:'
            r'(?P<durationSeconds>[0-9]{2}))'
        )

        result = cls.session.get(scrAPI.endpoint+'playlist', params=query)
        if result.status_code == 200:
            soup = BeautifulSoup(result.text, "html.parser")
            videos = soup.find_all("tr", {'class': 'pl-video'})
            for video in videos:
                duration = cls.format_duration(re.match(regex, video.find(class_ = "timestamp").text))
                item = {
                        'id': {
                            'kind': 'youtube#video',
                            'videoId': video['data-video-id']
                        },
                        'contentDetails': {
                            'duration': 'PT'+duration,
                        },
                        'snippet': {
                            'title': video['data-title'],
                            # TODO: full support for thumbnails
                            'thumbnails': {
                                'default': {
                                    'url': "https://i.ytimg.com/vi/"+video['data-video-id']+"/default.jpg",
                                    'width': 120,
                                    'height': 90,
                                },
                            },
                            'channelTitle': video.find(class_ = "pl-video-owner").find("a").text,
                        },
                    }

                items.append(item)
        return items

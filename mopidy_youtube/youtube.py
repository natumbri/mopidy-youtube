# -*- coding: utf-8 -*-
from mopidy_youtube import logger
import backend


class API:

    # test if API key works
    #
    @classmethod
    def test_api_key(cls, self):
        search_result = backend.search_youtube(
            q = ['VqfuExE7j0g'],
            youtube_api_key = self.youtube_api_key,
            processes = self.threads_max,
            max_results = self.search_results
        )
        try:
            if 'error' in search_result:
                logger.error('Error testing YouTube API key: %s', search_result)
                return False
            else:
                logger.info('Test API key successful')
                return True
        except Exception as e:
            logger.error('Search YouTube API test caused %s', e)
            return False



from __future__ import unicode_literals

import logging
import os

from mopidy import config, ext


__version__ = '2.0.0'

logger = logging.getLogger(__name__)


class Extension(ext.Extension):

    dist_name = 'Mopidy-Youtube'
    ext_name = 'youtube'
    version = __version__

    def get_default_config(self):
        conf_file = os.path.join(os.path.dirname(__file__), 'ext.conf')
        return config.read(conf_file)

    def get_config_schema(self):
        schema = super(Extension, self).get_config_schema()
        schema['search_results'] = config.Integer()
        schema['playlist_max_videos'] = config.Integer()
        schema['api_key'] = config.String()
        return schema

    def setup(self, registry):
        from .backend import YoutubeBackend
        registry.add('backend', YoutubeBackend)

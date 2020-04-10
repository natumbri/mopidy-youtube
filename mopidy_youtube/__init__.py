import logging
import pathlib

import pkg_resources
from mopidy import config, ext

__version__ = pkg_resources.get_distribution("Mopidy-YouTube").version

logger = logging.getLogger(__name__)


class Extension(ext.Extension):

    dist_name = "Mopidy-YouTube"
    ext_name = "youtube"
    version = __version__

    def get_default_config(self):
        return config.read(pathlib.Path(__file__).parent / "ext.conf")

    def get_config_schema(self):
        schema = super().get_config_schema()
        schema["youtube_api_key"] = config.String(optional=True)
        schema["threads_max"] = config.Integer(minimum=1)
        schema["search_results"] = config.Integer(minimum=1)
        schema["playlist_max_videos"] = config.Integer(minimum=1)
        schema["api_enabled"] = config.Boolean()
        schema["autoplay_enabled"] = config.Boolean(optional=True)
        schema["strict_autoplay"] = config.Boolean(optional=True)
        return schema

    def setup(self, registry):
        from .backend import YouTubeBackend
        from .frontend import YoutubeAutoplayer

        registry.add("backend", YouTubeBackend)
        registry.add("frontend", YoutubeAutoplayer)

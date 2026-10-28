import logging
import pathlib
from importlib.metadata import PackageNotFoundError, version

from mopidy import config as mopidy_config
from mopidy import ext

from mopidy_youtube.config import apply_config_schema

try:
    __version__ = version("Mopidy-YouTube")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

logger = logging.getLogger(__name__)

__all__ = ["Extension", "__version__"]


class Extension(ext.Extension):
    dist_name = "Mopidy-YouTube"
    ext_name = "youtube"
    version = __version__

    def get_default_config(self):
        return mopidy_config.read(pathlib.Path(__file__).parent / "ext.conf")

    def get_config_schema(self):
        schema = super().get_config_schema()
        return apply_config_schema(schema)

    def setup(self, registry):
        from .backend import YouTubeBackend
        from .frontend import YouTubeAutoplayer
        from .listener import YouTubeCoreListener

        registry.add("backend", YouTubeBackend)
        registry.add("frontend", YouTubeAutoplayer)
        registry.add("frontend", YouTubeCoreListener)
        registry.add("http:app", {"name": self.ext_name, "factory": self.webapp})

    def webapp(self, config, core):
        from .web import AudioHandler, ImageHandler, IndexHandler

        cache_dir = self.get_cache_dir(config)

        return [
            (
                r"/(index.html|image.html)?",
                IndexHandler,
                {"root": cache_dir, "core": core, "config": config},
            ),
            (r"/(.*\.(?:jpg|webp))", ImageHandler, {"path": cache_dir}),
            (r"/(.*\.(?:webm|m4a|mp3|ogg))", AudioHandler, {"cache_dir": cache_dir}),
        ]

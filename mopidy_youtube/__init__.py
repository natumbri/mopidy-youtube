from __future__ import annotations

import logging
import pathlib
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, override

from mopidy import config as mopidy_config
from mopidy import ext

from mopidy_youtube.config import apply_config_schema

if TYPE_CHECKING:
    from mopidy.core import CoreProxy
    from tornado.web import RequestHandler

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

    @override
    def get_default_config(self) -> str:
        return mopidy_config.read(pathlib.Path(__file__).parent / "ext.conf")

    @override
    def get_config_schema(self) -> mopidy_config.ConfigSchema:
        schema = super().get_config_schema()
        return apply_config_schema(schema)

    @override
    def setup(self, registry: ext.Registry) -> None:
        from .backend import YouTubeBackend  # noqa: PLC0415 - keep import light
        from .frontend import YouTubeAutoplayer  # noqa: PLC0415
        from .listener import YouTubeCoreListener  # noqa: PLC0415

        registry.add("backend", YouTubeBackend)
        registry.add("frontend", YouTubeAutoplayer)
        registry.add("frontend", YouTubeCoreListener)
        registry.add("http:app", {"name": self.ext_name, "factory": self.webapp})

    def webapp(
        self, config: mopidy_config.Config, core: CoreProxy
    ) -> list[tuple[str, type[RequestHandler], dict[str, Any]]]:
        from .web import AudioHandler, ImageHandler, IndexHandler  # noqa: PLC0415

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

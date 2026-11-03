from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, override

import tornado.gen
import tornado.ioloop
import tornado.iostream
import tornado.web
from mopidy.types import Uri

from mopidy_youtube import __version__, logger, youtube
from mopidy_youtube.data import extract_playlist_id, extract_video_id

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from typing import BinaryIO

    from mopidy.config import Config
    from mopidy.core import CoreProxy
    from tornado.concurrent import Future
    from tornado.http1connection import HTTP1Connection


class ImageHandler(tornado.web.StaticFileHandler):
    @override
    def get_cache_time(
        self, path: str, modified: datetime | None, mime_type: str
    ) -> int:
        return self.CACHE_MAX_AGE


class IndexHandler(tornado.web.RequestHandler):
    @override
    def initialize(self, root: Path | str, core: CoreProxy, config: Config) -> None:
        self.root = Path(root)
        self.core = core
        self.config = config

    @staticmethod
    def _track_title(track_json: Any, fallback: str) -> str:
        if not isinstance(track_json, dict):
            return fallback

        for key in ("name", "title", "comment"):
            value = track_json.get(key)
            if value:
                return value

        track = track_json.get("track")
        if isinstance(track, dict):
            value = track.get("name") or track.get("title")
            if value:
                return value

        return fallback

    @override
    def get(self, path: str) -> Future[None] | None:
        url = self.get_argument("url", None)
        image = self.get_argument("image", None)
        if url is not None:
            video_id = extract_video_id(url)
            playlist_id = extract_playlist_id(url)
            if video_id:
                self.core.tracklist.add(uris=[Uri(f"yt:video:{video_id}")])
                self.write(
                    "<!DOCTYPE html><html><head><title>Video Added</title><script>"
                    "alert('Video has been added.');window.history.back()</script>"
                    "</head></html>"
                )
            elif playlist_id:
                self.core.tracklist.add(uris=[Uri(f"yt:playlist:{playlist_id}")])
                self.write(
                    "<!DOCTYPE html><html><head><title>Playlist Added</title><script>"
                    "alert('Playlist has been added.');window.history.back()</script>"
                    "</head></html>"
                )
            else:
                self.write(
                    f"<!DOCTYPE html><html><head><title>Error</title><script>"
                    f"alert('Invalid URL: {url}');window.history.back()</script>"
                    f"</head></html>"
                )
            return None

        if image is not None:
            ext = self.get_argument("ext")
            track = self.get_argument("track", None)
            json_file = self.root / f"{image}.json"

            artists: list[str] | str = ""
            album = ""

            if json_file.is_file():
                with json_file.open() as openfile:
                    track_json = json.load(openfile)
                    if "artists" in track_json:
                        artists = [artist["name"] for artist in track_json["artists"]]
                    if "album" in track_json:
                        album = track_json["album"]["name"]

            return self.render(
                "image.html",
                image=image,
                ext=ext,
                track=track,
                artists=artists,
                album=album,
            )

        return self.render(
            "index.html", images=self.uri_generator(), version=__version__
        )

    @override
    def get_template_path(self) -> str:
        return str(Path(__file__).parent / "www")

    def uri_generator(self) -> Iterator[tuple[str, str, str]]:
        for metadata, image_id, extension in self.data_generator():
            yield (image_id, self._track_title(metadata, image_id), extension)

    def data_generator(self) -> Iterator[tuple[Any, str, str]]:
        images = [path.name for path in self.root.glob("*.jpg")] + [
            path.name for path in self.root.glob("*.webp")
        ]

        combo: list[tuple[Path, str, str]] = []
        for json_path in self.root.glob("*.json"):
            if f"{json_path.stem}.jpg" in images:
                combo.append((json_path, json_path.stem, "jpg"))
            elif f"{json_path.stem}.webp" in images:
                combo.append((json_path, json_path.stem, "webp"))

        for json_path, image_id, extension in combo:
            try:
                with json_path.open(encoding="utf-8") as openfile:
                    yield (json.load(openfile), image_id, extension)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Skipping malformed cache metadata for %s: %s", json_path, exc
                )


class AudioHandler(tornado.web.RequestHandler):
    """Serve a cached file, with Range support, while it is still being written."""

    CHUNK_SIZE = 65536
    STALL_TIMEOUT = 30  # seconds without new data before giving up

    @override
    def initialize(self, cache_dir: Path | str) -> None:
        self.cache_dir = Path(cache_dir)

    @staticmethod
    def _parse_range(header: str | None, total: int) -> tuple[int, int] | None:
        """Return (start, end) for a single satisfiable byte range, None if the
        header is absent or unsupported (serve the whole file), and raise
        ValueError if the range is unsatisfiable."""
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
        if not match or not (match[1] or match[2]):
            return None
        if match[1]:
            start = int(match[1])
            end = min(int(match[2]), total - 1) if match[2] else total - 1
        else:
            start = max(total - int(match[2]), 0)
            end = total - 1
        if start >= total or start > end:
            msg = "unsatisfiable range"
            raise ValueError(msg)
        return start, end

    @override
    async def get(self, path: str, *, include_body: bool = True) -> None:
        root = self.cache_dir.resolve()
        final_path = (root / path).resolve()
        if root not in final_path.parents:
            raise tornado.web.HTTPError(404)
        # While a download is running yt-dlp writes `<name>.part`, and renames it
        # once it is complete, so a file with the final name is always complete.
        file_path = (
            final_path
            if final_path.is_file()
            else final_path.with_name(final_path.name + ".part")
        )
        if not file_path.is_file():
            raise tornado.web.HTTPError(404)

        # total_bytes is only known on the Video that is downloading.
        total = youtube.Video.get(str(Path(path).with_suffix(""))).total_bytes
        if not total:
            if file_path != final_path:
                # the length of an unfinished file can't be guessed
                raise tornado.web.HTTPError(503)
            total = file_path.stat().st_size

        self.set_header("Content-Type", "application/octet-stream")
        self.set_header("Accept-Ranges", "bytes")

        start, end = 0, total - 1
        try:
            byte_range = self._parse_range(self.request.headers.get("Range"), total)
        except ValueError:
            self.set_status(416)
            self.set_header("Content-Range", f"bytes */{total}")
            self.finish()
            return
        if byte_range:
            start, end = byte_range
            self.set_status(206)
            self.set_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.set_header("Content-Length", str(end - start + 1))

        if not include_body:
            self.finish()
            return

        logger.debug(f"started serving {path} [{start}-{end}/{total}] to gstreamer")
        pos = start
        idle = 0.0
        known_size = 0
        try:
            with self._open(file_path, final_path) as fd:
                fd.seek(start)
                while pos <= end:
                    data = fd.read(min(self.CHUNK_SIZE, end - pos + 1))
                    if data:
                        idle = 0.0
                        self.write(data)
                        await self.flush()
                        pos += len(data)
                        continue
                    # waiting for the downloader; it is alive while the file grows
                    # (a request for the tail of the file waits on all of it)
                    size = os.fstat(fd.fileno()).st_size
                    if size > known_size:
                        known_size = size
                        idle = 0.0
                    if idle > self.STALL_TIMEOUT:  # downloader stalled or died
                        logger.warning(
                            "giving up serving %s at %d/%d", path, pos, end + 1
                        )
                        # a short body can't be finished cleanly; drop the connection
                        self._auto_finish = False
                        cast("HTTP1Connection", self.request.connection).close()
                        return
                    await tornado.gen.sleep(0.05)
                    idle += 0.05
        except tornado.iostream.StreamClosedError:
            return  # client went away
        self.finish()
        logger.debug(f"finished serving {path} [{start}-{end}] to gstreamer")

    @staticmethod
    def _open(file_path: Path, final_path: Path) -> BinaryIO:
        try:
            return file_path.open("rb")
        except FileNotFoundError:
            # the download finished, and the file was renamed, since it was found
            return final_path.open("rb")

    @override
    async def head(self, path: str) -> None:
        await self.get(path, include_body=False)

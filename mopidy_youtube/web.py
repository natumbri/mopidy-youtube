import glob
import json
import os
import pathlib
import re

import tornado.gen
import tornado.ioloop
import tornado.web
import tornado.iostream

from mopidy_youtube import __version__, logger, youtube
from mopidy_youtube.data import extract_playlist_id, extract_video_id


class ImageHandler(tornado.web.StaticFileHandler):
    def get_cache_time(self, *args):
        return self.CACHE_MAX_AGE


class IndexHandler(tornado.web.RequestHandler):
    def initialize(self, root, core, config):
        self.root = root
        self.core = core
        self.config = config

    @staticmethod
    def _track_title(track_json, fallback):
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

    def get(self, path):
        url = self.get_argument("url", None)
        image = self.get_argument("image", None)
        if url is not None:
            video_id = extract_video_id(url)
            playlist_id = extract_playlist_id(url)
            if video_id:
                self.core.tracklist.add(uris=[f"yt:video:{video_id}"])
                self.write(
                    "<!DOCTYPE html><html><head><title>Video Added</title><script>"
                    "alert('Video has been added.');window.history.back()</script>"
                    "</head></html>"
                )
            elif playlist_id:
                self.core.tracklist.add(uris=[f"yt:playlist:{playlist_id}"])
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

        elif image is not None:
            ext = self.get_argument("ext")
            track = self.get_argument("track", None)
            json_file = os.path.join(self.root, f"{image}.json")

            artists = ""
            album = ""

            if os.path.isfile(json_file):
                with open(json_file, "r") as openfile:
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

        else:
            return self.render(
                "index.html", images=self.uri_generator(), version=__version__
            )

    def get_template_path(self):
        return pathlib.Path(__file__).parent / "www"

    def uri_generator(self):
        for metadata, image_id, extension in self.data_generator():
            yield (image_id, self._track_title(metadata, image_id), extension)

    def data_generator(self):
        images = [
            os.path.basename(x) for x in glob.glob(os.path.join(self.root, "*.jpg"))
        ] + [os.path.basename(x) for x in glob.glob(os.path.join(self.root, "*.webp"))]

        json_files = glob.glob(os.path.join(self.root, "*.json"))

        combo = []
        for filename in json_files:
            if f"{os.path.splitext(os.path.basename(filename))[0]}.jpg" in images:
                combo.append(
                    (filename, os.path.splitext(os.path.basename(filename))[0], "jpg")
                )
            elif f"{os.path.splitext(os.path.basename(filename))[0]}.webp" in images:
                combo.append(
                    (filename, os.path.splitext(os.path.basename(filename))[0], "webp")
                )

        for filename in combo:
            try:
                with open(filename[0], encoding="utf-8") as openfile:
                    yield (json.load(openfile), filename[1], filename[2])
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Skipping malformed cache metadata for %s: %s", filename[0], exc
                )


class AudioHandler(tornado.web.RequestHandler):
    """Serve a cached file, with Range support, while it is still being written."""

    CHUNK_SIZE = 65536
    STALL_TIMEOUT = 30  # seconds without new data before giving up

    def initialize(self, cache_dir):
        self.cache_dir = cache_dir

    @staticmethod
    def _parse_range(header, total):
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
            raise ValueError("unsatisfiable range")
        return start, end

    async def get(self, path, include_body=True):
        root = os.path.realpath(self.cache_dir)
        file_path = os.path.realpath(os.path.join(root, path))
        if not file_path.startswith(root + os.sep) or not os.path.isfile(file_path):
            raise tornado.web.HTTPError(404)

        # total_bytes is only known on the Video that is downloading; fall back
        # to the file size (an already cached file, or a re-created Video).
        total = youtube.Video.get(
            os.path.splitext(path)[0]
        ).total_bytes or os.path.getsize(file_path)

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
            with open(file_path, "rb") as fd:
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
                        self.request.connection.close()
                        return
                    await tornado.gen.sleep(0.05)
                    idle += 0.05
        except tornado.iostream.StreamClosedError:
            return  # client went away
        self.finish()
        logger.debug(f"finished serving {path} [{start}-{end}] to gstreamer")

    async def head(self, path):
        await self.get(path, include_body=False)

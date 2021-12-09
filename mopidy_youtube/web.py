import logging
import os
import pathlib
# import time
from typing import Generator, Optional

import tornado.gen
import tornado.ioloop
import tornado.web
from tornado import httputil

from mopidy_youtube import youtube
from mopidy_youtube.data import (
    extract_playlist_id,
    extract_video_id,
)

# from tornado import httputil

from mopidy_youtube import youtube
from mopidy_youtube.data import (
    extract_playlist_id,
    extract_video_id,
)

logger = logging.getLogger(__name__)


class ImageHandler(tornado.web.StaticFileHandler):
    def get_cache_time(self, *args):
        return self.CACHE_MAX_AGE


class IndexHandler(tornado.web.RequestHandler):
    def initialize(self, root, core, config):
        self.root = root
        self.core = core
        self.config = config

        url = self.get_argument("url", None)
        if url is not None:
            video_id = extract_video_id(url)
            playlist_id = extract_playlist_id(url)
            if playlist_id:
                self.core.tracklist.add(uris=[f"yt:playlist:{playlist_id}"])
                self.write(
                    "<!DOCTYPE html><html><head><title>Playlist Added</title><script>"
                    "alert('Playlist has been added.');window.history.back()</script>"
                    "</head></html>"
                )
            elif video_id:
                self.core.tracklist.add(uris=[f"yt:video:{video_id}"])
                self.write(
                    "<!DOCTYPE html><html><head><title>Video Added</title><script>"
                    "alert('Video has been added.');window.history.back()</script>"
                    "</head></html>"
                )
            else:
                self.write(
                    f"<!DOCTYPE html><html><head><title>Error</title><script>"
                    f"alert('Invalid URL: {url}');window.history.back()</script>"
                    f"</head></html>"
                )
        else:
            return self.render("index.html", images=self.uris())

    def get_template_path(self):
        return pathlib.Path(__file__).parent / "www"

    def uris(self):
        for _, _, files in os.walk(self.root):
            yield from [file for file in files if file.endswith(".jpg")]


class AudioHandler(tornado.web.RequestHandler):
    """Keep reading file until it is all read and written.
    Allows simultaneous downloading by youtube_dl and playback of file.
    Is it necessary???"""

    def initialize(self, cache_dir):
        self.cache_dir = cache_dir

    # https://gist.github.com/seriyps/3773703
    @tornado.gen.coroutine
    def get(self, path):
        logger.info(f"started serving {path} to gstreamer")
        total_bytes = youtube.Video.get(os.path.splitext(path)[0]).total_bytes
        self.path = f"{self.cache_dir}/{path}"
        self.set_header("Content-Type", "application/octet-stream")
        self.set_header("Content-Length", total_bytes)
        self.flush()
        # "with" statement didn't work properly in this context (didn't release
        # resources when socket inproperly closed by client)
        # with open(self.path, "rb") as fd:
        #     data = fd.read()
        #     while data:
        #         self.write(data)
        #         yield tornado.gen.Task(self.flush)
        #         data = fd.read()
        bytes_written = 0
        fd = open(self.path, "rb")
        while bytes_written != total_bytes:
            data = fd.read()
            self.write(data)
            yield tornado.gen.Task(self.flush)
            bytes_written += len(data)
            # time.sleep(0.5)  # gross hack - wait to reduce calls to fd.read()
        fd.close()
        self.finish()
        logger.info(f"finished serving {path} to gstreamer")


class StaticFileAudioHandler(tornado.web.StaticFileHandler):
    def get_content_size(self) -> int:
        total_bytes = youtube.Video.get(os.path.splitext(self.path)[0]).total_bytes
        logger.info(f"total_bytes: {total_bytes}")
        return total_bytes

    @classmethod
    def get_content(
        cls, abspath: str, start: Optional[int] = None, end: Optional[int] = None
    ) -> Generator[bytes, None, None]:
        """Retrieve the content of the requested resource which is located
        at the given absolute path.
        This class method may be overridden by subclasses.  Note that its
        signature is different from other overridable class methods
        (no ``settings`` argument); this is deliberate to ensure that
        ``abspath`` is able to stand on its own as a cache key.
        This method should either return a byte string or an iterator
        of byte strings.  The latter is preferred for large files
        as it helps reduce memory fragmentation.
        .. versionadded:: 3.1
        """

        with open(abspath, "rb") as file:

            if start is not None:
                file.seek(start)

            if end is not None:
                remaining = end - (start or 0)  # type: Optional[int]

            else:
                total_bytes = youtube.Video.get(
                    os.path.splitext(os.path.basename(abspath))[0]
                ).total_bytes
                remaining = total_bytes - (start or 0)

            logger.info(f"abspath: {abspath}")
            logger.info(f"remaining: {remaining}")
            logger.info(f"start: {start}")
            logger.info(f"end: {end}")

            # no_chunk = 0
            while remaining:
                chunk_size = 64 * 1024
                if remaining < chunk_size:
                    chunk_size = remaining
                chunk = file.read(chunk_size)
                if chunk:
                    remaining -= len(chunk)
                    # no_chunk = 0
                    yield chunk
                # else:
                #     no_chunk += 1
                #     logger.info(f"no_chunk: {no_chunk}")
                #     if no_chunk == 20:  # how many no_chunk before giving up?
                #         assert remaining == 0
                #         return

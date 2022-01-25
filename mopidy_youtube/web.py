import glob
import json
import logging
import os
import pathlib

import tornado.gen
import tornado.ioloop
import tornado.web

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
            return self.render("image.html", image=image, track=self.get_argument("track", None))

        else:
            return self.render("index.html", images=self.uri_generator())

    def get_template_path(self):
        return pathlib.Path(__file__).parent / "www"

    def uri_generator(self):
        for json_line in self.data_generator():
            yield (f'{json_line["comment"]}', json_line["name"])

    def data_generator(self):
        json_pattern = os.path.join(self.root, '*.json')
        for filename in glob.glob(json_pattern):
            with open(filename) as openfile:
                yield json.load(openfile)


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

        bytes_written = 0
        fd = open(self.path, "rb")
        while bytes_written != total_bytes:
            data = fd.read()
            self.write(data)
            yield tornado.gen.Task(self.flush)
            bytes_written += len(data)
        fd.close()
        self.finish()
        logger.info(f"finished serving {path} to gstreamer")

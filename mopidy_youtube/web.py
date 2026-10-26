import glob
import json
import os
import pathlib

import tornado.gen
import tornado.ioloop
import tornado.web

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
            return self.render("index.html", images=self.uri_generator(), version=__version__)

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
                logger.warning("Skipping malformed cache metadata for %s: %s", filename[0], exc)



class AudioHandler(tornado.web.RequestHandler):
    """Serve a cached file in chunks while it is still being written."""

    def initialize(self, cache_dir):
        self.cache_dir = cache_dir

    # https://gist.github.com/seriyps/3773703
    @tornado.gen.coroutine
    def get(self, path):
        logger.debug(f"started serving {path} to gstreamer")
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
            # yield tornado.gen.Task(self.flush)
            yield self.flush()
            bytes_written += len(data)

        fd.close()
        self.finish()
        logger.debug(f"finished serving {path} to gstreamer")

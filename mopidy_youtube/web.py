import glob
import json
import os
import pathlib

import tornado.gen
import tornado.ioloop
import tornado.web

from mopidy_youtube import logger, youtube
from mopidy_youtube.data import extract_playlist_id, extract_video_id

# from PIL import Image


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
            return self.render("index.html", images=self.uri_generator())

    def get_template_path(self):
        return pathlib.Path(__file__).parent / "www"

    def uri_generator(self):
        for json_line in self.data_generator():
            yield (json_line[0]["comment"], json_line[0]["name"], json_line[2])

    def data_generator(self):
        images = [
            os.path.basename(x) for x in glob.glob(os.path.join(self.root, "*.jpg"))
        ] + [os.path.basename(x) for x in glob.glob(os.path.join(self.root, "*.webp"))]

        json_files = glob.glob(os.path.join(self.root, "*.json"))

        combo = []
        for filename in json_files:
            # logger.info(f"{os.path.splitext(os.path.basename(filename))[0]}.jpg")
            if f"{os.path.splitext(os.path.basename(filename))[0]}.jpg" in images:
                combo.append(
                    (filename, os.path.splitext(os.path.basename(filename))[0], "jpg")
                )  # ,  self.find_dominant_color(os.path.join(self.root, f"{os.path.splitext(os.path.basename(filename))[0]}.jpg"))))
            elif f"{os.path.splitext(os.path.basename(filename))[0]}.webp" in images:
                combo.append(
                    (filename, os.path.splitext(os.path.basename(filename))[0], "webp")
                )  # ,  self.find_dominant_color(os.path.join(self.root, f"{os.path.splitext(os.path.basename(filename))[0]}.webp"))))

        # for filename in sorted(combo, key=lambda element: (element[3][0], element[3][1], element[3][2])):
        for filename in combo:
            with open(filename[0]) as openfile:
                yield (json.load(openfile), filename[1], filename[2])

    # # for arranging images by dominant colour
    # def find_dominant_color(self, filename):
    #     img = Image.open(filename)
    #     img = img.convert("RGBA")
    #     img = img.resize((1, 1), resample=0)
    #     dominant_color = img.getpixel((0, 0))
    #     return dominant_color


class AudioHandler(tornado.web.RequestHandler):
    """Keep reading file until it is all read and written.
    Allows simultaneous downloading by youtube_dl and playback of file.
    Is it necessary???"""

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

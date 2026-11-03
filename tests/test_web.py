import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import tornado.web
from tornado.simple_httpclient import HTTPStreamClosedError
from tornado.testing import AsyncHTTPTestCase

from mopidy_youtube import youtube
from mopidy_youtube.web import AudioHandler

SIZE = 300_000
DATA = os.urandom(SIZE)


class AudioHandlerTest(AsyncHTTPTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name)
        self.stall_timeout = AudioHandler.STALL_TIMEOUT
        AudioHandler.STALL_TIMEOUT = 1
        super().setUp()

    def tearDown(self) -> None:
        super().tearDown()
        AudioHandler.STALL_TIMEOUT = self.stall_timeout
        self._tmp.cleanup()

    def get_app(self) -> tornado.web.Application:
        return tornado.web.Application(
            [
                (
                    r"/youtube/(.*\.(?:webm|m4a))",
                    AudioHandler,
                    {"cache_dir": self.cache_dir},
                )
            ]
        )

    def audio(self, name: str, **kwargs: Any):
        return self.fetch(f"/youtube/{name}", **kwargs)

    def write_in_background(
        self, path: Path, chunk: int, delay: float
    ) -> threading.Thread:
        def writer() -> None:
            with path.open("ab") as file:
                for i in range(0, SIZE, chunk):
                    time.sleep(delay)
                    file.write(DATA[i : i + chunk])
                    file.flush()

        path.touch()
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        return thread

    def test_serves_a_complete_file(self) -> None:
        (self.cache_dir / "done1.webm").write_bytes(DATA)

        response = self.audio("done1.webm")

        assert response.code == 200
        assert response.body == DATA
        assert response.headers["Accept-Ranges"] == "bytes"
        assert response.headers["Content-Length"] == str(SIZE)

    def test_head_returns_the_length_without_a_body(self) -> None:
        (self.cache_dir / "done2.webm").write_bytes(DATA)

        response = self.audio("done2.webm", method="HEAD")

        assert response.code == 200
        assert response.headers["Content-Length"] == str(SIZE)
        assert response.body == b""

    def test_range_requests(self) -> None:
        (self.cache_dir / "done3.webm").write_bytes(DATA)
        cases = {
            "bytes=1000-1999": (DATA[1000:2000], f"bytes 1000-1999/{SIZE}"),
            "bytes=290000-": (DATA[290000:], f"bytes 290000-{SIZE - 1}/{SIZE}"),
            "bytes=-500": (DATA[-500:], f"bytes {SIZE - 500}-{SIZE - 1}/{SIZE}"),
            f"bytes=0-{SIZE + 99}": (DATA, f"bytes 0-{SIZE - 1}/{SIZE}"),
        }

        for header, (body, content_range) in cases.items():
            response = self.audio("done3.webm", headers={"Range": header})

            assert response.code == 206, header
            assert response.body == body, header
            assert response.headers["Content-Range"] == content_range, header

    def test_unsatisfiable_range_gets_416(self) -> None:
        (self.cache_dir / "done4.webm").write_bytes(DATA)

        response = self.audio("done4.webm", headers={"Range": f"bytes={SIZE}-"})

        assert response.code == 416
        assert response.headers["Content-Range"] == f"bytes */{SIZE}"

    def test_multiple_ranges_are_ignored(self) -> None:
        (self.cache_dir / "done5.webm").write_bytes(DATA)

        response = self.audio("done5.webm", headers={"Range": "bytes=0-10,20-30"})

        assert response.code == 200
        assert response.body == DATA

    def test_missing_files_and_path_traversal_get_404(self) -> None:
        assert self.audio("nothing.webm").code == 404
        assert self.audio("..%2f..%2fetc%2fpasswd.webm").code == 404

    def test_serves_the_part_file_while_downloading_and_follows_the_rename(
        self,
    ) -> None:
        youtube.Video.get("grow1").total_bytes = SIZE
        part = self.cache_dir / "grow1.webm.part"
        writer = self.write_in_background(part, 20_000, 0.02)

        response = self.audio("grow1.webm")
        writer.join()
        part.rename(self.cache_dir / "grow1.webm")

        assert response.code == 200
        assert response.body == DATA

    def test_a_request_for_the_tail_waits_for_the_download(self) -> None:
        youtube.Video.get("grow2").total_bytes = SIZE
        part = self.cache_dir / "grow2.webm.part"
        # slower than the stall timeout overall, but always making progress
        self.write_in_background(part, 60_000, 0.4)

        response = self.audio("grow2.webm", headers={"Range": "bytes=-16"})

        assert response.code == 206
        assert response.body == DATA[-16:]

    def test_an_unfinished_file_of_unknown_length_is_unavailable(self) -> None:
        (self.cache_dir / "unknown.webm.part").write_bytes(DATA[:1000])

        assert self.audio("unknown.webm").code == 503

    def test_a_stalled_download_drops_the_connection(self) -> None:
        youtube.Video.get("stall").total_bytes = SIZE
        (self.cache_dir / "stall.webm.part").write_bytes(DATA[:1000])

        with pytest.raises(HTTPStreamClosedError):
            self.audio("stall.webm")

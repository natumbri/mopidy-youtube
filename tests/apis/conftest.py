"""Helpers for testing the api clients without the network.

`FakeYouTube` replaces a client's HTTP transport: requests are answered from
canned responses and recorded, and a request nobody planned for fails loudly.
Fixture files under `tests/fixtures/` are real responses captured from YouTube
(or from ytmusicapi), trimmed to the parts the code reads; to refresh one, fetch
the same URL again, extract the JSON and trim long lists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import requests
from requests.adapters import BaseAdapter

if TYPE_CHECKING:
    from mopidy_youtube.apis.client import Client

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load a JSON fixture, e.g. `load_fixture("japi/watch.json")`."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def yt_initial_data_page(data: Any) -> str:
    """Wrap `data` the way YouTube embeds it in its pages."""
    return f"<html><script>var ytInitialData = {json.dumps(data)};</script></html>"


class FakeYouTube(BaseAdapter):
    """A requests transport that serves canned responses."""

    def __init__(self) -> None:
        super().__init__()
        self._routes: list[tuple[str, str, bytes, int]] = []
        self.requests: list[requests.PreparedRequest] = []

    def add(
        self,
        method: str,
        url_prefix: str,
        *,
        body: str | bytes = b"",
        json_data: Any = None,
        status: int = 200,
    ) -> None:
        """Answer `method` requests whose url starts with `url_prefix`."""
        if json_data is not None:
            body = json.dumps(json_data)
        if isinstance(body, str):
            body = body.encode()
        self._routes.append((method.upper(), url_prefix, body, status))

    def attach(self, client: Client) -> None:
        client.session.mount("https://", self)
        client.session.mount("http://", self)

    def send(  # noqa: PLR0917 - signature of requests' BaseAdapter
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        self.requests.append(request)
        for method, prefix, body, status in self._routes:
            if request.method == method and (request.url or "").startswith(prefix):
                response = requests.Response()
                response.status_code = status
                response._content = body
                response.url = request.url or ""
                response.request = request
                return response
        msg = f"no fake response for {request.method} {request.url}"
        raise requests.ConnectionError(msg)

    def close(self) -> None:
        pass

    def calls(self, method: str, url_prefix: str) -> list[requests.PreparedRequest]:
        return [
            r
            for r in self.requests
            if r.method == method.upper() and (r.url or "").startswith(url_prefix)
        ]


@pytest.fixture
def youtube_site() -> FakeYouTube:
    return FakeYouTube()

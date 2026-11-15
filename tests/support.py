"""Helpers for testing without the network.

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

import httpx

if TYPE_CHECKING:
    from mopidy_youtube.apis.client import Client

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load a JSON fixture, e.g. `load_fixture("japi/watch.json")`."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def yt_initial_data_page(data: Any) -> str:
    """Wrap `data` the way YouTube embeds it in its pages."""
    return f"<html><script>var ytInitialData = {json.dumps(data)};</script></html>"


class FakeYouTube(httpx.BaseTransport):
    """An httpx transport that serves canned responses."""

    def __init__(self) -> None:
        super().__init__()
        self._routes: list[tuple[str, str, bytes, int]] = []
        self.requests: list[httpx.Request] = []

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
        """Serve the requests of `client`, which keeps its headers."""
        old = client.session
        client.session = httpx.Client(
            transport=self, headers=old.headers, follow_redirects=True
        )
        old.close()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.send(request)

    def send(
        self, request: httpx.Request, *_args: Any, **_kwargs: Any
    ) -> httpx.Response:
        self.requests.append(request)
        for method, prefix, body, status in self._routes:
            if request.method == method and str(request.url).startswith(prefix):
                return httpx.Response(status, content=body, request=request)
        msg = f"no fake response for {request.method} {request.url}"
        raise httpx.ConnectError(msg, request=request)

    def respond(
        self, request: httpx.Request, body: str | bytes, status: int = 200
    ) -> httpx.Response:
        """A response to `request`, for subclasses that answer it themselves."""
        content = body.encode() if isinstance(body, str) else body
        return httpx.Response(status, content=content, request=request)

    def calls(self, method: str, url_prefix: str) -> list[httpx.Request]:
        return [
            r
            for r in self.requests
            if r.method == method.upper() and str(r.url).startswith(url_prefix)
        ]

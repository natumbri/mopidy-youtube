from __future__ import annotations

import os
import time
from concurrent.futures.thread import ThreadPoolExecutor

import httpx

TIMEOUT = httpx.Timeout(30.0)
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"})


class RetryTransport(httpx.BaseTransport):
    """Retry connection errors and, for idempotent requests, 5xx answers.

    httpx only retries failed connections itself. The delay doubles between
    retries (none before the first), and a `Retry-After` header is respected.
    """

    def __init__(
        self,
        transport: httpx.BaseTransport,
        *,
        retries: int = 3,
        backoff_factor: float = 0.3,
        status_forcelist: frozenset[int] = frozenset({500, 502, 503, 504}),
    ) -> None:
        self._transport = transport
        self._retries = retries
        self._backoff_factor = backoff_factor
        self._status_forcelist = status_forcelist

    def _delay(self, attempt: int, response: httpx.Response | None = None) -> float:
        delay = 0.0 if attempt == 0 else self._backoff_factor * 2 ** (attempt - 1)
        retry_after = response.headers.get("retry-after") if response else None
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        return delay

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(self._retries + 1):
            last = attempt == self._retries
            try:
                response = self._transport.handle_request(request)
            except httpx.TransportError:
                if last:
                    raise
                time.sleep(self._delay(attempt))
                continue
            retry = (
                response.status_code in self._status_forcelist
                and request.method in IDEMPOTENT_METHODS
                and not last
            )
            if not retry:
                return response
            response.close()
            time.sleep(self._delay(attempt, response))
        raise AssertionError  # pragma: no cover - the loop always returns or raises

    def close(self) -> None:
        self._transport.close()


class Client:
    """Base of the api clients: an HTTP session and a thread pool, both per instance."""

    def __init__(
        self, proxy: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        self.session = self._create_session(proxy, headers)
        self.executor = ThreadPoolExecutor(
            max_workers=max(2, min(8, (os.cpu_count() or 1) + 2))
        )

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.session.close()

    @staticmethod
    def _create_session(  # noqa: PLR0913 - tuning parameters are keyword-only
        proxy: str | None = None,
        headers: dict[str, str] | None = None,
        *,
        retries: int = 3,
        backoff_factor: float = 0.3,
        status_forcelist: frozenset[int] = frozenset({500, 502, 503, 504}),
        transport: httpx.BaseTransport | None = None,
    ) -> httpx.Client:
        transport = transport or httpx.HTTPTransport(proxy=proxy)
        return httpx.Client(
            headers=headers,
            timeout=TIMEOUT,
            follow_redirects=True,
            transport=RetryTransport(
                transport,
                retries=retries,
                backoff_factor=backoff_factor,
                status_forcelist=status_forcelist,
            ),
        )

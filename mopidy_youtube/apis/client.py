from __future__ import annotations

import os
from concurrent.futures.thread import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
        status_forcelist: tuple[int, ...] = (500, 502, 503, 504),
        session: requests.Session | None = None,
    ) -> requests.Session:
        session = session or requests.Session()

        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})

        if headers:
            session.headers.update(headers)

        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

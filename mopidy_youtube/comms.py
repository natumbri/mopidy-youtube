from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class Client:
    session: requests.Session | None = None

    def __init__(self, proxy: str | None = None, headers: dict[str, str] | None = None):
        self.session = self._create_session(proxy, headers)

    @classmethod
    def _create_session(
        cls,
        proxy: str | None = None,
        headers: dict[str, str] | None = None,
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

        cls.session = session
        return session

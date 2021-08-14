import os

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from requests.packages.urllib3.util.timeout import Timeout


# is this necessary or worthwhile?  Are there any bad
# consequences that arise if timeout isn't set like this?
class MyHTTPAdapter(HTTPAdapter):
    def get(self, *args, **kwargs):
        kwargs["timeout"] = (6.05, 27)
        return super(MyHTTPAdapter, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        kwargs["timeout"] = (6.05, 27)
        return super(MyHTTPAdapter, self).post(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["timeout"] = Timeout(connect=6.05, read=27)
        return super(MyHTTPAdapter, self).init_poolmanager(*args, **kwargs)


class Client:
    time_regex = (
        r"(?:(?:(?P<durationHours>[0-9]+)\:)?"
        r"(?P<durationMinutes>[0-9]+)\:"
        r"(?P<durationSeconds>[0-9]{2}))"
    )

    def __init__(self, proxy, headers):
        if not hasattr(type(self), "session"):
            self._create_session(proxy, headers)

    @classmethod
    def _create_session(
        cls,
        proxy,
        headers,
        retries=10,
        backoff_factor=0.3,
        status_forcelist=(500, 502, 504),
        session=None,
    ):
        cls.session = session or requests.Session()
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
        )
        adapter = MyHTTPAdapter(
            max_retries=retry, pool_maxsize=min(32, os.cpu_count() + 4)
        )
        cls.session.mount("http://", adapter)
        cls.session.mount("https://", adapter)
        cls.session.proxies = {"http": proxy, "https": proxy}
        cls.session.headers = headers

    @classmethod
    def format_duration(cls, match):
        duration = ""
        if match.group("durationHours") is not None:
            duration += match.group("durationHours") + "H"
        if match.group("durationMinutes") is not None:
            duration += match.group("durationMinutes") + "M"
        if match.group("durationSeconds") is not None:
            duration += match.group("durationSeconds") + "S"
        return duration

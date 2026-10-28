from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests

    from mopidy_youtube.comms import Client


def require_session(client: type[Client]) -> requests.Session:
    """Return the client class's HTTP session, which `Client.__init__` creates."""
    session = client.session
    if session is None:
        msg = f"{client.__name__} has no HTTP session; instantiate it first"
        raise RuntimeError(msg)
    return session

from __future__ import annotations

import threading
from queue import Full

import pykka

_create_lock = threading.Lock()


def async_property(func):
    _future_name = "_" + func.__name__

    def wrapper(self):
        with _create_lock:
            future = self.__dict__.get(_future_name)
            first = future is None
            if first:
                future = self.__dict__[_future_name] = pykka.ThreadingFuture()
        if first:
            func(self)  # runs outside the lock
        return future

    return property(wrapper)


def set_once(future, value):
    """Set a pykka future; return False if it was already set."""
    try:
        future.set(value)
        return True
    except Full:
        return False


def is_future_set(future):
    """Return whether a pykka future already has a value or an exception."""
    if future is None:
        return False
    try:
        future.get(timeout=0)
    except pykka.Timeout:
        return False
    except Exception:  # noqa: BLE001 - set with an exception, which counts as set
        return True
    return True

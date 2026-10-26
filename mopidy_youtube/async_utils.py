from __future__ import annotations

import pykka


def async_property(func):
    """Create a consistent per-property ThreadingFuture wrapper.

    The property name determines the backing future name, and the future exists
    before any loading logic runs so callers always receive the same object.
    """

    _future_name = "_" + func.__name__

    def wrapper(self):
        future = self.__dict__.get(_future_name)
        if future is None:
            future = self.__dict__[_future_name] = pykka.ThreadingFuture()
            func(self)
        return future

    return property(wrapper)


def is_future_set(future):
    return future is not None and getattr(future, "_result", None) is not None

from __future__ import annotations

import threading
from queue import Full
from typing import TYPE_CHECKING, Any

import pykka

if TYPE_CHECKING:
    from collections.abc import Callable

_create_lock = threading.Lock()


def async_property(func: Callable[[Any], None]) -> property:
    """Create a property that returns a per-instance future.

    The future is stored under `_<name>` and exists before `func` runs, so
    callers always receive the same object. `func` starts the (background)
    work that eventually sets it.
    """
    future_name = "_" + func.__name__

    def wrapper(self: Any) -> pykka.ThreadingFuture[Any]:
        with _create_lock:
            future = self.__dict__.get(future_name)
            first = future is None
            if first:
                future = self.__dict__[future_name] = pykka.ThreadingFuture()
        if first:
            func(self)  # runs outside the lock
        return future

    return property(wrapper)


def set_once(future: pykka.ThreadingFuture[Any], value: Any) -> bool:
    """Set a pykka future; return False if it was already set."""
    try:
        future.set(value)
    except Full:
        return False
    return True


def is_future_set(future: pykka.ThreadingFuture[Any] | None) -> bool:
    """Return whether a pykka future already has a value or an exception."""
    if future is None:
        return False
    try:
        future.get(timeout=0)
    except pykka.Timeout:
        return False
    except Exception:
        return True
    return True

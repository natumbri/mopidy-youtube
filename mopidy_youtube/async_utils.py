from __future__ import annotations

import threading
from queue import Full
from typing import TYPE_CHECKING, Any

import pykka

from mopidy_youtube import logger

if TYPE_CHECKING:
    from collections.abc import Callable

_create_lock = threading.Lock()


def async_property(
    func: Callable[[Any], None] | None = None,
    *,
    default_factory: Callable[[], Any] = lambda: None,
) -> Any:
    """Create a property that returns a per-instance future.

    The future is stored under `_<name>` and exists before `func` runs, so
    callers always receive the same object. `func` starts the (background)
    work that eventually sets it. If `func` raises, the error is logged and the
    future is resolved with `default_factory()` rather than being left for a
    caller to wait on forever.
    """

    def decorate(func: Callable[[Any], None]) -> property:
        future_name = "_" + func.__name__

        def wrapper(self: Any) -> pykka.ThreadingFuture[Any]:
            with _create_lock:
                future = self.__dict__.get(future_name)
                first = future is None
                if first:
                    future = self.__dict__[future_name] = pykka.ThreadingFuture()
            if first:
                try:
                    func(self)  # runs outside the lock
                except Exception:
                    logger.exception("loading %s of %r failed", func.__name__, self)
                    set_once(future, default_factory())
            return future

        return property(wrapper)

    return decorate if func is None else decorate(func)


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

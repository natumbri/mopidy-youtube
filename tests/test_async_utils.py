from __future__ import annotations

import threading
from typing import Any

from mopidy_youtube.async_utils import async_property, is_future_set, set_once


class Loadable:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.loads = 0

    @async_property
    def value(self) -> None:
        self.loads += 1
        if self.fail:
            msg = "the loader failed"
            raise RuntimeError(msg)
        set_once(self._value, 42)

    @async_property(default_factory=list)
    def items(self) -> None:
        msg = "the loader failed"
        raise RuntimeError(msg)


def test_the_loader_runs_once_and_every_access_returns_the_same_future():
    loadable = Loadable()

    first, second = loadable.value, loadable.value

    assert first is second
    assert first.get(timeout=1) == 42
    assert loadable.loads == 1


def test_a_failing_loader_resolves_the_future_with_none_instead_of_raising():
    loadable = Loadable(fail=True)

    future = loadable.value

    assert future.get(timeout=1) is None
    assert loadable.loads == 1


def test_a_failing_loader_resolves_with_a_fresh_default_for_each_object():
    first, second = Loadable(), Loadable()

    first_items = first.items.get(timeout=1)
    second_items = second.items.get(timeout=1)

    assert first_items == second_items == []
    assert first_items is not second_items


def test_concurrent_first_accesses_start_a_single_load():
    loadable = Loadable()
    futures: list[Any] = []
    barrier = threading.Barrier(8)

    def access() -> None:
        barrier.wait()
        futures.append(loadable.value)

    threads = [threading.Thread(target=access) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert loadable.loads == 1
    assert len({id(future) for future in futures}) == 1


def test_set_once_keeps_the_first_value():
    loadable = Loadable()
    future = loadable.value

    assert set_once(future, 99) is False
    assert future.get(timeout=1) == 42
    assert is_future_set(future) is True

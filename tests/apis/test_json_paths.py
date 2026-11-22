from __future__ import annotations

import pytest

from mopidy_youtube.apis.json_paths import traverse, traverse_or_none

DATA = {"sidebar": {"items": [{"title": "A"}, {"title": "B"}]}}


def test_traverse_follows_keys_and_indexes():
    assert traverse(DATA, ["sidebar", "items", 1, "title"]) == "B"


def test_traverse_names_the_step_that_is_missing():
    # a bare KeyError has no message: a log line with it reads `error ""`
    with pytest.raises(KeyError) as error:
        traverse(DATA, ["sidebar", "playlistSidebarRenderer", "items"])

    assert str(error.value) == "'playlistSidebarRenderer'"


def test_traverse_fails_on_a_value_that_is_null():
    with pytest.raises(KeyError, match="items"):
        traverse({"sidebar": {"items": None}}, ["sidebar", "items"])


def test_traverse_or_none_is_none_for_a_missing_step():
    assert traverse_or_none(DATA, ["sidebar", "nope"]) is None
    assert traverse_or_none(DATA, ["sidebar", "items", 9]) is None

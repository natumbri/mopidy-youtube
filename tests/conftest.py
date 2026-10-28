from collections.abc import Iterator

import pytest

from mopidy_youtube.context import context
from mopidy_youtube.youtube import Entry

from tests.support import FakeYouTube


@pytest.fixture(autouse=True)
def reset_context() -> Iterator[None]:
    context.reset()
    yield
    context.reset()


@pytest.fixture(autouse=True)
def reset_entity_cache() -> Iterator[None]:
    Entry.cache.clear()
    yield
    Entry.cache.clear()


@pytest.fixture
def youtube_site() -> FakeYouTube:
    return FakeYouTube()

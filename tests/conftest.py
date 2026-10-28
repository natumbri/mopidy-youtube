from collections.abc import Iterator

import pytest

from mopidy_youtube.context import context


@pytest.fixture(autouse=True)
def reset_context() -> Iterator[None]:
    context.reset()
    yield
    context.reset()

from mopidy_youtube.context import Context, context


def test_reset_restores_the_defaults():
    context.search_results = 3
    context.autoplayed.append("abc")

    context.reset()

    assert context.search_results == Context().search_results
    assert context.autoplayed == []


def test_only_one_search_can_run_at_a_time():
    assert context.begin_search() is True
    assert context.begin_search() is False

    context.end_search()

    assert context.begin_search() is True

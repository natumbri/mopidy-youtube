from unittest import mock

from mopidy_youtube.context import Context, context


def test_reset_restores_defaults_and_drops_the_loaded_module():
    context.search_results = 3
    context.autoplayed.append("abc")
    context._youtube_dl = mock.Mock()

    context.reset()

    assert context.search_results == Context().search_results
    assert context.autoplayed == []
    assert context._youtube_dl is None


def test_only_one_search_can_run_at_a_time():
    assert context.begin_search() is True
    assert context.begin_search() is False

    context.end_search()

    assert context.begin_search() is True


def test_youtube_dl_is_imported_once_and_youtube_dl_is_an_alias_for_yt_dlp():
    context.youtube_dl_package = "youtube_dl"

    with mock.patch("mopidy_youtube.context.importlib.import_module") as import_module:
        first = context.youtube_dl()
        second = context.youtube_dl()

    import_module.assert_called_once_with("yt_dlp")
    assert first is second is import_module.return_value
    assert context.youtube_dl_package == "yt_dlp"

# https://stackoverflow.com/a/14049167


def deep_search(needles, haystack):
    found = []

    if not isinstance(needles, list):
        needles = [needles]

    if isinstance(haystack, dict):
        for needle in needles:
            if needle in haystack.keys():
                found.append({needle: haystack[needle]})
            elif len(haystack.keys()) > 0:
                for key in haystack.keys():
                    result = deep_search(needle, haystack[key])
                    if result:
                        found.extend(result)
    elif isinstance(haystack, list):
        for node in haystack:
            result = deep_search(needles, node)
            if result:
                found.extend(result)
    return found


# json paths

sectionListRendererContentsPath = [
    "contents",
    "twoColumnSearchResultsRenderer",
    "primaryContents",
    "sectionListRenderer",
    "contents",
]

continuationItemsPath = [
    "onResponseReceivedCommands",
    0,
    "appendContinuationItemsAction",
    "continuationItems",
]

watchVideoPath = [
    "contents",
    "twoColumnWatchNextResults",
    "results",
    "results",
    "contents",
]

relatedVideosPath = [
    "contents",
    "twoColumnWatchNextResults",
    "secondaryResults",
    "secondaryResults",
    "results",
]

playlistBasePath = [
    "contents",
    "twoColumnBrowseResultsRenderer",
    "tabs",
    0,
    "tabRenderer",
    "content",
    "sectionListRenderer",
    "contents",
    0,
    "itemSectionRenderer",
    "contents",
    0,
]

listPlaylistItemsPath = playlistBasePath + [
    "playlistVideoListRenderer",
    "contents",
]

listChannelPlaylistsPath = playlistBasePath + ["shelfRenderer", "content"]

textPath = ["runs", 0, "text"]

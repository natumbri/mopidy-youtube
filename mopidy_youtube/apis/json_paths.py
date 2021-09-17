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

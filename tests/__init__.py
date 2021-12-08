from pathlib import Path

import vcr

from mopidy_youtube import backend
from mopidy_youtube.apis import youtube_api, youtube_japi, youtube_music

my_vcr = vcr.VCR(
    record_mode="new_episodes",
    filter_query_parameters=[("key", "fake_key")],
    filter_post_data_parameters=["key"],
    decode_compressed_response=True,
)

try:
    youtube_api_key = Path("/tmp/secretkey.txt").read_text().replace("\n", "")
except Exception:
    youtube_api_key = "fake_key"


apis = [
    {
        "name": "japi",
        "class": youtube_japi.jAPI,
        "config": {"youtube": {"api_enabled": False, "youtube_api_key": None}},
    },
    {
        "name": "api",
        "class": youtube_api.API,
        "config": {
            "youtube": {"api_enabled": True, "youtube_api_key": youtube_api_key,}
        },
    },
    {
        "name": "music",
        "class": youtube_music.Music,
        "config": {
            "youtube": {
                "api_enabled": False,
                "youtube_api_key": None,
                "musicapi_enabled": True,
            }
        },
    },
]

channel_uris = [
    "youtube:channel:UCZtGOj7FTHPd2txgnbJS2kQ",
    "yt:channel:UCZtGOj7FTHPd2txgnbJS2kQ",
]

video_uris = [
    "youtube:https://www.youtube.com/watch?v=nvlTJrNJ5lA",
    "yt:https://www.youtube.com/watch?v=nvlTJrNJ5lA",
    "youtube:https://youtu.be/nvlTJrNJ5lA",
    "yt:https://youtu.be/nvlTJrNJ5lA",
    (
        "youtube:video/Tom Petty And The Heartbreakers - "
        "I Won't Back Down (Official Music Video).nvlTJrNJ5lA"
    ),
    (
        "yt:video/Tom Petty And The Heartbreakers - "
        "I Won't Back Down (Official Music Video).nvlTJrNJ5lA"
    ),
    "youtube:video:nvlTJrNJ5lA",
    "yt:video:nvlTJrNJ5lA",
    "youtube:video:LvXoB1S45j0",
]

playlist_uris = [
    (
        "youtube:https://www.youtube.com/watch?v=SIhb-kNvL6M&"
        "list=PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J"
    ),
    (
        "yt:https://www.youtube.com/watch?v=SIhb-kNvL6M&"
        "list=PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J"
    ),
    (
        "youtube:playlist/Tom Petty's greatest hits album."
        "PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J"
    ),
    (
        "yt:playlist/Tom Petty's greatest hits album."
        "PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J"
    ),
    "youtube:playlist:PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J",
    "yt:playlist:PLo4c-riVwz2miWOT3Y2VWzg2bmV4FmC8J",
]


def get_backend(config, api_config):  # , session_mock=None):
    def mergedicts(dict1, dict2):
        for k in set(dict1.keys()).union(dict2.keys()):
            if k in dict1 and k in dict2:
                if isinstance(dict1[k], dict) and isinstance(dict2[k], dict):
                    yield (k, dict(mergedicts(dict1[k], dict2[k])))
                else:
                    # If one of the values is not a dict, you can't continue merging it.
                    # Value from second dict overrides one in first and we move on.
                    yield (k, dict2[k])
                    # Alternatively, replace this with exception
                    # raiser to alert you of value conflicts
            elif k in dict1:
                yield (k, dict1[k])
            else:
                yield (k, dict2[k])

    updated_config = dict(mergedicts(config, api_config))

    obj = backend.YouTubeBackend(config=updated_config, audio=None)
    # if session_mock:
    #     obj._session = session_mock
    # else:
    #     obj._session = mock.Mock()
    #     obj._web_client = mock.Mock()
    # obj._event_loop = mock.Mock()
    return obj

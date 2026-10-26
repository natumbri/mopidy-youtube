from __future__ import annotations

from mopidy import config as mopidy_config


def apply_config_schema(schema):
    schema["enabled"] = mopidy_config.Boolean()
    schema["allow_cache"] = mopidy_config.Boolean(optional=True)
    schema["youtube_api_key"] = mopidy_config.String(optional=True)
    schema["search_results"] = mopidy_config.Integer(minimum=1)
    schema["playlist_max_videos"] = mopidy_config.Integer(minimum=1)
    schema["api_enabled"] = mopidy_config.Boolean(optional=True)
    schema["channel_id"] = mopidy_config.String(optional=True)
    schema["musicapi_enabled"] = mopidy_config.Boolean(optional=True)
    schema["musicapi_cookie"] = mopidy_config.String(optional=True)
    schema["musicapi_browser_authentication_file"] = mopidy_config.String(optional=True)
    schema["musicapi_cookiefile"] = mopidy_config.String(optional=True)
    schema["history_enabled"] = mopidy_config.Boolean(optional=True)
    schema["autoplay_enabled"] = mopidy_config.Boolean(optional=True)
    schema["strict_autoplay"] = mopidy_config.Boolean(optional=True)
    schema["max_autoplay_length"] = mopidy_config.Integer(optional=True)
    schema["max_degrees_of_separation"] = mopidy_config.Integer(minimum=0)
    schema["youtube_dl_package"] = mopidy_config.String(optional=True)
    return schema

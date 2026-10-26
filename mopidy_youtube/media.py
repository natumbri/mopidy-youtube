from __future__ import annotations


def is_live_item(item):
    if not item:
        return False

    try:
        if item.get("is_live"):
            return True
    except AttributeError:
        pass

    live_status = item.get("live_status")
    if live_status in ("is_live", "is_upcoming", "post_live"):
        return True

    content_details = item.get("contentDetails") or {}
    duration = content_details.get("duration")
    if duration in (None, "", "P0D", "PT0S"):
        item_id = item.get("id")
        if isinstance(item_id, dict) and item_id.get("kind") == "youtube#video":
            snippet = item.get("snippet") or {}
            if "liveBroadcastContent" in snippet:
                if snippet.get("liveBroadcastContent") != "none":
                    return True

    return False


def is_live_info(info):
    if not info:
        return False

    if info.get("is_live"):
        return True

    if info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        return True

    if info.get("duration") in (None, 0):
        if info.get("was_live") or info.get("is_upcoming"):
            return True

    return False


def extract_audio_url(info):
    if not isinstance(info, dict):
        return None

    def find_audio_url(node):
        if isinstance(node, dict):
            for key in ("url", "manifest_url"):
                value = node.get(key)
                if isinstance(value, str) and value:
                    return value

            for key in ("requested_formats", "formats"):
                candidate = node.get(key)
                result = find_audio_url(candidate)
                if result:
                    return result

            for value in node.values():
                result = find_audio_url(value)
                if result:
                    return result
            return None

        if isinstance(node, list):
            for item in node:
                result = find_audio_url(item)
                if result:
                    return result
            return None

        return None

    return find_audio_url(info)

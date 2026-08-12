#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import sys
from urllib.parse import parse_qs, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
ADDON_ICON = os.path.join(ADDON_PATH, "icon.png")
MEDIA_PATH = os.path.join(ADDON_PATH, "resources", "media")
LIB_PATH = os.path.join(ADDON_PATH, "resources", "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

import m4sport_core
import mediaklikk_core
from cdm_installer import ensure_widevine_cdm

_INPUTSTREAM_ADDON = "inputstream.adaptive"

_STREAM_HEADERS = (
    "User-Agent=Mozilla%2F5.0+%28X11%3B+Linux+x86_64%29+AppleWebKit%2F537.36"
    "+%28KHTML%2C+like+Gecko%29+Chrome%2F125.0.0.0+Safari%2F537.36"
    "&Referer=https%3A%2F%2Fplayer.mediaklikk.hu%2F"
)

# Map URL substrings to icon filenames in resources/media/
_URL_ICON_MAP = (
    ("m4sport.hu",  "m4sport.png"),
    ("/mtv4live",   "m4sport.png"),
    ("/mtv1live",   "m1.png"),
    ("/mtv2live",   "m2.png"),
    ("/mtv5live",   "m5.png"),
    ("/dunalive",   "duna.png"),
)


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[{ADDON_ID}] {message}", level)


def plugin_url(base_url, query):
    return f"{base_url}?{urlencode(query)}"


def _icon_for_url(url):
    for fragment, filename in _URL_ICON_MAP:
        if fragment in url:
            return os.path.join(MEDIA_PATH, filename)
    return ADDON_ICON


def _jsonrpc(method, params):
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    return json.loads(xbmc.executeJSONRPC(req))


def _ensure_inputstream_adaptive():
    """Return True if inputstream.adaptive is enabled, enabling it silently via JSON-RPC."""
    result = _jsonrpc("Addons.GetAddonDetails",
                      {"addonid": _INPUTSTREAM_ADDON, "properties": ["enabled"]})
    addon_info = result.get("result", {}).get("addon", {})
    if addon_info.get("enabled"):
        return True

    if "error" not in result and addon_info:
        # Installed but disabled — enable silently without any dialog
        enable_result = _jsonrpc("Addons.SetAddonEnabled",
                                 {"addonid": _INPUTSTREAM_ADDON, "enabled": True})
        if enable_result.get("result") == "OK":
            return True

    # Not installed — attempt auto-install (one-time only, may show install dialog)
    log("inputstream.adaptive not found, attempting install…")
    xbmc.executebuiltin(f"InstallAddon({_INPUTSTREAM_ADDON})", True)
    result = _jsonrpc("Addons.GetAddonDetails",
                      {"addonid": _INPUTSTREAM_ADDON, "properties": ["enabled"]})
    if result.get("result", {}).get("addon"):
        _jsonrpc("Addons.SetAddonEnabled", {"addonid": _INPUTSTREAM_ADDON, "enabled": True})
        return True

    xbmcgui.Dialog().ok(
        ADDON.getAddonInfo("name"),
        "inputstream.adaptive is required but could not be installed automatically.\n"
        "Please install it from the Kodi addon repository and try again.",
    )
    return False


def list_root(handle, base_url, channels):
    for idx, (name, _url, icon, _core) in enumerate(channels):
        item = xbmcgui.ListItem(label=f"{name} (Live)")
        item.setInfo("video", {"title": f"{name} (Live)"})
        item.setArt({"icon": icon, "thumb": icon})
        item.setProperty("IsPlayable", "true")
        play_url = plugin_url(base_url, {"action": "play", "ch": idx})
        xbmcplugin.addDirectoryItem(handle=handle, url=play_url, listitem=item, isFolder=False)
    xbmcplugin.endOfDirectory(handle)


def resolve_play(handle, page_url, channel_name, fetch_fn):
    stream_url, license_url = fetch_fn(page_url)
    is_hls = ".m3u8" in stream_url
    log(f"Stream URL: {stream_url}  type={'HLS' if is_hls else 'DASH'}  DRM: {bool(license_url)}")

    if not _ensure_inputstream_adaptive():
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    if license_url and not ensure_widevine_cdm():
        log("Widevine CDM unavailable — aborting playback", xbmc.LOGERROR)
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    manifest_type = "hls" if is_hls else "mpd"
    mime_type = "application/vnd.apple.mpegurl" if is_hls else "application/dash+xml"

    list_item = xbmcgui.ListItem(label=channel_name, path=stream_url)
    list_item.setInfo("video", {"title": channel_name})
    list_item.setMimeType(mime_type)
    list_item.setContentLookup(False)
    list_item.setProperty("inputstream", _INPUTSTREAM_ADDON)
    list_item.setProperty("inputstream.adaptive.manifest_type", manifest_type)
    list_item.setProperty("inputstream.adaptive.stream_headers", _STREAM_HEADERS)

    if license_url:
        list_item.setProperty("inputstream.adaptive.license_type", "com.widevine.alpha")
        list_item.setProperty(
            "inputstream.adaptive.license_key",
            f"{license_url}|Content-Type=application/octet-stream|R{{SSM}}|",
        )

    xbmcplugin.setResolvedUrl(handle, True, list_item)
    log("Stream resolved successfully")


def _get_channels():
    """Return list of (name, url, icon, core_module) for all configured channels."""
    raw = [
        # M4 Sport channels — use m4sport_core
        (
            ADDON.getSetting("channel_name") or "M4 Sport",
            ADDON.getSetting("source_page_url") or "https://mediaklikk.hu/elo/mtv4live/",
            m4sport_core,
        ),
        (
            ADDON.getSetting("channel_name_2") or "M4 Sport direct",
            ADDON.getSetting("source_page_url_2") or "https://m4sport.hu/elo",
            m4sport_core,
        ),
        # Mediaklikk channels — use mediaklikk_core
        (
            ADDON.getSetting("channel_name_3") or "M1",
            ADDON.getSetting("source_page_url_3") or "https://mediaklikk.hu/elo/mtv1live/",
            mediaklikk_core,
        ),
        (
            ADDON.getSetting("channel_name_4") or "M2",
            ADDON.getSetting("source_page_url_4") or "https://mediaklikk.hu/elo/mtv2live/",
            mediaklikk_core,
        ),
        (
            ADDON.getSetting("channel_name_5") or "Duna TV",
            ADDON.getSetting("source_page_url_5") or "https://mediaklikk.hu/elo/dunalive/",
            mediaklikk_core,
        ),
        (
            ADDON.getSetting("channel_name_6") or "M5",
            ADDON.getSetting("source_page_url_6") or "https://mediaklikk.hu/elo/mtv5live/",
            mediaklikk_core,
        ),
    ]
    return [
        (name, url, _icon_for_url(url), core)
        for name, url, core in raw
        if url.strip()
    ]


def run():
    handle   = int(sys.argv[1])
    base_url = sys.argv[0]
    params   = parse_qs(sys.argv[2][1:]) if len(sys.argv) > 2 and sys.argv[2] else {}
    action   = params.get("action", [""])[0]
    channels = _get_channels()

    if not channels:
        xbmcgui.Dialog().ok(ADDON.getAddonInfo("name"), "No channels configured. Check Settings.")
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    if action == "play":
        try:
            ch_idx = int(params.get("ch", ["0"])[0])
        except (ValueError, IndexError):
            ch_idx = 0
        channel_name, page_url, _icon, core = channels[min(ch_idx, len(channels) - 1)]
        resolve_play(handle, core.normalize_page_url(page_url), channel_name, core.fetch_stream_url)
    else:
        list_root(handle, base_url, channels)


if __name__ == "__main__":
    _handle = int(sys.argv[1])
    _params = parse_qs(sys.argv[2][1:]) if len(sys.argv) > 2 and sys.argv[2] else {}
    try:
        run()
    except Exception as exc:
        log(f"Plugin failed: {exc}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            ADDON.getAddonInfo("name"),
            f"Error: {exc}",
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        if _params.get("action", [""])[0] == "play":
            xbmcplugin.setResolvedUrl(_handle, False, xbmcgui.ListItem())
        else:
            xbmcplugin.endOfDirectory(_handle, succeeded=False)

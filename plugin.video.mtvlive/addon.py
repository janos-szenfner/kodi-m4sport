#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib
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

from cdm_installer import ensure_widevine_cdm

# NOTE: the stream-extraction cores are deliberately NOT imported here.
# Each channel names its core module and it is imported only when that
# channel is played (see _load_core).  This keeps the channel groups
# isolated: a broken edit in mediaklikk_core.py cannot stop M4 Sport from
# playing, and cannot stop the channel list from opening at all.
_INPUTSTREAM_ADDON = "inputstream.adaptive"

# Fallback only — a core module may override it with its own STREAM_HEADERS.
_DEFAULT_STREAM_HEADERS = (
    "User-Agent=Mozilla%2F5.0+%28X11%3B+Linux+x86_64%29+AppleWebKit%2F537.36"
    "+%28KHTML%2C+like+Gecko%29+Chrome%2F125.0.0.0+Safari%2F537.36"
    "&Referer=https%3A%2F%2Fplayer.mediaklikk.hu%2F"
)

# Map URL substrings to icon filenames in resources/media/
_URL_ICON_MAP = (
    ("m4sport.hu",      "m4sport.png"),
    ("/mtv4plus",       "m4plusz.png"),
    ("/mtv4live",       "m4sport.png"),
    ("/mtv1live",       "m1.png"),
    ("/mtv2live",       "m2.png"),
    ("/mtv5live",       "m5.png"),
    ("/dunaworldlive",  "dunaworld.png"),
    ("/dunalive",       "duna.png"),
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
    for ch_id, name, _url, icon, _core_name in channels:
        item = xbmcgui.ListItem(label=f"{name} (Live)")
        item.setInfo("video", {"title": f"{name} (Live)"})
        item.setArt({"icon": icon, "thumb": icon})
        item.setProperty("IsPlayable", "true")
        play_url = plugin_url(base_url, {"action": "play", "ch": ch_id})
        xbmcplugin.addDirectoryItem(handle=handle, url=play_url, listitem=item, isFolder=False)
    xbmcplugin.endOfDirectory(handle)


def resolve_play(handle, page_url, channel_name, core, icon=None):
    stream_url, license_url = core.fetch_stream_url(page_url)
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
    # Give the playing item its own channel art explicitly. Without this the
    # resolved item carries no art and Kodi falls back to whatever it has
    # cached for the plugin path, which is what makes the add-on's own icon
    # appear to change to the last channel played.
    if icon:
        list_item.setArt({"icon": icon, "thumb": icon})
    list_item.setMimeType(mime_type)
    list_item.setContentLookup(False)
    list_item.setProperty("inputstream", _INPUTSTREAM_ADDON)
    list_item.setProperty("inputstream.adaptive.manifest_type", manifest_type)
    list_item.setProperty(
        "inputstream.adaptive.stream_headers",
        getattr(core, "STREAM_HEADERS", _DEFAULT_STREAM_HEADERS),
    )

    if license_url:
        list_item.setProperty("inputstream.adaptive.license_type", "com.widevine.alpha")
        list_item.setProperty(
            "inputstream.adaptive.license_key",
            f"{license_url}|Content-Type=application/octet-stream|R{{SSM}}|",
        )

    xbmcplugin.setResolvedUrl(handle, True, list_item)
    log("Stream resolved successfully")


# (stable id, name setting, default name, url setting, default url, core module name)
#
# The "stable id" is what gets written into playback URLs, so Kodi favourites
# and bookmarks keep pointing at the same channel even if other channels are
# renamed, reordered or blanked out in Settings.  Never reuse or rename an id.
#
# "core module name" is imported lazily, by name — see _load_core.
_CHANNEL_DEFS = (
    # M4 Sport channels — m4sport_core
    ("m4sport", "channel_name", "M4 Sport",
     "source_page_url", "https://mediaklikk.hu/elo/mtv4live/", "m4sport_core"),
    ("m4sport_direct", "channel_name_2", "M4 Sport direct",
     "source_page_url_2", "https://m4sport.hu/elo", "m4sport_core"),
    # Note: M4 Sport+ breaks the "<slug>live" convention the others follow —
    # its live page really is /elo/mtv4plus/, with no "live" suffix.
    ("m4plusz", "channel_name_7", "M4 Sport+",
     "source_page_url_7", "https://mediaklikk.hu/elo/mtv4plus/", "m4sport_core"),
    # Mediaklikk channels — mediaklikk_core
    ("m1", "channel_name_3", "M1",
     "source_page_url_3", "https://mediaklikk.hu/elo/mtv1live/", "mediaklikk_core"),
    ("m2", "channel_name_4", "M2",
     "source_page_url_4", "https://mediaklikk.hu/elo/mtv2live/", "mediaklikk_core"),
    ("duna", "channel_name_5", "Duna TV",
     "source_page_url_5", "https://mediaklikk.hu/elo/dunalive/", "mediaklikk_core"),
    ("dunaworld", "channel_name_8", "Duna World",
     "source_page_url_8", "https://mediaklikk.hu/elo/dunaworldlive/", "mediaklikk_core"),
    ("m5", "channel_name_6", "M5",
     "source_page_url_6", "https://mediaklikk.hu/elo/mtv5live/", "mediaklikk_core"),
)


def _load_core(module_name):
    """Import a stream-extraction core on demand.

    Imported here rather than at module scope so that a broken core only
    breaks the channels that use it.
    """
    try:
        return importlib.import_module(module_name)
    except Exception as exc:
        raise RuntimeError(f"Stream module '{module_name}' failed to load: {exc}") from exc


def _get_channels():
    """Return list of (ch_id, name, url, icon, core_name) for all configured channels."""
    channels = []
    for ch_id, name_setting, name_default, url_setting, url_default, core_name in _CHANNEL_DEFS:
        url = ADDON.getSetting(url_setting) or url_default
        if not url.strip():
            continue
        name = ADDON.getSetting(name_setting) or name_default
        channels.append((ch_id, name, url, _icon_for_url(url), core_name))
    return channels


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
        requested = params.get("ch", [""])[0]
        selected = next((c for c in channels if c[0] == requested), None)
        if selected is None:
            # Backwards compatibility with favourites saved when "ch" was a
            # positional index.
            try:
                selected = channels[min(int(requested), len(channels) - 1)]
            except (ValueError, TypeError):
                log(f"Unknown channel '{requested}'", xbmc.LOGERROR)
                xbmcgui.Dialog().notification(
                    ADDON.getAddonInfo("name"),
                    f"Unknown channel: {requested}",
                    xbmcgui.NOTIFICATION_ERROR,
                    5000,
                )
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
                return
        _ch_id, channel_name, page_url, icon, core_name = selected
        core = _load_core(core_name)
        resolve_play(handle, core.normalize_page_url(page_url), channel_name, core, icon)
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

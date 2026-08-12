#!/usr/bin/env python3
"""
Extract a playable live stream URL from mediaklikk.hu / m4sport.hu live pages
and optionally open it in VLC.

Usage:
  python3 m4sport-vlc.py                        # list channels, play first (M4 Sport)
  python3 m4sport-vlc.py --channel m1           # play M1 by short name
  python3 m4sport-vlc.py --channel duna         # play Duna TV
  python3 m4sport-vlc.py https://...            # any mediaklikk live page URL
  python3 m4sport-vlc.py --list                 # show all known channels
  python3 m4sport-vlc.py --open-vlc             # resolve + launch VLC
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from urllib.parse import urlencode, urlparse, urlunparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

CHANNELS: dict[str, tuple[str, str]] = {
    "m4sport":  ("M4 Sport",       "https://mediaklikk.hu/elo/mtv4live/"),
    "m4direct": ("M4 Sport direct","https://m4sport.hu/elo/"),
    "m1":       ("M1",             "https://mediaklikk.hu/elo/mtv1live/"),
    "m2":       ("M2",             "https://mediaklikk.hu/elo/mtv2live/"),
    "duna":     ("Duna TV",        "https://mediaklikk.hu/elo/dunalive/"),
    "m5":       ("M5",             "https://mediaklikk.hu/elo/mtv5live/"),
}

DEFAULT_CHANNEL = "m4sport"


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url.lstrip("/")
        parsed = urlparse(url)
    if not parsed.path.endswith("/"):
        url = urlunparse(parsed._replace(path=parsed.path + "/"))
    return url


def _extract_stream_id(page_html: str) -> str:
    # Matches both JS assignment (streamId = 'x') and JSON property ("streamId":"x")
    match = re.search(r"""streamId['"]\s*[=:]\s*['"]([^'"]+)['"]""", page_html)
    if not match:
        match = re.search(r"""streamId\s*=\s*['"]([^'"]+)['"]""", page_html)
    if not match:
        raise RuntimeError("Could not find streamId on the live page.")
    return match.group(1)


def _build_player_url(stream_id: str, page_url: str) -> str:
    query = urlencode({
        "video": stream_id,
        "autostart": "false",
        "embedded": "0",
        "mute": "false",
        "sourceUrl": page_url,
    })
    return f"https://player.mediaklikk.hu/playernew/player.php?{query}"


def _extract_stream_url(player_html: str) -> tuple[str, str | None]:
    """Return (stream_url, widevine_license_url_or_None), skipping bumper entries."""
    playlist_match = re.search(r'"playlist"\s*:\s*(\[.+?\])\s*\}', player_html, re.DOTALL)
    if playlist_match:
        try:
            playlist = json.loads(playlist_match.group(1))
            for item in playlist:
                file_url = item.get("file", "")
                if not file_url or "Bumper" in file_url:
                    continue
                license_url = None
                drm = item.get("drm", {})
                if drm.get("widevine", {}).get("url"):
                    license_url = drm["widevine"]["url"]
                return file_url, license_url
        except (ValueError, KeyError):
            pass

    for m in re.finditer(r'"file"\s*:\s*"([^"]+\.(?:m3u8|mpd)[^"]*)"', player_html):
        url = json.loads(f'"{m.group(1)}"')
        if "Bumper" not in url:
            return url, None

    raise RuntimeError("Could not find a stream URL (.m3u8/.mpd) in player output.")


def resolve(page_url: str, timeout: float) -> tuple[str, str | None]:
    """Return (stream_url, license_url_or_None) for the given live page URL."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    page_resp = session.get(page_url, timeout=timeout)
    page_resp.raise_for_status()
    stream_id = _extract_stream_id(page_resp.text)

    player_url = _build_player_url(stream_id, page_url)
    player_resp = session.get(player_url, headers={"Referer": page_url}, timeout=timeout)
    player_resp.raise_for_status()

    return _extract_stream_url(player_resp.text)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a Hungarian public TV live stream URL for VLC or other players.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(
            f"  {k:10}  {name}  ({url})"
            for k, (name, url) in CHANNELS.items()
        ),
    )
    parser.add_argument(
        "page_url",
        nargs="?",
        default=None,
        help="Mediaklikk live page URL (overrides --channel)",
    )
    parser.add_argument(
        "--channel", "-c",
        choices=list(CHANNELS),
        default=DEFAULT_CHANNEL,
        metavar="NAME",
        help=f"Channel short name (default: {DEFAULT_CHANNEL}). One of: {', '.join(CHANNELS)}",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all known channels and exit.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="HTTP timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--open-vlc",
        action="store_true",
        help="Launch VLC immediately with the resolved URL.",
    )
    args = parser.parse_args()

    if args.list:
        print("Known channels:")
        for key, (name, url) in CHANNELS.items():
            print(f"  {key:10}  {name:20}  {url}")
        return 0

    if args.page_url:
        page_url = _normalize_url(args.page_url)
    else:
        _, page_url = CHANNELS[args.channel]

    print(f"Resolving: {page_url}", file=sys.stderr)

    try:
        stream_url, license_url = resolve(page_url, args.timeout)
    except requests.RequestException as exc:
        print(f"Request error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    kind = "HLS" if ".m3u8" in stream_url else "DASH"
    drm_note = f"  [DRM: {license_url}]" if license_url else ""
    print(f"Type:   {kind}{drm_note}", file=sys.stderr)
    print(stream_url)

    if args.open_vlc:
        try:
            subprocess.Popen(["vlc", stream_url])
        except FileNotFoundError:
            print("VLC not found in PATH.", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

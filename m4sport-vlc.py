#!/usr/bin/env python3
"""
Extract a playable live stream URL from mediaklikk.hu live pages.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from urllib.parse import urlparse

import requests


DEFAULT_PAGE_URL = "https://mediaklikk.hu/elo/mtv4live/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _extract_stream_id(page_html: str) -> str:
    match = re.search(r'"streamId"\s*:\s*"([^"]+)"', page_html)
    if not match:
        raise RuntimeError("Could not find streamId in the live page.")
    return match.group(1)


def _build_player_url(stream_id: str, page_url: str) -> str:
    params = {
        "video": stream_id,
        "autostart": "false",
        "embedded": "0",
        "mute": "false",
        "sourceUrl": page_url,
    }
    req = requests.Request(
        "GET", "https://player.mediaklikk.hu/playernew/player.php", params=params
    ).prepare()
    return req.url


def _extract_stream_url(player_html: str) -> str:
    # Usually embedded as JS object values, e.g. "file":"https:\/\/...\/index.m3u8?...".
    direct = re.search(r'"file"\s*:\s*"([^"]+\.(?:m3u8|mpd)[^"]*)"', player_html)
    if direct:
        return json.loads(f'"{direct.group(1)}"')

    # Fallback: generic URL search.
    fallback = re.search(r"https?://[^\"'\\s<>]+\\.(?:m3u8|mpd)[^\"'\\s<>]*", player_html)
    if fallback:
        return fallback.group(0)

    raise RuntimeError("Could not find a stream URL (.m3u8/.mpd) in player output.")


def extract_live_stream_url(page_url: str, timeout: float) -> str:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    page_resp = session.get(page_url, timeout=timeout)
    page_resp.raise_for_status()
    stream_id = _extract_stream_id(page_resp.text)

    player_url = _build_player_url(stream_id, page_url)
    player_resp = session.get(player_url, headers={"Referer": page_url}, timeout=timeout)
    player_resp.raise_for_status()

    return _extract_stream_url(player_resp.text)


def _normalize_page_url(page_url: str) -> str:
    parsed = urlparse(page_url)
    if not parsed.scheme:
        page_url = "https://" + page_url.lstrip("/")
    if not page_url.endswith("/"):
        page_url += "/"
    return page_url


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract a mediaklikk live stream URL that can be played in VLC."
    )
    parser.add_argument(
        "page_url",
        nargs="?",
        default=DEFAULT_PAGE_URL,
        help=f"Mediaklikk live page URL (default: {DEFAULT_PAGE_URL})",
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
        help="Launch VLC immediately with the extracted URL.",
    )
    args = parser.parse_args()

    try:
        page_url = _normalize_page_url(args.page_url)
        stream_url = extract_live_stream_url(page_url, args.timeout)
    except requests.RequestException as exc:
        print(f"Request error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(stream_url)

    if args.open_vlc:
        try:
            subprocess.Popen(["vlc", stream_url])
        except FileNotFoundError:
            print("VLC executable not found in PATH.", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

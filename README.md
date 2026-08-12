# Magyar TV Live — Kodi plugin

Kodi **video source plugin** for watching Hungarian public TV channels live from Mediaklikk, with automatic URL resolution.

Installed name in Kodi: **Magyar TV Live**

## Channels

| Channel | Stream page |
|---------|-------------|
| M4 Sport | `https://mediaklikk.hu/elo/mtv4live/` |
| M4 Sport direct | `https://m4sport.hu/elo` |
| M1 | `https://mediaklikk.hu/elo/mtv1live/` |
| M2 | `https://mediaklikk.hu/elo/mtv2live/` |
| Duna TV | `https://mediaklikk.hu/elo/dunalive/` |
| M5 | `https://mediaklikk.hu/elo/mtv5live/` |

Stream URLs are resolved dynamically at play time — no hardcoded permanent URLs.

## Installation

1. Create a ZIP archive with `plugin.video.m4sport/` as the top-level folder (must contain `addon.xml`).
2. In Kodi: **Settings → Add-ons → Install from zip file**.
3. Select the ZIP file.
4. Open the plugin at **Add-ons → Video add-ons → Magyar TV Live**.

## How it works

1. User selects a channel in Kodi.
2. Plugin fetches the live page for that channel (e.g. `https://mediaklikk.hu/elo/mtv1live/`).
3. It extracts `streamId` from the page HTML.
4. It calls the Mediaklikk player endpoint with the required `sourceUrl` + `Referer` headers.
5. It extracts the final `.m3u8` (HLS) or `.mpd` (DASH) URL from the player response.
6. It passes that URL to Kodi via `setResolvedUrl` and Kodi starts playback via `inputstream.adaptive`.

DRM-protected streams (Widevine) are handled by the bundled CDM installer.

## Key files

| File | Purpose |
|------|---------|
| `addon.py` | Plugin entry point, routing, channel list |
| `resources/lib/m4sport_core.py` | Stream extraction for M4 Sport channels |
| `resources/lib/mediaklikk_core.py` | Stream extraction for M1/M2/M5/Duna channels |
| `resources/lib/cdm_installer.py` | Widevine CDM installer (bundled, no external deps) |
| `resources/media/` | Per-channel logos (m1.png, m2.png, m5.png, duna.png, m4sport.png) |
| `resources/settings.xml` | Configurable channel URLs and names |
| `addon.xml` | Kodi addon metadata |

## Requirements

- Kodi 19 (Matrix) or later
- `inputstream.adaptive` (installed automatically if missing)
- LibreELEC or any Linux-based Kodi installation (Intel x86/x64 recommended)

## `mtv-live-vlc.py`

A standalone helper at the repository root that resolves any channel's live URL and prints or opens it in VLC:

```
python3 mtv-live-vlc.py --list
python3 mtv-live-vlc.py --channel m1
python3 mtv-live-vlc.py --channel duna --open-vlc
python3 mtv-live-vlc.py https://mediaklikk.hu/elo/mtv4live/
```

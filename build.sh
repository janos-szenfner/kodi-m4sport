#!/usr/bin/env bash
# Build an installable Kodi zip.
#
# Kodi requires exactly ONE top-level entry in the archive, named after the
# addon id.  Finder's "Compress" adds a second one (__MACOSX/) and Kodi then
# rejects the zip with an add-on structure error, so build it here instead.
set -euo pipefail

cd "$(dirname "$0")"

ADDON_DIR="plugin.video.m4sport"

# Read id/version from the <addon> element itself.  Do not grep for
# version="..." — the XML declaration on line 1 also matches it.
read -r ADDON_ID VERSION < <(python3 -c '
import xml.etree.ElementTree as ET
r = ET.parse("'"$ADDON_DIR"'/addon.xml").getroot()
print(r.get("id"), r.get("version"))
')

if [ "$ADDON_ID" != "$ADDON_DIR" ]; then
    echo "ERROR: addon.xml id '$ADDON_ID' must match folder name '$ADDON_DIR'." >&2
    echo "Kodi rejects the zip when they differ." >&2
    exit 1
fi

OUT="dist/${ADDON_DIR}-${VERSION}.zip"

find . -name '.DS_Store' -not -path './.git/*' -delete
rm -rf dist && mkdir -p dist

zip -r -X "$OUT" "$ADDON_DIR" \
    -x '*.DS_Store' -x '__MACOSX/*' -x '*/__pycache__/*' -x '*.pyc' > /dev/null

# Fail loudly rather than shipping a zip Kodi will reject.
roots=$(unzip -Z1 "$OUT" | cut -d/ -f1 | sort -u)
if [ "$roots" != "$ADDON_DIR" ]; then
    echo "ERROR: archive root must be exactly '$ADDON_DIR', got:" >&2
    echo "$roots" >&2
    exit 1
fi

echo "Built $OUT"
unzip -Z1 "$OUT"

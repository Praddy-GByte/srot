#!/usr/bin/env bash
#
# Build the installable plugin zip.
#
# plugins.qgis.org requires exactly one top-level folder inside the archive,
# named after the plugin package, containing metadata.txt and __init__.py. It
# also rejects compiled artefacts, so those are excluded rather than cleaned up
# afterwards.
#
#   bash scripts/package.sh
#   -> dist/srot.zip

set -euo pipefail

PACKAGE="srot"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f "$PACKAGE/metadata.txt" ]; then
  echo "error: $PACKAGE/metadata.txt not found - run this from the repository." >&2
  exit 1
fi

VERSION="$(sed -n 's/^version=//p' "$PACKAGE/metadata.txt" | head -1)"
echo "Packaging $PACKAGE $VERSION"

find "$PACKAGE" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$PACKAGE" -name "*.pyc" -delete 2>/dev/null || true

# plugins.qgis.org wants the README and LICENSE inside the package, while a
# GitHub repo wants them at the root. Keep one copy at the root and stage it
# into the package at build time, so the two can never drift apart.
cp README.md "$PACKAGE/README.md"
cp LICENSE "$PACKAGE/LICENSE"
trap 'rm -f "$PACKAGE/README.md" "$PACKAGE/LICENSE"' EXIT

mkdir -p dist
rm -f "dist/$PACKAGE.zip"

zip -rq "dist/$PACKAGE.zip" "$PACKAGE" \
  -x "$PACKAGE/tests/*" \
  -x "*.pyc" \
  -x "*__pycache__*" \
  -x "*.DS_Store" \
  -x "*/.git/*"

SIZE="$(du -h "dist/$PACKAGE.zip" | cut -f1)"
COUNT="$(unzip -l "dist/$PACKAGE.zip" | tail -1 | awk '{print $2}')"
echo "Built dist/$PACKAGE.zip  ($SIZE, $COUNT files)"
echo
echo "Install locally with: Plugins -> Manage and Install Plugins -> Install from ZIP"

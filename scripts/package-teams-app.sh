#!/usr/bin/env bash
# Package the Teams app manifest into a .zip for sideloading.
# Substitutes ${{MSTEAMS_APP_ID}} from .env before zipping.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_DIR/teams-app"
OUT_DIR="$PROJECT_DIR/dist"

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a; source "$PROJECT_DIR/.env"; set +a
fi

if [ -z "${MSTEAMS_APP_ID:-}" ]; then
  echo "ERROR: MSTEAMS_APP_ID not set. Fill in .env first."
  exit 1
fi

# Check icons
if [ ! -f "$APP_DIR/outline.png" ] || [ ! -f "$APP_DIR/color.png" ]; then
  echo "Creating placeholder icon PNGs..."
  if command -v magick &>/dev/null; then
    magick -size 32x32 xc:'#5B6DEF' "$APP_DIR/outline.png"
    magick -size 192x192 xc:'#5B6DEF' "$APP_DIR/color.png"
  elif command -v convert &>/dev/null; then
    convert -size 32x32 xc:'#5B6DEF' "$APP_DIR/outline.png"
    convert -size 192x192 xc:'#5B6DEF' "$APP_DIR/color.png"
  else
    echo "ERROR: No ImageMagick found. Place outline.png (32x32) and color.png (192x192) in teams-app/"
    exit 1
  fi
fi

mkdir -p "$OUT_DIR"

# Substitute placeholders
sed "s/\\\${{MSTEAMS_APP_ID}}/$MSTEAMS_APP_ID/g" "$APP_DIR/manifest.json" > "$OUT_DIR/manifest.json"
cp "$APP_DIR/outline.png" "$APP_DIR/color.png" "$OUT_DIR/"

cd "$OUT_DIR"
zip -j "$PROJECT_DIR/reagent-teams-app.zip" manifest.json outline.png color.png
rm -rf "$OUT_DIR"

echo ""
echo "Packaged: reagent-teams-app.zip"
echo "Sideload via: Teams > Apps > Manage your apps > Upload a custom app"

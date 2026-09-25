#!/usr/bin/env bash
# Assemble the GitHub Pages site into _site/ (landing page + demo player with a CC BY song).
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf _site
cp -R site _site
cp web/player.html _site/demo/index.html
echo "built _site/ — preview with: python3 -m http.server -d _site 8000"

#!/usr/bin/env bash
# Copy the code to the Sprite. Run from the repo root after `sprite use uncle-vern`.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests 2>/dev/null
pkg="$(mktemp -t uncle-vern).tgz"
COPYFILE_DISABLE=1 tar --no-xattrs --exclude data --exclude __pycache__ --exclude '*.pyc' -czf "$pkg" uncle run.sh
# -p: without it, `sprite file push` (2026-11-03) says an existing folder "does not exist"
# when that folder was made inside the Sprite.
sprite file push -p "$pkg" /home/sprite/deploy/uncle-vern.tgz
rm -f "$pkg"
sprite exec --no-stdin -- bash -c 'mkdir -p ~/app ~/uncle-data && tar xzf ~/deploy/uncle-vern.tgz -C ~/app && chmod +x ~/app/run.sh && ls ~/app'
echo "Pushed. First time only: create ~/app/uncle.env and register the service (see deploy/README.md)."

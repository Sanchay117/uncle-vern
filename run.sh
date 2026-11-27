#!/usr/bin/env bash
# Starts Uncle on the Sprite. Registered once as a Sprite service, so it comes back on every wake.
cd "$(dirname "$0")"
set -a
[ -f ./uncle.env ] && . ./uncle.env
set +a
exec python3 -m uncle.server

#!/bin/sh
set -eu
. "$(dirname -- "$0")/common.sh"
sleep "$1"
[ "$(cat "$STATE/status")" = ACTIVE ] || exit 0
sh "$BASE/rollback.sh" --confirm "$TOKEN"

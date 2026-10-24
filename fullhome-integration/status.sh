#!/bin/sh
set -eu
. "$(dirname -- "$0")/common.sh"
log "SESSION $TOKEN"
sha256sum "$TARGET_1" "$TARGET_2"
awk '$5 ~ /com.webos.app.fullhome/ {print}' "$MOUNTINFO"
if [ -d "$STATE" ]; then
    printf 'status='; cat "$STATE/status"
    context_check
fi
if [ -f /var/log/fullhome ]; then
    grep -F "$TOKEN" /var/log/fullhome | tail -n 100
fi

#!/bin/sh
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
LOCK=/tmp/wiios-wake-monitor-lock
mkdir "$LOCK" 2>/dev/null || exit 0
trap 'rmdir "$LOCK"' EXIT
trap 'exit 0' HUP INT TERM
BOOT=$(cat /proc/sys/kernel/random/boot_id)
previous=unknown
while [ "$(cat /proc/sys/kernel/random/boot_id)" = "$BOOT" ]; do
    state=unknown
    if response=$(luna-send -n 1 -w 3000 -f luna://com.webos.service.tvpower/power/getPowerState '{}' 2>/dev/null); then
        if printf '%s\n' "$response" | grep -Eq '"state"[[:space:]]*:[[:space:]]*"Active"'; then
            state=active
        elif printf '%s\n' "$response" | grep -Eq '"state"[[:space:]]*:[[:space:]]*"(Suspend|Off|ActiveStandby)"'; then
            state=inactive
        fi
    fi
    if [ "$previous" = inactive ] && [ "$state" = active ]; then
        sh "$BASE/launch-on-boot.sh" >> "$BASE/wake-monitor.log" 2>&1 || :
    fi
    [ "$state" = unknown ] || previous=$state
    sleep 10
done

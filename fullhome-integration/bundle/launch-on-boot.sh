#!/bin/sh
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
BOOT=$(cat /proc/sys/kernel/random/boot_id)
attempt=0
seen=false
ready=false
while [ "$attempt" -lt 20 ]; do
    [ "$(cat /proc/sys/kernel/random/boot_id)" = "$BOOT" ] || exit 0
    if response=$(luna-send -n 1 -w 3000 -f luna://com.webos.bootManager/getBootStatus '{}' 2>/dev/null); then
        if printf '%s\n' "$response" | grep -Eq '"boot-done"[[:space:]]*:[[:space:]]*true'; then
            ready=true
            break
        fi
        if printf '%s\n' "$response" | grep -Eq '"boot-done"[[:space:]]*:[[:space:]]*false'; then
            seen=true
        fi
    fi
    attempt=$((attempt+1))
    sleep 2
done
if [ "$ready" = false ] && [ "$seen" = true ]; then
    echo 'Boot status explicitly incomplete' >&2
    exit 1
fi
if [ "$ready" = false ]; then
    echo 'Boot status API unavailable; attempting launcher after fallback delay'
fi
if power=$(luna-send -n 1 -w 3000 -f luna://com.webos.service.tvpower/power/getPowerState '{}' 2>/dev/null); then
    if printf '%s\n' "$power" | grep -Eq '"state"[[:space:]]*:[[:space:]]*"(Suspend|Off|ActiveStandby)"'; then
        echo 'TV not active; launch deferred to wake monitor'
        exit 0
    fi
fi
attempt=0
while [ "$attempt" -lt 3 ]; do
    attempt=$((attempt+1))
    response=$(luna-send -n 1 -w 3000 -f luna://com.webos.applicationManager/launch '{"id":"com.wiios.launcher"}' 2>/dev/null || :)
    printf '%s\n' "$response"
    if printf '%s\n' "$response" | grep -Eq '"returnValue"[[:space:]]*:[[:space:]]*true'; then
        checks=0
        while [ "$checks" -lt 4 ]; do
            sleep 2
            checks=$((checks+1))
            foreground=$(luna-send -n 1 -w 3000 -f luna://com.webos.applicationManager/getForegroundAppInfo '{}' 2>/dev/null || :)
            if printf '%s\n' "$foreground" | grep -Eq '"appId"[[:space:]]*:[[:space:]]*"com.wiios.launcher"'; then
                echo 'WIIOS_FOREGROUND_CONFIRMED'
                exit 0
            fi
        done
    fi
    sleep 3
done
echo 'WiiOS launch not confirmed' >&2
exit 1

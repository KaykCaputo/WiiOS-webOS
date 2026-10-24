#!/bin/sh
set -eu
. "$(dirname -- "$0")/common.sh"
[ ! -e /var/luna/preferences/webosbrew_failsafe ] || exit 0
cd "$BASE"
sha256sum -c persistent.sha256 || fail 'Home payload checksum mismatch'
BOOT=$(cat /proc/sys/kernel/random/boot_id)
BOOT_LOCK=/tmp/wiios-fullhome-boot-lock
mkdir "$BOOT_LOCK" || fail 'Home startup already running'
trap 'rmdir "$BOOT_LOCK"' EXIT
trap 'exit 130' HUP INT TERM
ACTIVE=false
if [ -d "$STATE" ]; then
    OLD_BOOT=$(cat "$STATE/boot-id" 2>/dev/null || :)
    if [ "$OLD_BOOT" = "$BOOT" ]; then
        STATUS=$(cat "$STATE/status")
        if [ "$STATUS" = ACTIVE ]; then
            context_check
            for number in 1 2 3 4; do verify_owned "$number"; done
            ACTIVE=true
        elif [ "$STATUS" = RESTORED ]; then
            [ -z "$(rows "$TARGET_1")" ] && [ -z "$(rows "$TARGET_2")" ] || fail 'QML mounted after rollback'
            [ -z "$(grep -F "$BASE/" "$MOUNTINFO" || :)" ] || fail 'Owned mount remains after rollback'
            [ "$(hash "$TARGET_1")" = "$ORIGINAL_1" ] || fail 'Original main.qml mismatch'
            [ "$(hash "$TARGET_2")" = "$ORIGINAL_2" ] || fail 'Original UIController.qml mismatch'
            mv "$STATE" "$BASE/state-restored-$(date +%s)"
        else
            fail 'Current session is incomplete; inspect before restarting'
        fi
    else
        [ -z "$(rows "$TARGET_1")" ] && [ -z "$(rows "$TARGET_2")" ] || fail 'Unexpected QML mount after reboot'
        [ -z "$(grep -F "$BASE/" "$MOUNTINFO" || :)" ] || fail 'Unexpected owned mount after reboot'
        mv "$STATE" "$BASE/state-previous-$(date +%s)"
    fi
fi
if [ "$ACTIVE" = false ]; then
    tries=0
    while [ "$tries" -lt 40 ]; do
        if [ -d /tmp/checkpoint/com.webos.app.fullhome ] && [ -d /mnt/lg/cmn_data/checkpoint/com.webos.app.fullhome ] && [ -f "$TARGET_1" ] && [ -f "$TARGET_2" ]; then
            break
        fi
        tries=$((tries+1))
        sleep 2
    done
    [ "$tries" -lt 40 ] || fail 'Full Home paths unavailable after boot'
    for directory in "$BASE/mask-tmp" "$BASE/mask-persistent"; do
        [ ! -d "$directory" ] || [ -z "$(ls -A "$directory")" ] || fail "Checkpoint mask not empty: $directory"
    done
    sh "$BASE/activate.sh" --activate 600
    for number in 1 2 3 4; do verify_owned "$number"; done
    for pid in $(pidof com.webos.app.fullhome 2>/dev/null || :); do
        case "$pid" in ''|*[!0-9]*) continue;; esac
        if [ "$(readlink "/proc/$pid/exe" 2>/dev/null || :)" = /usr/bin/com.webos.app.fullhome ]; then
            kill -TERM "$pid" || :
            log "Reload requested for Full Home PID $pid"
        fi
    done
fi
nohup sh "$BASE/launch-on-boot.sh" > "$BASE/launch-on-boot.log" 2>&1 < /dev/null &
nohup sh "$BASE/wake-monitor.sh" > "$BASE/wake-monitor.log" 2>&1 < /dev/null &
log "WiiOS Home ready on boot $BOOT"

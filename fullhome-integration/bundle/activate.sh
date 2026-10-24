#!/bin/sh
set -eu
. "$(dirname -- "$0")/common.sh"
[ "${1:-}" = '--activate' ] || fail 'Usage: activate.sh --activate [seconds: 60..600]'
TTL=${2:-180}
case "$TTL" in ''|*[!0-9]*) fail 'Invalid timeout';; esac
[ "$TTL" -ge 60 ] && [ "$TTL" -le 600 ] || fail 'Timeout must be 60..600 seconds'
[ "$(id -u)" = 0 ] || fail 'Root required'
[ ! -e "$STATE" ] || fail 'Session already used; prepare a new token'
for cmd in awk sort cmp sha256sum stat readlink mount umount nohup; do command -v "$cmd" >/dev/null || fail "Missing $cmd"; done
lock
[ "$(hash "$TARGET_1")" = "$ORIGINAL_1" ] || fail 'main.qml is not the verified original'
[ "$(hash "$TARGET_2")" = "$ORIGINAL_2" ] || fail 'UIController.qml is not the verified original'
[ "$(hash "$BASE/$FILE_1")" = "$PATCHED_1" ] || fail 'Patched main.qml hash mismatch'
[ "$(hash "$BASE/$FILE_2")" = "$PATCHED_2" ] || fail 'Patched controller hash mismatch'
[ -z "$(rows "$TARGET_1")" ] && [ -z "$(rows "$TARGET_2")" ] || fail 'Pre-existing QML mount; do not stack on another patch'
for target in /tmp/checkpoint/com.webos.app.fullhome /mnt/lg/cmn_data/checkpoint/com.webos.app.fullhome; do
    [ -d "$target" ] || fail "Checkpoint directory absent: $target"
    [ -z "$(children "$target")" ] || fail "Nested checkpoint mount: $target"
done
umask 077
mkdir "$STATE"
mkdir -p "$BASE/mask-tmp" "$BASE/mask-persistent"
cat /proc/sys/kernel/random/boot_id > "$STATE/boot-id"
readlink /proc/self/ns/mnt > "$STATE/namespace"
printf '%s\n' ACTIVE > "$STATE/status"
:
bind_owned 1 "$BASE/$FILE_1" "$TARGET_1"
bind_owned 2 "$BASE/$FILE_2" "$TARGET_2"
bind_owned 3 "$BASE/mask-tmp" /tmp/checkpoint/com.webos.app.fullhome
bind_owned 4 "$BASE/mask-persistent" /mnt/lg/cmn_data/checkpoint/com.webos.app.fullhome
log "ACTIVE $TOKEN; permanent mode; no expiry timer."
log "Capture /var/log/fullhome and applicationManager/running; use physical Home to start a fresh process."

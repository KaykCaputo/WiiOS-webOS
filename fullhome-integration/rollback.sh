#!/bin/sh
set -eu
. "$(dirname -- "$0")/common.sh"
[ "${1:-}" = '--confirm' ] && [ "${2:-}" = "$TOKEN" ] || fail "Usage: rollback.sh --confirm $TOKEN"
[ -d "$STATE" ] || fail 'No session state; ownership cannot be proved'
context_check
lock
for number in 4 3 2 1; do
    [ -f "$STATE/$number.intent" ] || continue
    target=$(cat "$STATE/$number.target")
    if [ -n "$(owned_row "$number")" ]; then
        verify_owned "$number"
    else
        rows "$target" > "$STATE/$number.current"
        cmp -s "$STATE/$number.current" "$STATE/$number.before" || fail "Unrecognized mount state: $target"
    fi
done
for number in 4 3 2 1; do
    [ -f "$STATE/$number.intent" ] || continue
    target=$(cat "$STATE/$number.target")
    if [ -n "$(owned_row "$number")" ]; then
        verify_owned "$number"
        umount -n "$target" || fail "Unmount failed/busy: $target. No force/lazy/retry-on-stack was used."
        log "UNMOUNTED owned bind $number at $target"
    fi
    rows "$target" > "$STATE/$number.current"
    cmp -s "$STATE/$number.current" "$STATE/$number.before" || fail "Baseline mount records did not return: $target"
    log "BASELINE VERIFIED $target"
done
[ "$(hash "$TARGET_1")" = "$ORIGINAL_1" ] || fail 'Original main.qml hash did not return'
[ "$(hash "$TARGET_2")" = "$ORIGINAL_2" ] || fail 'Original controller hash did not return'
printf '%s\n' RESTORED > "$STATE/status"
log "RESTORED $TOKEN: original QML hashes and baseline mount records verified."
log 'A process already in memory may retain diagnostic QML until it exits normally.'

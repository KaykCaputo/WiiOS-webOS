#!/bin/sh
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
. "$BASE/config.sh"
[ "$BASE" = "$EXPECTED_BASE" ] || { echo 'Unexpected session directory' >&2; exit 1; }
STATE=$BASE/state
LOCK=/var/lib/webosbrew/wiios-fullhome-diag/operation-lock
MOUNTINFO=/proc/self/mountinfo
fail() { printf 'REFUSED: %s\n' "$*" >&2; exit 1; }
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
rows() { awk -v target="$1" '$5 == target' "$MOUNTINFO" | sort -n; }
children() { awk -v target="$1/" 'index($5,target) == 1' "$MOUNTINFO"; }
identity() { stat -c '%d:%i' "$1"; }
hash() { sha256sum "$1" | awk '{print $1}'; }
lock() {
    mkdir "$LOCK" || fail 'Another mount operation is active. No lock is removed automatically.'
    printf '%s\n' "$TOKEN" > "$LOCK/owner"
    trap 'unlock' EXIT
    trap 'exit 130' HUP INT TERM
}
unlock() {
    if [ -f "$LOCK/owner" ] && [ "$(cat "$LOCK/owner")" = "$TOKEN" ]; then
        rm "$LOCK/owner"
        rmdir "$LOCK"
    fi
}
context_check() {
    [ "$(cat /proc/sys/kernel/random/boot_id)" = "$(cat "$STATE/boot-id")" ] || fail 'TV boot changed; do not reuse mount IDs across boots.'
    [ "$(readlink /proc/self/ns/mnt)" = "$(cat "$STATE/namespace")" ] || fail 'Mount namespace changed.'
}
source_coordinates() {
    awk -v path="$1" '
    { m=$5; if (path==m || m=="/" || index(path,m "/")==1) {
        if (length(m)>best) {best=length(m); dev=$3; root=$4; point=m}
    }}
    END {
        if (!best) exit 1;
        suffix=(point=="/" ? path : substr(path,length(point)+1));
        if (root=="/") root="";
        print dev " " root suffix;
    }' "$MOUNTINFO"
}
owned_row() {
    number=$1
    target=$(cat "$STATE/$number.target")
    device=$(awk '{print $1}' "$STATE/$number.coordinates")
    root=$(awk '{print $2}' "$STATE/$number.coordinates")
    awk -v t="$target" -v d="$device" -v r="$root" '$5==t && $3==d && $4==r' "$MOUNTINFO"
}
verify_owned() {
    number=$1
    target=$(cat "$STATE/$number.target")
    source=$(cat "$STATE/$number.source")
    row=$(owned_row "$number")
    [ -n "$row" ] && [ "$(printf '%s\n' "$row" | wc -l)" -eq 1 ] || fail "No unique owned mount at $target"
    if [ -f "$STATE/$number.owned" ]; then
        printf '%s\n' "$row" | awk '{$6="OPTIONS"; print}' > "$STATE/$number.current-id"
        awk '{$6="OPTIONS"; print}' "$STATE/$number.owned" > "$STATE/$number.recorded-id"
        cmp -s "$STATE/$number.current-id" "$STATE/$number.recorded-id" || fail "Mount identity changed: $target"
    fi
    rows "$target" > "$STATE/$number.current"
    { cat "$STATE/$number.before"; printf '%s\n' "$row"; } | sort -n > "$STATE/$number.expected"
    cmp -s "$STATE/$number.current" "$STATE/$number.expected" || fail "Foreign/stacked mount at $target"
    [ -z "$(children "$target")" ] || fail "Nested mount at $target"
    [ "$(identity "$target")" = "$(cat "$STATE/$number.inode")" ] || fail "Target inode changed: $target"
    [ "$(identity "$source")" = "$(cat "$STATE/$number.inode")" ] || fail "Source inode changed: $source"
}
record_intent() {
    number=$1; source=$2; target=$3
    [ -z "$(children "$target")" ] || fail "Nested mounts at $target"
    [ "$(readlink -f "$target")" = "$target" ] || fail "Symlink target: $target"
    printf '%s\n' "$target" > "$STATE/$number.target"
    printf '%s\n' "$source" > "$STATE/$number.source"
    identity "$source" > "$STATE/$number.inode"
    source_coordinates "$source" > "$STATE/$number.coordinates"
    rows "$target" > "$STATE/$number.before"
    printf '%s\n' ready > "$STATE/$number.intent"
}
bind_owned() {
    number=$1; source=$2; target=$3
    record_intent "$number" "$source" "$target"
    mount -n --bind "$source" "$target" || fail "Bind failed: $target (run rollback)"
    row=$(owned_row "$number")
    [ -n "$row" ] || fail "Could not identify new bind: $target (run rollback)"
    printf '%s\n' "$row" > "$STATE/$number.owned"
    verify_owned "$number"
    mount -n -o remount,bind,ro "$source" "$target" || fail "Read-only remount failed: $target (run rollback)"
    verify_owned "$number"
    owned_row "$number" > "$STATE/$number.owned"
    options=$(owned_row "$number" | awk '{print $6}')
    case ",$options," in *,ro,*) ;; *) fail "Bind is not read-only: $target";; esac
    log "MOUNTED $number $(cat "$STATE/$number.owned")"
}

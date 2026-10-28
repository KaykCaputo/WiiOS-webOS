#!/bin/sh
set -eu
umask 077
action=$1
base=$2
source=$3
target=$4
case "$base" in /var/lib/wiios/home-transactions/*) ;; *) exit 8 ;; esac
case "$base" in *..*|*[!a-zA-Z0-9/_-]*) exit 8 ;; esac
case "$source" in "$base/bundle"|"$base/standin.sh"|"$base/recovery-self-test/source") ;; *) exit 8 ;; esac
case "$target" in /usr/palm/applications/com.webos.app.home|/usr/palm/applications/com.webos.app.home/*|"$base/recovery-self-test/target") ;; *) exit 8 ;; esac
case "$target" in *..*|*[!a-zA-Z0-9/_.-]*) exit 8 ;; esac
boot=$(cat /proc/sys/kernel/random/boot_id)
namespace=$(readlink /proc/self/ns/mnt)
case "$boot" in ''|*[!a-f0-9-]*) exit 8 ;; esac
ledger="$base/mount-$boot"
if [ "$target" = "$base/recovery-self-test/target" ]; then ledger="$base/self-test-$boot"; fi
related() {
    awk -v t="$target" '$5 == t || index($5,t "/") == 1 {print}' /proc/self/mountinfo
}
covering() {
    awk -v t="$1" '($5 == "/" || t == $5 || index(t,$5 "/") == 1) && length($5)>n {n=length($5); row=$0} END {if (!n) exit 1; print row}' /proc/self/mountinfo
}
coordinate() {
    awk -v t="$source" '($5 == "/" || t == $5 || index(t,$5 "/") == 1) && length($5)>n {n=length($5); dev=$3; root=$4; at=$5} END {if (!n) exit 1; suffix=substr(t,length(at)+1); if(at=="/") suffix="/" suffix; if(root=="/") root=""; path=root suffix; if(path=="") path="/"; print dev " " path}' /proc/self/mountinfo
}
check_context() {
    [ "$(cat "$ledger/boot")" = "$boot" ] || return 7
    [ "$(cat "$ledger/namespace")" = "$namespace" ] || return 7
    [ "$(cat "$ledger/source")" = "$source" ] || return 7
    [ "$(cat "$ledger/target")" = "$target" ] || return 7
    [ "$(stat -Lc '%d:%i' "$source")" = "$(cat "$ledger/inode")" ] || return 7
}
check_owned() {
    check_context || return 7
    current=$(related)
    [ "$(printf '%s\n' "$current" | awk 'NF {n++} END {print n+0}')" = 1 ] || return 7
    [ "$(printf '%s\n' "$current" | awk '{print $5}')" = "$target" ] || return 7
    [ "$(printf '%s\n' "$current" | awk '{print $3 " " $4}')" = "$(cat "$ledger/coordinate")" ] || return 7
    [ "$(stat -Lc '%d:%i' "$target")" = "$(cat "$ledger/inode")" ] || return 7
    mount_id=$(printf '%s\n' "$current" | awk '{print $1}')
    ! grep -qx "$mount_id" "$ledger/before-ids" || return 7
    predecessor=$(cat "$ledger/predecessor")
    grep -Fx "$predecessor" /proc/self/mountinfo >/dev/null || return 7
    if [ -f "$ledger/mounted" ]; then [ "$current" = "$(cat "$ledger/mounted")" ] || return 7; fi
}
case "$action" in
    bind|restore|check) ;;
    *) exit 2 ;;
esac
[ -d "$base" ] || exit 8
[ ! -L "$base" ] || exit 8
lock="$base/mount-operation.lock"
[ ! -L "$lock" ] || exit 7
if [ -e "$lock" ]; then [ -f "$lock" ] || exit 7; fi
command -v flock >/dev/null || exit 6
exec 9>>"$lock"
flock -w 10 9 || exit 6
[ "$(stat -Lc '%d:%i' "$lock")" = "$(stat -Lc '%d:%i' /proc/self/fd/9)" ] || exit 7
trap 'exit 6' HUP INT TERM
if [ "$action" = restore ]; then
    if [ "$target" != "$base/recovery-self-test/target" ]; then
        touch "$base/boot-disabled" "$base/trial-expired"
        sync
    fi
    if [ -z "$(related)" ]; then exit 0; fi
    check_owned || exit 7
    printf '%s\n' RESTORE_INTENT > "$ledger/status"
    sync
    umount "$target"
    [ -z "$(related)" ] || exit 6
    [ "$(covering "$target")" = "$(cat "$ledger/predecessor")" ] || exit 7
    printf '%s\n' FILES_RESTORED > "$ledger/status"
    sync
    exit 0
fi
if [ "$action" = check ]; then check_owned || exit 7; exit 0; fi
[ ! -e "$base/trial-expired" ] || exit 8
[ ! -e "$base/boot-disabled" ] || exit 8
[ -z "$(related)" ] || exit 7
[ ! -L "$source" ] || exit 8
[ ! -L "$target" ] || exit 8
mkdir "$ledger"
printf '%s\n' "$boot" > "$ledger/boot"
printf '%s\n' "$namespace" > "$ledger/namespace"
printf '%s\n' "$source" > "$ledger/source"
printf '%s\n' "$target" > "$ledger/target"
stat -Lc '%d:%i' "$source" > "$ledger/inode"
coordinate > "$ledger/coordinate"
covering "$target" > "$ledger/predecessor"
awk '{print $1}' /proc/self/mountinfo > "$ledger/before-ids"
printf '%s\n' BIND_INTENT > "$ledger/status"
sync
mount --bind "$source" "$target"
check_owned || exit 7
related > "$ledger/mounted.pending"
mv "$ledger/mounted.pending" "$ledger/mounted"
printf '%s\n' MOUNTED > "$ledger/status"
sync

#!/bin/sh
set -eu
BASE=/var/lib/webosbrew/wiios-metrics
STATE=$BASE/process
LOCK=$BASE/operation-lock
fail() { printf '%s\n' "$*" >&2; exit 1; }
owned() {
    [ -f "$STATE" ] || return 1
    read -r saved_pid saved_boot saved_start < "$STATE"
    case "$saved_pid" in ''|*[!0-9]*) return 1;; esac
    [ "$(cat /proc/sys/kernel/random/boot_id)" = "$saved_boot" ] || return 1
    [ -f "/proc/$saved_pid/stat" ] || return 1
    [ "$(awk '{print $22}' "/proc/$saved_pid/stat")" = "$saved_start" ] || return 1
    tr '\000' '\n' < "/proc/$saved_pid/cmdline" | grep -Fx "$BASE/metrics.js" > /dev/null
}
case "${1:-}" in start|stop|status) ;; *) fail 'Usage: control.sh start|stop|status';; esac
if [ "$1" = status ]; then
    if owned; then printf 'RUNNING %s\n' "$saved_pid"; else printf 'STOPPED\n'; exit 1; fi
    exit 0
fi
mkdir "$LOCK" || fail 'Another metrics operation is active'
trap 'rmdir "$LOCK"' EXIT
trap 'exit 130' HUP INT TERM
if [ "$1" = stop ]; then
    if owned; then
        kill -TERM "$saved_pid"
        printf 'Stop requested for metrics PID %s\n' "$saved_pid"
    else
        printf 'No owned metrics process to stop\n'
    fi
    exit 0
fi
if owned; then printf 'Already running: %s\n' "$saved_pid"; exit 0; fi
[ -f "$BASE/metrics.js" ] || fail 'Missing metrics.js'
nohup /usr/bin/node "$BASE/metrics.js" > "$BASE/metrics.log" 2>&1 < /dev/null &
new_pid=$!
new_boot=$(cat /proc/sys/kernel/random/boot_id)
[ -f "/proc/$new_pid/stat" ] || fail 'Collector exited before startup'
new_start=$(awk '{print $22}' "/proc/$new_pid/stat")
printf '%s %s %s\n' "$new_pid" "$new_boot" "$new_start" > "$STATE"
printf 'Started metrics PID %s\n' "$new_pid"

#!/bin/sh
set -eu
BASE=/var/lib/webosbrew/wiios-privacy
TARGET=/etc/hosts
SOURCE=$BASE/hosts
[ "$(id -u)" = 0 ] || exit 1
[ ! -e /var/luna/preferences/webosbrew_failsafe ] || exit 0
[ -f "$TARGET" ] && [ ! -L "$TARGET" ] || { echo 'Unexpected /etc/hosts path' >&2; exit 1; }
[ -f "$BASE/hosts.txt" ] || { echo 'Missing domain list' >&2; exit 1; }
owned=$(awk -v s="$SOURCE" '$5=="/etc/hosts" && $4==s {print}' /proc/self/mountinfo)
[ -z "$owned" ] || { echo 'Privacy bind already active'; exit 0; }
foreign=$(awk '$5=="/etc/hosts" {print}' /proc/self/mountinfo)
if [ -n "$foreign" ]; then
    rows=$(awk '$5=="/etc/hosts" {count++} END {print count+0}' /proc/self/mountinfo)
    [ "$rows" = 1 ] || { echo 'Stacked hosts mounts; refusing changes' >&2; exit 1; }
    known=$(awk '$5=="/etc/hosts" && $4=="/hosts" && $8=="tmpfs" && $6 ~ /^rw,/ {print "KNOWN"}' /proc/self/mountinfo)
    [ "$known" = KNOWN ] && [ -w "$TARGET" ] || { echo 'Unknown hosts mount; refusing changes' >&2; exit 1; }
    while IFS= read -r domain || [ -n "$domain" ]; do
        [ -n "$domain" ] || continue
        case "$domain" in *[!a-zA-Z0-9.-]*|.*|*.) echo 'Invalid domain list' >&2; exit 1;; esac
    done < "$BASE/hosts.txt"
    while IFS= read -r domain || [ -n "$domain" ]; do
        [ -n "$domain" ] || continue
        grep -Fqx "0.0.0.0 $domain" "$TARGET" || printf '0.0.0.0 %s\n' "$domain" >> "$TARGET"
        grep -Fqx "::1 $domain" "$TARGET" || printf '::1 %s\n' "$domain" >> "$TARGET"
    done < "$BASE/hosts.txt"
    echo 'LG ad/telemetry hosts entries applied to existing tmpfs'
    exit 0
fi
TEMP=$BASE/hosts.pending
cp "$TARGET" "$TEMP"
printf '\n' >> "$TEMP"
while IFS= read -r domain || [ -n "$domain" ]; do
    [ -n "$domain" ] || continue
    case "$domain" in *[!a-zA-Z0-9.-]*|.*|*.) echo 'Invalid domain list' >&2; exit 1;; esac
    printf '0.0.0.0 %s\n::1 %s\n' "$domain" "$domain" >> "$TEMP"
done < "$BASE/hosts.txt"
chmod 644 "$TEMP"
mv "$TEMP" "$SOURCE"
mount -n --bind "$SOURCE" "$TARGET"
owned=$(awk -v s="$SOURCE" '$5=="/etc/hosts" && $4==s {print}' /proc/self/mountinfo)
[ -n "$owned" ] || { echo 'Hosts bind could not be verified' >&2; exit 1; }
mount -n -o remount,bind,ro "$SOURCE" "$TARGET"
owned=$(awk -v s="$SOURCE" '$5=="/etc/hosts" && $4==s {print}' /proc/self/mountinfo)
[ -n "$owned" ] || { echo 'Readonly hosts bind could not be verified' >&2; exit 1; }
echo 'LG ad/telemetry hosts block active'

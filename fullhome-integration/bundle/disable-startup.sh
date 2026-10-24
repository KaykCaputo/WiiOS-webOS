#!/bin/sh
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
HOOK=/var/lib/webosbrew/init.d/99-wiios-fullhome
[ -e "$HOOK" ] || { echo 'WiiOS Home hook already disabled'; exit 0; }
cmp -s "$HOOK" "$BASE/99-wiios-fullhome" || { echo 'Unrecognized Home hook' >&2; exit 1; }
rm "$HOOK"
echo 'WiiOS Home startup disabled; restart the TV to restore stock QML'

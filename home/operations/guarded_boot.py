import hashlib
import json
from importlib import resources
import re
import shlex

from installer.errors import InstallerError


BOOT_DIRECTORY = '/var/lib/webosbrew/init.d'
BOOT_PREFIX = '98-wiios-guarded-'


def build_boot_hook(transaction_id, target, source, original_sha256, staged_sha256, app_id, native=False, file_hashes=None, profile=None, sam_protocol=None):
    if (not re.fullmatch(r'[a-f0-9]{64}', transaction_id) or
            not re.fullmatch(r'[a-f0-9]{64}', original_sha256) or
            not re.fullmatch(r'[a-f0-9]{64}', staged_sha256) or
            not re.fullmatch(r'com\.webos\.app\.(?:home|fullhome)', app_id) or
            not (target == '/usr/palm/applications/' + app_id or
                 target.startswith('/usr/palm/applications/' + app_id + '/')) or
            not source.startswith('/var/lib/wiios/home-transactions/' + transaction_id + '/')):
        raise InstallerError('BOOT_PROFILE_INVALID', 'Boot persistence requires an exact approved Home transaction.', 8)
    if not isinstance(file_hashes, dict) or not file_hashes or len(file_hashes) > 512:
        raise InstallerError('BOOT_PAYLOAD_UNVERIFIED', 'Boot persistence requires a complete payload hash ledger.', 8)
    checks = []
    for name, expected in sorted(file_hashes.items()):
        if (not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name) or
                name.startswith('.') or not re.fullmatch(r'[a-f0-9]{64}', expected)):
            raise InstallerError('BOOT_PAYLOAD_INVALID', 'The boot payload includes an untrusted path or hash.', 8)
        checks.append((name, expected))
    if (not isinstance(profile, dict) or
            any(not isinstance(profile.get('identity', {}).get(key), str) or not profile['identity'][key]
                for key in ('model', 'board', 'firmware', 'sdkVersion', 'architecture'))):
        raise InstallerError('BOOT_IDENTITY_UNVERIFIED', 'Boot persistence requires a complete device identity.', 3)
    if not native and sam_protocol != 'sam-block-release-v1':
        raise InstallerError('BOOT_REFRESH_UNVERIFIED', 'Boot requires the qualified manifest refresh contract.', 3)
    base = '/var/lib/wiios/home-transactions/' + transaction_id
    hook = BOOT_DIRECTORY + '/' + BOOT_PREFIX + transaction_id[:16]
    sha_target = target if native else target + '/appinfo.json'
    sha_source = source if native else source + '/appinfo.json'
    executor = resources.files('home.operations').joinpath('owned_mount.sh').read_bytes()
    runtime = resources.files('home.operations').joinpath('boot_runtime.js').read_bytes()
    heartbeat = resources.files('home.operations').joinpath('heartbeat.js').read_bytes()
    config = json.dumps({'identity': profile['identity'], 'transactionId': transaction_id,
                         'appId': app_id, 'native': native, 'samProtocol': sam_protocol,
                         'main': 'index.html'}, sort_keys=True, separators=(',', ':')).encode()
    shared = ['#!/bin/sh', 'set -eu', 'base=' + shlex.quote(base),
              'target=' + shlex.quote(target), 'source=' + shlex.quote(source)]
    ownership = 'sh "$base/owned-mount.sh" '
    arguments = ' "$base" "$source" "$target"'
    integrity = []
    for name, data in (('owned-mount.sh', executor), ('boot-runtime.js', runtime), ('boot-profile.json', config), ('heartbeat.js', heartbeat)):
        integrity.append('[ "$(sha256sum "$base/' + name + '" | cut -d " " -f 1)" = ' +
                         shlex.quote(hashlib.sha256(data).hexdigest()) + ' ] || exit 0')
    lines = shared + [
        '[ -f "$base/boot-enabled" ] || exit 0',
        '[ ! -e "$base/boot-disabled" ] || exit 0',
        'failures="$(cat "$base/boot-failures" 2>/dev/null || echo 2)"',
        'case "$failures" in 0|1) ;; *) exit 0 ;; esac',
        'for tool in node sha256sum mount umount nohup stat awk readlink flock; do command -v "$tool" >/dev/null || exit 0; done',
        *integrity,
        'node "$base/boot-runtime.js" "$base" preflight || exit 0',
        '[ "$(sha256sum ' + shlex.quote(sha_target) + ' | cut -d " " -f 1)" = ' + shlex.quote(original_sha256) + ' ] || exit 0',
        '[ "$(sha256sum ' + shlex.quote(sha_source) + ' | cut -d " " -f 1)" = ' + shlex.quote(staged_sha256) + ' ] || exit 0',
        *['[ "$(sha256sum ' + shlex.quote(base + '/bundle/' + name) + ' | cut -d " " -f 1)" = ' + shlex.quote(expected) + ' ] || exit 0' for name, expected in checks],
        'printf "%s\\n" "$((failures + 1))" > "$base/boot-failures"',
        'sync',
        'nohup sh -c ' + shlex.quote('cat /proc/sys/kernel/random/boot_id > ' + shlex.quote(base + '/boot-watchdog-ready') + '; sleep 120; sh ' + shlex.quote(base + '/boot-health.sh')) + ' </dev/null >/dev/null 2>&1 &',
        'i=0; until [ "$(cat "$base/boot-watchdog-ready" 2>/dev/null)" = "$(cat /proc/sys/kernel/random/boot_id)" ]; do i=$((i + 1)); [ "$i" -lt 5 ] || exit 0; sleep 1; done',
        'nohup node "$base/heartbeat.js" "$base" </dev/null >/dev/null 2>&1 &',
        ownership + 'bind' + arguments + ' || { touch "$base/boot-disabled"; exit 0; }',
        'if ! node "$base/boot-runtime.js" "$base" refresh; then sh "$base/restore.sh"; exit 0; fi',
        'exit 0',
    ]
    health_integrity = [line.replace('|| exit 0', '|| { touch "$base/boot-disabled"; sh "$base/restore.sh"; exit 1; }') for line in integrity]
    health = shared + [
        'while [ -f "$base/boot-enabled" ] && [ ! -e "$base/boot-disabled" ]; do',
        *health_integrity,
        'if ! ' + ownership + 'check' + arguments + ' || ! node "$base/boot-runtime.js" "$base" health > "$base/runtime-health.pending"; then',
        '  touch "$base/boot-disabled"',
        '  sh "$base/restore.sh"',
        '  exit 1',
        'fi',
        'mv "$base/runtime-health.pending" "$base/runtime-health.json"',
        'printf "0\\n" > "$base/boot-failures"',
        'sleep 30',
        'done',
    ]
    script = '\n'.join(lines) + '\n'
    return {'path': hook, 'script': script, 'healthScript': '\n'.join(health) + '\n',
            'runtimeScript': runtime, 'profileData': config,
            'sha256': hashlib.sha256(script.encode()).hexdigest()}

import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re
import shlex
from subprocess import TimeoutExpired

from installer.errors import InstallerError

HELPER_FILES = ('metrics.js', 'catalog.js', 'control.sh')
BASE = '/var/lib/webosbrew/wiios-metrics'
HOOK = '/var/lib/webosbrew/init.d/98-wiios-metrics'
OWNER = BASE + '/owner'
HOOK_DATA = ('#!/bin/sh\nexec sh ' + BASE + '/control.sh start\n').encode()


def helper_payload():
    embedded = files('installer').joinpath('helper_payload')
    if embedded.is_dir():
        return {name: embedded.joinpath(name).read_bytes() for name in HELPER_FILES}
    source = Path(__file__).resolve().parents[1] / 'root-services'
    return {name: (source / name).read_bytes() for name in HELPER_FILES}


def install_helper(transport, *, remove=False):
    if transport.kind != 'root-ssh':
        raise InstallerError('ROOT_HELPER_REQUIRED', 'Select Root SSH to manage the WiiOS TV helper.', 3)
    return deploy_helper(transport.execute, remove=remove)


def deploy_helper(remote, *, remove=False):
    hook_hash = hashlib.sha256(HOOK_DATA).hexdigest()
    owned = f'[ ! -L {BASE} ] && [ ! -L {HOOK} ] && [ -f {HOOK} ] && [ "$(sha256sum {HOOK} | cut -d " " -f 1)" = {hook_hash} ]'
    registered_owner = f'[ ! -L {BASE} ] && [ ! -L {OWNER} ] && [ -f {OWNER} ] && [ "$(sha256sum {OWNER} | cut -d " " -f 1)" = {hook_hash} ]'
    if remove:
        remote(f'''set -eu
test "$(id -u)" = 0
test ! -L {BASE}/control.sh
if [ -e {HOOK} ] || [ -L {HOOK} ]; then
    {owned} || exit 1
    test ! -L {OWNER}
    cp {HOOK} {OWNER}
    sh {BASE}/control.sh stop
    rm {HOOK}
else
    {registered_owner} || exit 1
    sh {BASE}/control.sh stop
fi
''')
        return {'ok': True, 'state': 'removed'}

    payload = helper_payload()
    fingerprints = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    remote('test "$(id -u)" = 0 && test -x /usr/bin/node && command -v curl >/dev/null && '
           'test ! -L /var/lib/webosbrew && mkdir -p /var/lib/webosbrew')
    stage = remote('umask 077; mktemp -d /var/lib/webosbrew/wiios-helper.XXXXXXXX').strip()
    if not re.fullmatch(r'/var/lib/webosbrew/wiios-helper\.[A-Za-z0-9]{8}', stage):
        raise InstallerError('HELPER_STAGING_FAILED', 'Failed to create a private helper staging directory.')
    try:
        for name, data in payload.items():
            remote(f'cat > {stage}/{name}', data)
        remote(f'cat > {stage}/hook', HOOK_DATA)
        checksums = ''.join(f'{digest}  {name}\n' for name, digest in dict(fingerprints, hook=hook_hash).items())
        remote(f'cd {stage} && sha256sum -c - && sh -n control.sh', checksums.encode())

        node_check = '''
const fs = require('fs');
const h = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
if (h.schema !== 1 || h.catalogFingerprint !== process.argv[2] || h.metricsFingerprint !== process.argv[3]) process.exit(1);
'''
        verify = ('curl --fail --silent --max-time 2 http://127.0.0.1:19083/v1/health > "$stage/health" && '
                  '/usr/bin/node -e ' + shlex.quote(node_check) + ' "$stage/health" ' +
                  fingerprints['catalog.js'] + ' ' + fingerprints['metrics.js'])
        script = f'''set -eu
umask 077
base={BASE}
hook={HOOK}
stage={stage}
lock=/var/lib/webosbrew/wiios-metrics-install-lock
mkdir "$lock"
persistent=0
if [ -d /var/lib/webosbrew/init.d ] && [ ! -L /var/lib/webosbrew/init.d ]; then persistent=1; fi
new=0
replacing=0
committed=0
stop() {{
    sh "$stage/control.sh" stop || return 1
    i=0
    while sh "$stage/control.sh" status >/dev/null; do
        i=$((i+1)); [ "$i" -lt 6 ] || return 1
        sleep 1
    done
}}
cleanup() {{
    result=$?
    trap - EXIT
    set +e
    if [ "$committed" = 0 ] && [ "$replacing" = 1 ]; then
        if stop; then
            for item in metrics.js catalog.js control.sh; do
                if [ -f "$stage/old-$item" ]; then
                    mv "$stage/old-$item" "$base/$item"
                else
                    rm -f "$base/$item"
                fi
            done
            if [ "$new" = 0 ]; then
                sh "$base/control.sh" start
            else
                rm -f "$base/process" "$base/metrics.log" "$base/owner"
                rmdir "$base"
            fi
        else
            printf '%s\\n' 'Helper rollback could not stop the owned process.' >&2
            result=1
            rmdir "$lock"
            exit "$result"
        fi
    fi
    rmdir "$stage/active"
    rmdir "$lock"
    exit "$result"
}}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
mkdir "$stage/active"
/usr/bin/node -e {shlex.quote("['metrics.js','catalog.js'].forEach(function(p){new Function(require('fs').readFileSync(process.argv[1]+'/'+p,'utf8'));});")} "$stage"
if [ -e "$base" ] || [ -L "$base" ] || [ -e "$hook" ] || [ -L "$hook" ]; then
    if [ -e "$hook" ] || [ -L "$hook" ]; then
        {owned} || {{ printf '%s\\n' 'Existing helper hook is unrecognized.' >&2; exit 1; }}
    else
        {registered_owner} || {{ printf '%s\\n' 'Existing helper files are unrecognized.' >&2; exit 1; }}
    fi
    [ ! -L "$base/owner" ]
    for item in metrics.js catalog.js control.sh; do
        [ ! -L "$base/$item" ]
        cp -p "$base/$item" "$stage/old-$item"
    done
    if {{ [ "$persistent" = 0 ] || [ -f "$hook" ]; }} && {verify} && cmp -s "$stage/control.sh" "$base/control.sh"; then
        printf '%s\\n' "$persistent"
        exit 0
    fi
    stop
else
    mkdir "$base"
    new=1
fi
replacing=1
for item in metrics.js catalog.js control.sh; do
    cp "$stage/$item" "$base/$item"
done
sh "$base/control.sh" start
i=0
until {verify}; do
    i=$((i+1)); [ "$i" -lt 6 ] || exit 1
    sleep 1
done
cp "$stage/hook" "$base/owner"
if [ "$persistent" = 1 ]; then
    chmod 755 "$stage/hook"
    mv "$stage/hook" "$hook"
fi
committed=1
printf '%s\\n' "$persistent"
'''
        activation = remote('sh -s', script.encode(), timeout=45).splitlines()
    finally:
        names = (*HELPER_FILES, 'hook', 'health', *('old-' + name for name in HELPER_FILES))
        try:
            remote(f'cd {stage} && test ! -d active && rm -f ' + ' '.join(names) + f' && rmdir {stage}')
        except (InstallerError, OSError, TimeoutExpired, SystemExit):
            pass

    status = {'ok': True, 'state': 'installed', 'persistent': bool(activation and activation[-1] == '1')}
    try:
        current = json.loads(remote('curl --fail --silent --show-error --max-time 12 http://127.0.0.1:19083/v1/apps'))
        if (isinstance(current, dict) and current.get('returnValue') is True and
                current.get('helperFingerprint') == fingerprints['catalog.js'] and isinstance(current.get('launchPoints'), list)):
            status['imageApps'] = sum(bool(point.get('images')) for point in current['launchPoints'] if isinstance(point, dict))
            status['catalog'] = current.get('method')
    except (InstallerError, OSError, TimeoutExpired, ValueError, SystemExit):
        pass
    return status

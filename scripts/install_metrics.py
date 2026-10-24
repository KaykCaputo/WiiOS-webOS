#!/usr/bin/env python3
import argparse
import hashlib
import time
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '/var/lib/webosbrew/wiios-metrics'
HOOK = '/var/lib/webosbrew/init.d/98-wiios-metrics'
HOOK_DATA = ('#!/bin/sh\nexec sh ' + BASE + '/control.sh start\n').encode()

def main():
    parser = argparse.ArgumentParser(description='Install or update the local WiiOS app/images and metrics helper over root SSH.')
    parser.add_argument('--host', default='192.168.68.51')
    parser.add_argument('--remove', action='store_true', help='Stop this collector and remove its own startup hook')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', args.host):
        parser.error('Invalid hostname')
    def remote(command, data=None):
        result = subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', 'root@' + args.host, command], input=data, capture_output=True, timeout=30)
        if result.returncode:
            raise SystemExit((result.stdout + result.stderr).decode(errors='replace'))
        return result.stdout.decode(errors='replace')
    hook_hash = hashlib.sha256(HOOK_DATA).hexdigest()
    if args.remove:
        print(remote("test \"$(sha256sum " + HOOK + " | awk '{print $1}')\" = " + hook_hash + ' && sh ' + BASE + '/control.sh stop && rm ' + HOOK))
        print('Owned startup hook removed; files and logs kept for inspection.')
        return
    print('Updating WiiOS helper on ' + args.host + ' (not touching Home)...', flush=True)
    payload = {name: (ROOT / 'root-services' / name).read_bytes() for name in ('metrics.js', 'catalog.js', 'control.sh')}
    remote('test "$(id -u)" = 0 && test -d /var/lib/webosbrew/init.d && test -x /usr/bin/node')
    existing = remote(f'if [ -e {BASE} ] || [ -e {HOOK} ]; then test "$(sha256sum {HOOK} | cut -d " " -f 1)" = {hook_hash} && echo OWNED; else echo NEW; fi').strip()
    if existing not in ('OWNED', 'NEW'):
        raise SystemExit('Existing helper is not owned by WiiOS')
    remote('umask 077; mkdir -p ' + BASE)
    for name, data in payload.items():
        remote('cat > ' + shlex.quote(BASE + '/' + name + '.pending'), data)
    checksum = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '.pending\n' for name, data in payload.items())
    remote('cd ' + BASE + ' && sha256sum -c - && sh -n control.sh.pending && /usr/bin/node -e ' + shlex.quote("['metrics.js.pending','catalog.js.pending'].forEach(function(p){new Function(require('fs').readFileSync(p,'utf8'));});"), checksum.encode())
    backup = BASE + '/backup-' + str(time.time_ns())
    remote('mkdir ' + backup + '; for f in metrics.js catalog.js control.sh; do if [ -f ' + BASE + '/"$f" ]; then cp -p ' + BASE + '/"$f" ' + backup + '/"$f" || exit 1; fi; done')

    stop = 'set -e; if [ -f ' + BASE + '/control.sh ]; then sh ' + BASE + '/control.sh.pending stop; i=0; while sh ' + BASE + '/control.sh.pending status; do i=$((i+1)); [ "$i" -lt 10 ] || exit 1; sleep 1; done; fi'
    try:
        remote(stop)
        remote('set -e; cd ' + BASE + '; for f in metrics.js catalog.js control.sh; do mv "$f.pending" "$f"; done; sh control.sh start')

        
        import json
        expected_catalog = hashlib.sha256(payload['catalog.js']).hexdigest()
        expected_metrics = hashlib.sha256(payload['metrics.js']).hexdigest()
        health_raw = remote('i=0; until curl --fail --silent --show-error --max-time 3 http://127.0.0.1:19083/v1/health; do i=$((i+1)); [ "$i" -lt 10 ] || exit 1; sleep 1; done')
        health = json.loads(health_raw)
        active_catalog = health.get('catalogFingerprint')
        active_metrics = health.get('metricsFingerprint')
        if (health.get('schema') != 1 or active_catalog != expected_catalog or active_metrics != expected_metrics):
            raise RuntimeError('Stale WiiOS helper: catalog ' + str(active_catalog)[:12] +
                               ' (expected ' + expected_catalog[:12] + '); metrics ' +
                               str(active_metrics)[:12] + ' (expected ' + expected_metrics[:12] +
                               '). Deployment rolled back; do not kill unowned processes.')
        
        raw_catalog = remote('curl --fail --silent --show-error --max-time 8 http://127.0.0.1:19083/v1/apps')
        current = json.loads(raw_catalog)
        if current.get('returnValue') is not True or current.get('helperFingerprint') != expected_catalog:
            raise RuntimeError('Updated helper did not expose its active app catalog. Deployment rolled back.')
        image_count = sum(bool(point.get('images')) for point in current.get('launchPoints', []) if isinstance(point, dict))
        print('Verified active helper on ' + args.host + ': ' + expected_catalog[:12] +
              ', ' + str(image_count) + ' apps with image candidates.', flush=True)
        remote('cat > ' + HOOK + '.pending && chmod 755 ' + HOOK + '.pending && mv ' + HOOK + '.pending ' + HOOK, HOOK_DATA)
    except (SystemExit, Exception):
        remote(stop)
        remote('set -e; for f in metrics.js catalog.js control.sh; do if [ -f ' + backup + '/"$f" ]; then cp -p ' + backup + '/"$f" ' + BASE + '/"$f"; else rm -f ' + BASE + '/"$f"; fi; done')
        if existing == 'OWNED':
            remote('sh ' + BASE + '/control.sh start')
        raise
    print('Local app/images and metrics helper installed; active catalog and metrics fingerprints verified.')
    print('Previous files: ' + backup)

if __name__ == '__main__':
    main()

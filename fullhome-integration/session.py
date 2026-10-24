#!/usr/bin/env python3

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

PAYLOAD = ('main.qml', 'UIController.qml', 'common.sh', 'activate.sh', 'rollback.sh', 'watchdog.sh', 'status.sh', 'config.sh', 'manifest.json', 'diagnostic.diff')

def load_bundle(path):
    manifest = json.loads((path / 'manifest.json').read_text())
    token = manifest['token']
    if not re.fullmatch(r'[a-z0-9-]{6,48}', token):
        raise ValueError('Invalid token')
    if manifest['base'] != '/var/lib/webosbrew/wiios-fullhome-diag/' + token:
        raise ValueError('Invalid remote path')
    if manifest['kind'] not in ('diagnostic-only', 'redirect-trial'):
        raise ValueError('Unsupported bundle kind')
    for entry in manifest['files']:
        if entry['name'] not in ('main.qml', 'UIController.qml'):
            raise ValueError('Invalid QML file')
        if hashlib.sha256((path / entry['name']).read_bytes()).hexdigest() != entry['patched_sha256']:
            raise ValueError('QML checksum mismatch')
    for name in PAYLOAD:
        if not (path / name).is_file() or (path / name).is_symlink():
            raise ValueError('Missing/unsafe file: ' + name)
    return manifest

def remote(host, command, data=None, tty=False, timeout=30, allowed=(0,)):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', host):
        raise ValueError('Invalid hostname')
    result = subprocess.run(['ssh', '-tt' if tty else '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2', 'root@' + host, command], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode not in allowed:
        raise RuntimeError((result.stdout + result.stderr).decode(errors='replace'))
    return result.stdout.decode(errors='replace')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'activate', 'status', 'rollback', 'capture'])
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--host', default='192.168.68.51')
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--output', type=Path, default=Path('.tools/fullhome-evidence'))
    args = parser.parse_args()
    if not 60 <= args.seconds <= 600:
        parser.error('--seconds must be 60..600')
    manifest = load_bundle(args.bundle)
    base, token = manifest['base'], manifest['token']
    call = lambda command, **kw: remote(args.host, command, **kw)
    if args.action == 'stage':

        call('umask 077; mkdir -p /var/lib/webosbrew/wiios-fullhome-diag && mkdir ' + shlex.quote(base))
        for name in PAYLOAD:
            call('cat > ' + shlex.quote(base + '/' + name), data=(args.bundle / name).read_bytes())
        checksums = ''.join(hashlib.sha256((args.bundle / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in PAYLOAD)
        print(call('cd ' + shlex.quote(base) + ' && sha256sum -c -', data=checksums.encode()))
        print('STAGED only; no mounts, launch or startup changes.')
    elif args.action == 'capture':
        args.output.mkdir(parents=True, exist_ok=True)

        commands = {
            'running': "timeout -t %d luna-send -i -f luna://com.webos.applicationManager/running '{\"subscribe\":true}'" % args.seconds,
            'qml': 'timeout -t %d tail -n 0 -F /var/log/fullhome' % args.seconds,
        }
        def capture(item):
            name, command = item
            content = call(command, tty=(name == 'running'), timeout=args.seconds + 15, allowed=(0, 124, 143))
            if name == 'qml':
                content = '\n'.join(line for line in content.splitlines() if token in line) + '\n'
            dest = args.output / (token + '-' + name + '.log')
            dest.write_text(content)
            return str(dest)
        with ThreadPoolExecutor(max_workers=2) as pool:
            for dest in pool.map(capture, commands.items()):
                print(dest)
    else:
        command = 'sh ' + shlex.quote(base + '/' + ('rollback.sh' if args.action == 'rollback' else args.action + '.sh'))
        if args.action == 'activate': command += ' --activate ' + str(args.seconds)
        if args.action == 'rollback': command += ' --confirm ' + token
        print(call(command))

if __name__ == '__main__':
    main()

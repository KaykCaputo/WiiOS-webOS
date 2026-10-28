#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PRIVACY = ROOT / 'privacy'
BASE = '/var/lib/webosbrew/wiios-fullhome-diag/diag-3e891511b377'
PRIV_BASE = '/var/lib/webosbrew/wiios-privacy'
HOME_HOOK = '/var/lib/webosbrew/init.d/99-wiios-fullhome'
PRIV_HOOK = '/var/lib/webosbrew/init.d/97-wiios-privacy'
def remote(host, command, data=None, timeout=45):
    result = subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=7', 'root@' + host, command], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    output = (result.stdout + result.stderr).decode(errors='replace').strip()
    if result.returncode:
        raise RuntimeError(output or f'SSH failed: {result.returncode}')
    return output

def quote(value):
    return shlex.quote(str(value))

def send(host, source, destination):
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    present = remote(host, 'if [ -f ' + quote(destination) + ' ]; then sha256sum ' + quote(destination) + ' | cut -d \" \" -f 1; else echo ABSENT; fi')
    if present == digest:
        return
    tmp = destination + '.wiios-pending'
    remote(host, 'umask 077; cat > ' + quote(tmp), data=data)
    remote(host, 'test "$(sha256sum ' + quote(tmp) + ' | cut -d " " -f 1)" = ' + quote(digest) + ' && mv ' + quote(tmp) + ' ' + quote(destination))




def install_home(host):
    raise RuntimeError('Legacy Home activation is disabled. Use the installer compatibility report and qualify recovery first.')

def install_privacy(host):
    remote(host, 'test "$(id -u)" = 0 && mkdir -p /var/lib/webosbrew/init.d && mkdir -p ' + quote(PRIV_BASE))
    output = remote(host, 'if [ -e ' + quote(PRIV_HOOK) + ' ]; then grep -Fq ' + quote(PRIV_BASE) + ' ' + quote(PRIV_HOOK) + ' && echo OWNED; else echo ABSENT; fi')
    if output not in ('OWNED', 'ABSENT'):
        raise RuntimeError('Privacy startup hook belongs to another program')
    for name in ('apply.sh', 'hosts.txt'):
        send(host, PRIVACY / name, PRIV_BASE + '/' + name)
    send(host, PRIVACY / '97-wiios-privacy', PRIV_HOOK)
    remote(host, 'chmod 755 ' + quote(PRIV_HOOK) + ' && sh -n ' + quote(PRIV_BASE) + '/apply.sh')
    print(remote(host, 'sh ' + quote(PRIV_BASE) + '/apply.sh'))
    print('Privacy hook installed')

def disable(host, key):
    hook, needle = (HOME_HOOK, BASE) if key == 'home' else (PRIV_HOOK, PRIV_BASE)
    result = remote(host, 'if [ -e ' + quote(hook) + ' ]; then grep -Fq ' + quote(needle) + ' ' + quote(hook) + ' || exit 1; rm ' + quote(hook) + '; echo DISABLED; else echo ALREADY_DISABLED; fi')
    print(key + ': ' + result)
    print('Restart the TV to remove active bind mounts')

def status(host):
    cmd = '''echo '=== INSTALLED APP ==='; grep -E '"version"' /media/developer/apps/usr/palm/applications/com.wiios.launcher/appinfo.json 2>/dev/null || :; echo '=== PRIVACY HOOK ==='; if [ -f /var/lib/webosbrew/init.d/97-wiios-privacy ]; then echo PRESENT; else echo ABSENT; fi; echo '=== BOOT HOOKS ==='; ls -l /var/lib/webosbrew/init.d/*wiios* 2>/dev/null || :; echo '=== QML/HOSTS MOUNTS ==='; awk '$5=="/etc/hosts" || $5=="/usr/palm/applications/com.webos.app.fullhome/qml/main.qml" || $5=="/usr/palm/applications/com.webos.app.fullhome/qml/UserInterfaceLayer/UIController.qml" {print}' /proc/self/mountinfo; echo '=== SESSIONS ==='; cat /var/lib/webosbrew/wiios-fullhome-diag/diag-3e891511b377/state/status 2>/dev/null || :; echo '=== BOOT LOG ==='; tail -n 12 /var/lib/webosbrew/wiios-fullhome-permanent.log 2>/dev/null || :; echo '=== APP LAUNCH LOG ==='; tail -n 12 /var/lib/webosbrew/wiios-fullhome-diag/diag-3e891511b377/launch-on-boot.log 2>/dev/null || :; echo '=== PRIVACY LOG ==='; tail -n 8 /var/lib/webosbrew/wiios-privacy/privacy.log 2>/dev/null || :'''
    print(remote(host, cmd))

def main():
    parser = argparse.ArgumentParser(description='WiiOS legacy maintenance and installer entry point')
    parser.add_argument('action', choices=['install', 'app', 'home', 'metrics', 'privacy', 'status', 'home-off', 'privacy-off', 'off'])
    parser.add_argument('--host', required=True)
    parser.add_argument('--transport', choices=['developer-mode', 'root-ssh'], default='developer-mode')
    parser.add_argument('--port', type=int)
    parser.add_argument('--user')
    parser.add_argument('--identity')
    parser.add_argument('--known-hosts', default=str(Path.home() / '.wiios' / 'known_hosts'))
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', args.host):
        parser.error('Invalid host')
    if args.action in ('install', 'app'):
        if not args.port or not args.user:
            parser.error('App installation requires explicit --port and --user; Developer Mode is the default transport')
        sys.path.insert(0, str(ROOT))
        from build import build
        from installer.cli import main as installer_main
        package = build()
        command = ['install', '--host', args.host, '--transport', args.transport,
                   '--port', str(args.port), '--user', args.user, '--known-hosts', args.known_hosts,
                   '--ipk', str(package), '--mode', 'app']
        if args.identity:
            command += ['--identity', args.identity]
        raise SystemExit(installer_main(command))
    elif args.action == 'home':
        install_home(args.host)
    elif args.action == 'metrics':
        subprocess.run([sys.executable, str(ROOT / 'scripts/install_metrics.py'), '--host', args.host], check=True)
    elif args.action == 'privacy':
        install_privacy(args.host)
    elif args.action == 'status':
        status(args.host)
    elif args.action == 'off':
        disable(args.host, 'home')
        disable(args.host, 'privacy')
    elif args.action.endswith('-off'):
        disable(args.host, args.action[:-4])

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, subprocess.TimeoutExpired, FileNotFoundError) as error:
        sys.exit(str(error))

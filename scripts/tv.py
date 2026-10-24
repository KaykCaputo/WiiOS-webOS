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
BUNDLE = ROOT / 'fullhome-integration' / 'bundle'
PRIVACY = ROOT / 'privacy'
BASE = '/var/lib/webosbrew/wiios-fullhome-diag/diag-3e891511b377'
PRIV_BASE = '/var/lib/webosbrew/wiios-privacy'
HOME_HOOK = '/var/lib/webosbrew/init.d/99-wiios-fullhome'
PRIV_HOOK = '/var/lib/webosbrew/init.d/97-wiios-privacy'
HOME_FILES = ('main.qml', 'UIController.qml', 'activate.sh', 'common.sh', 'rollback.sh', 'config.sh', 'manifest.json', 'boot.sh', 'launch-on-boot.sh', 'wake-monitor.sh', 'disable-startup.sh', '99-wiios-fullhome', 'persistent.sha256')

def remote(host, command, data=None, timeout=45):
    result = subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=7', 'root@' + host, command], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
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

def validate_bundle():
    manifest = json.loads((BUNDLE / 'manifest.json').read_text())
    if manifest.get('base') != BASE or not manifest.get('permanent_variant') or manifest.get('deadline') != 0:
        raise ValueError('Unsupported Full Home bundle')
    for item in manifest['files']:
        p = BUNDLE / item['name']
        if hashlib.sha256(p.read_bytes()).hexdigest() != item['patched_sha256']:
            raise ValueError('Invalid QML checksum: ' + str(p))
    for row in (BUNDLE / 'persistent.sha256').read_text().splitlines():
        digest, name = row.split()
        if hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Invalid persistent checksum: ' + name)
    return manifest

def installed_version(host, version):
    info = '/media/developer/apps/usr/palm/applications/com.wiios.launcher/appinfo.json'
    pattern = r'"version"[[:space:]]*:[[:space:]]*"' + re.escape(version) + r'"'
    script = 'if [ -f ' + quote(info) + ' ] && grep -Eq ' + quote(pattern) + ' ' + quote(info) + '; then echo INSTALLED; else echo ABSENT; fi'
    return remote(host, script, timeout=12).strip() == 'INSTALLED'

def install_app(host):
    from build import build
    package = build()
    version = json.loads((ROOT / 'appinfo.json').read_text())['version']
    print('[1/4] Checking the installed version...', flush=True)
    if installed_version(host, version):
        print('WiiOS ' + version + ' is already installed; skipping IPK installation.', flush=True)
        return
    remote(host, 'test "$(id -u)" = 0 && mkdir -p /var/lib/webosbrew', timeout=12)
    print('[2/4] Uploading IPK (' + str(package.stat().st_size) + ' bytes)...', flush=True)
    send(host, package, '/tmp/wiios-launcher.ipk')
    print('[3/4] Requesting installation from webOS...', flush=True)
    payload = json.dumps({'id': 'com.wiios.launcher', 'ipkUrl': '/tmp/wiios-launcher.ipk', 'subscribe': True}, separators=(',', ':'))
    command = 'luna-send -n 1 -w 8000 -f luna://com.webos.appInstallService/dev/install ' + quote(payload)
    response = ''
    request_error = ''
    try:
        response = remote(host, command, timeout=15)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        request_error = str(error)
        print('No immediate response from the install service; checking the installed version...', flush=True)
    if re.search(r'"returnValue"\s*:\s*false', response):
        raise RuntimeError('webOS rejected the installation: ' + response)
    print('[4/4] Checking installation progress...', flush=True)
    for attempt in range(16):
        if installed_version(host, version):
            print('WiiOS ' + version + ' confirmed on the TV.', flush=True)
            return
        if attempt < 15:
            if attempt % 3 == 0:
                print('Installation in progress; check ' + str(attempt + 1) + '/16...', flush=True)
            time.sleep(4)
    extra = (' Service response: ' + response) if response else (' Request error: ' + request_error)
    raise RuntimeError('Could not confirm WiiOS ' + version + ' on the TV after 60 seconds.' + extra + ' No startup hooks were modified.')

def install_home(host):
    manifest = validate_bundle()
    main = manifest['files'][0]
    controller = manifest['files'][1]
    remote(host, 'test "$(id -u)" = 0 && test -d /var/lib/webosbrew && test -d /var/lib/webosbrew/init.d')
    script = '\n'.join([
        'set -eu',
        f'BASE={quote(BASE)}',
        'mkdir -p "$BASE"',
        'if [ -f "$BASE/main.qml" ]; then',
        f'  test "$(sha256sum "$BASE/main.qml" | cut -d " " -f 1)" = {quote(main["patched_sha256"])} || exit 1',
        'fi',
        'if [ -f "$BASE/UIController.qml" ]; then',
        f'  test "$(sha256sum "$BASE/UIController.qml" | cut -d " " -f 1)" = {quote(controller["patched_sha256"])} || exit 1',
        'fi',
        f'test "$(sha256sum {quote(main["target"])} | cut -d " " -f 1)" = {quote(main["original_sha256"])} || test "$(sha256sum {quote(main["target"])} | cut -d " " -f 1)" = {quote(main["patched_sha256"])} || exit 1',
        f'test "$(sha256sum {quote(controller["target"])} | cut -d " " -f 1)" = {quote(controller["original_sha256"])} || test "$(sha256sum {quote(controller["target"])} | cut -d " " -f 1)" = {quote(controller["patched_sha256"])} || exit 1',
        "MAIN_ROW=$(awk -v t=" + quote(main["target"]) + " '$5==t {print $4}' /proc/self/mountinfo)",
        "CTRL_ROW=$(awk -v t=" + quote(controller["target"]) + " '$5==t {print $4}' /proc/self/mountinfo)",
        f'if [ "$(sha256sum {quote(main["target"])} | cut -d " " -f 1)" = {quote(main["patched_sha256"])} ]; then [ "$MAIN_ROW" = "$BASE/main.qml" ] || exit 1; else [ -z "$MAIN_ROW" ] || exit 1; fi',
        f'if [ "$(sha256sum {quote(controller["target"])} | cut -d " " -f 1)" = {quote(controller["patched_sha256"])} ]; then [ "$CTRL_ROW" = "$BASE/UIController.qml" ] || exit 1; else [ -z "$CTRL_ROW" ] || exit 1; fi',
        f'if [ -f {quote(HOME_HOOK)} ]; then grep -Fq {quote(BASE)} {quote(HOME_HOOK)} || exit 1; fi',
        'echo HOME_PRECHECK_OK',
    ])
    if 'HOME_PRECHECK_OK' not in remote(host, 'sh -eu -c ' + quote(script)):
        raise RuntimeError('Home preflight failed')
    backup = BASE + '/scripts-backup-' + str(int(time.time()))
    remote(host, 'umask 077; mkdir ' + quote(backup) + '; for n in activate.sh boot.sh launch-on-boot.sh wake-monitor.sh 99-wiios-fullhome; do [ ! -f ' + quote(BASE) + '/"$n" ] || cp ' + quote(BASE) + '/"$n" ' + quote(backup) + '/; done')
    for name in HOME_FILES:
        send(host, BUNDLE / name, BASE + '/' + name)
    validation = 'cd ' + quote(BASE) + ' && sha256sum -c persistent.sha256 && sh -n activate.sh && sh -n boot.sh && sh -n launch-on-boot.sh && sh -n wake-monitor.sh'
    print(remote(host, validation))
    send(host, BUNDLE / '99-wiios-fullhome', HOME_HOOK)
    remote(host, 'chmod 755 ' + quote(HOME_HOOK))
    active_cmd = 'if [ "$(cat ' + quote(BASE + '/state/status') + ' 2>/dev/null)" = ACTIVE ] && [ "$(cat ' + quote(BASE + '/state/boot-id') + ' 2>/dev/null)" = "$(cat /proc/sys/kernel/random/boot_id)" ]; then echo ACTIVE; else echo INACTIVE; fi'
    if remote(host, active_cmd) == 'ACTIVE':
        print('Home is already active in this boot; skipping additional startup.')
    else:
        print(remote(host, 'sh ' + quote(HOME_HOOK)))
    print('Home boot hook installed; log: /var/lib/webosbrew/wiios-fullhome-permanent.log')
    print('Backup of previous scripts: ' + backup)

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
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'app', 'home', 'privacy', 'status', 'home-off', 'privacy-off', 'off'])
    parser.add_argument('--host', default='192.168.68.51')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', args.host):
        parser.error('Invalid host')
    if args.action == 'install':
        subprocess.run([sys.executable, str(ROOT / 'scripts/install_metrics.py'), '--host', args.host], check=True)
        install_app(args.host)
        install_home(args.host)
        install_privacy(args.host)
    elif args.action == 'app':
        subprocess.run([sys.executable, str(ROOT / 'scripts/install_metrics.py'), '--host', args.host], check=True)
        install_app(args.host)
    elif args.action == 'home':
        install_home(args.host)
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

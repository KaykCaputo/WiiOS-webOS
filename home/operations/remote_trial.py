import hashlib
import io
from importlib import resources
import json
from pathlib import Path
import re
import secrets
import shlex
import tarfile

from compatibility.mountinfo import parse_mountinfo, related_mounts
from compatibility.signatures import canonical, profile_digest
from installer.errors import InstallerError


IDENTIFIER = re.compile(r'[a-f0-9]{64}\Z')
SAFE_HOME = re.compile(r'/usr/palm/applications/com\.webos\.app\.(?:home|fullhome)(?:/[A-Za-z0-9_.-]+)*\Z')
REMOTE_ROOT = '/var/lib/wiios/home-transactions'


def validated_target(target):
    if not isinstance(target, str) or not SAFE_HOME.fullmatch(target) or '/..' in target:
        raise InstallerError('HOME_TARGET_INVALID', 'The Home target is not an approved system application path.', 8)
    return target


def verified_archive(source, manifest):
    source = Path(source)
    if not source.is_dir() or source.is_symlink() or not isinstance(manifest, dict):
        raise InstallerError('HOME_BUNDLE_INVALID', 'A verified Home bundle is required.', 3)
    expected = manifest.get('files')
    if not isinstance(expected, dict) or not expected or len(expected) > 512:
        raise InstallerError('HOME_BUNDLE_INVALID', 'The bundle manifest is invalid.', 3)
    stream = io.BytesIO()
    size = 0
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, checksum in sorted(expected.items()):
            if (not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name)
                    or any(part in ('.', '..') for part in name.split('/')) or not IDENTIFIER.fullmatch(checksum)):
                raise InstallerError('HOME_BUNDLE_PATH_INVALID', 'The bundle includes an invalid file path or digest.', 8)
            target = source / name
            if target.is_symlink() or not target.is_file():
                raise InstallerError('HOME_BUNDLE_FILE_INVALID', 'Only ordinary, verified files are allowed.', 8)
            data = target.read_bytes()
            size += len(data)
            if size > 50 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != checksum:
                raise InstallerError('HOME_BUNDLE_HASH_MISMATCH', 'The local Home bundle failed its digest check.', 8)
            metadata = tarfile.TarInfo('bundle/' + name)
            metadata.size = len(data)
            metadata.mode = 0o600
            metadata.mtime = 0
            archive.addfile(metadata, io.BytesIO(data))
    all_entries = list(source.rglob('*'))
    if any(p.is_symlink() for p in all_entries):
        raise InstallerError('HOME_BUNDLE_SYMLINK', 'Symbolic links are not permitted in a Home bundle.', 8)
    actual = {p.relative_to(source).as_posix() for p in all_entries if p.is_file()}
    if actual != set(expected) | {'wiios-home-bundle.json'}:
        raise InstallerError('HOME_BUNDLE_UNEXPECTED_FILE', 'The Home bundle contains unexpected files.', 8)
    return stream.getvalue()


class RemoteHomeTrial:
    def __init__(self, transport, profile, plan, bundle_directory, bundle_manifest):
        self.transport = transport
        self.profile = profile
        self.plan = plan
        self.bundle_directory = Path(bundle_directory)
        self.bundle_manifest = bundle_manifest
        transaction_id = plan.get('transactionId', '')
        if not IDENTIFIER.fullmatch(transaction_id):
            raise InstallerError('INVALID_TRANSACTION', 'A valid transaction identifier is required.', 8)
        self.directory = REMOTE_ROOT + '/' + transaction_id
        self.stock_target = validated_target(profile['home']['effectiveDirectory'])
        self.source = self.directory + '/bundle'
        self.mount_receipt = None

    def shell(self, command, data=None, timeout=25):
        return self.transport.execute(command, data=data, timeout=timeout)

    def profile_check(self):
        if self.transport.kind != 'root-ssh' or not self.profile['transport']['root']:
            raise InstallerError('ROOT_REQUIRED', 'A verified root SSH connection is required.', 3)
        if profile_digest(self.profile) != self.plan['deviceProfileDigest']:
            raise InstallerError('PROFILE_CHANGED', 'The signed device profile differs from the current TV.', 8)
        if self.profile['home']['foreignMounts'] or self.profile['home']['conflictingHooks']:
            raise InstallerError('HOME_CONFLICT', 'A foreign Home modification was detected.', 7)
        if self.profile['home']['namespaceVerified'] is not True:
            raise InstallerError('MOUNT_NAMESPACE_UNVERIFIED', 'The effective Home mount namespace is not proven.', 7)
        if self.plan['adapter'] != 'home-directory-takeover' or self.profile['home']['implementation'] not in ('web', 'flutter'):
            raise InstallerError('HOME_ADAPTER_UNSUPPORTED', 'The current remote trial supports verified web Home only.', 3)
        if self.profile['home']['stockManifestSha256'] != self.bundle_manifest['stockManifestSha256']:
            raise InstallerError('STOCK_MANIFEST_CHANGED', 'The original Home manifest does not match the bundle.', 8)
        if self.profile['home']['appId'] != self.bundle_manifest['homeAppId']:
            raise InstallerError('HOME_ID_CHANGED', 'The original Home identity does not match the bundle.', 8)

    def inspect_mounts(self):
        info = self.shell('cat /proc/self/mountinfo')
        return related_mounts(parse_mountinfo(info), self.stock_target)

    def preflight(self, plan=None):
        if plan is not None and plan != self.plan:
            raise InstallerError('HOME_PLAN_CHANGED', 'The approved Home plan has changed.', 8)
        self.profile_check()
        result = self.shell('id -u; command -v mount; command -v umount; command -v tar; command -v sha256sum; command -v nohup; command -v sleep; command -v findmnt; command -v flock')
        if not result.splitlines() or result.splitlines()[0].strip() != '0' or len(result.splitlines()) < 9:
            raise InstallerError('REMOTE_TOOLS_UNAVAILABLE', 'The TV lacks a required root operation or recovery command.', 3)
        if self.inspect_mounts():
            raise InstallerError('HOME_MOUNT_CONFLICT', 'A Home mount already exists in the observed namespace.', 7)
        digest = self.shell('sha256sum ' + shlex.quote(self.stock_target + '/appinfo.json')).split()[0]
        if digest != self.profile['home']['stockManifestSha256']:
            raise InstallerError('STOCK_HOME_CHANGED', 'The stock Home manifest has changed.', 8)
        self.shell('test -d ' + shlex.quote(self.stock_target) + ' && test ! -L ' + shlex.quote(self.stock_target))

    def write_device_journal(self, record):
        if record.get('transactionId') != self.plan['transactionId']:
            raise InstallerError('JOURNAL_MISMATCH', 'The transaction identity changed.', 8)
        record = dict(record, recoveryMetadata={'profile': self.profile, 'bundleManifest': self.bundle_manifest,
                      'samProtocol': getattr(self, 'sam_protocol', None),
                      'nativeContract': getattr(self, 'native_contract', None),
                      'launchPayload': getattr(self, 'launch_payload', None)})
        payload = canonical(record) + b'\n'
        target = self.directory + '/journal.json'
        self.shell('umask 077; mkdir -p ' + shlex.quote(self.directory) +
                   '; cat > ' + shlex.quote(target + '.pending') +
                   ' && mv -f ' + shlex.quote(target + '.pending') + ' ' + shlex.quote(target) +
                   ' && sync', data=payload)

    def stage_bundle(self):
        archive = verified_archive(self.bundle_directory, self.bundle_manifest)
        self.shell('umask 077; mkdir -p ' + shlex.quote(self.directory) +
                   '; tar -xz -C ' + shlex.quote(self.directory), data=archive, timeout=120)
        for name, expected in sorted(self.bundle_manifest['files'].items()):
            remote = self.source + '/' + name
            checksum = self.shell('sha256sum ' + shlex.quote(remote)).split()[0]
            if checksum != expected:
                raise InstallerError('REMOTE_BUNDLE_HASH_MISMATCH', 'The TV staged payload failed verification.', 8)
        return {'staged': True, 'directory': self.source, 'fileCount': len(self.bundle_manifest['files'])}

    def mount_command(self, action, target=None, source=None):
        return 'sh ' + ' '.join(shlex.quote(value) for value in (
            self.directory + '/owned-mount.sh', action, self.directory,
            source or self.source, target or self.stock_target))

    def install_recovery_executor(self):
        script = resources.files('home.operations').joinpath('owned_mount.sh').read_bytes()
        path = self.directory + '/owned-mount.sh'
        self.shell('umask 077; cat > ' + shlex.quote(path) + ' && chmod 700 ' + shlex.quote(path), data=script)
        actual = self.shell('sha256sum ' + shlex.quote(path)).split()
        if not actual or actual[0] != hashlib.sha256(script).hexdigest():
            raise InstallerError('RECOVERY_EXECUTOR_CHANGED', 'The recovery executor failed its digest check.', 8)

    def stop_native_script(self):
        base = shlex.quote(self.directory)
        return ('base=' + base + '\n'
                '[ -f "$base/native-pid" ] || exit 0\n'
                'pid="$(sed -n 1p "$base/native-pid")"\n'
                'start="$(sed -n 2p "$base/native-pid")"\n'
                'case "$pid:$start" in *[!0-9:]*|:*|*:) exit 7 ;; esac\n'
                '[ -f "/proc/$pid/stat" ] || exit 0\n'
                "actual=\"$(sed \"s/.*) //\" \"/proc/$pid/stat\" | awk '{print $20}')\"\n"
                '[ "$actual" = "$start" ] || exit 7\n'
                "tr '\\000' '\\n' < \"/proc/$pid/cmdline\" | grep -Fx \"$base/bundle/wam-launch.json\" >/dev/null || exit 7\n"
                'kill -TERM "$pid"\n'
                'i=0; while [ -e "/proc/$pid/stat" ]; do i=$((i + 1)); [ "$i" -lt 5 ] || exit 6; sleep 1; done\n')

    def recovery_script(self, target=None, source=None):
        body = '#!/bin/sh\nset -eu\n' + self.mount_command('restore', target, source) + '\n'
        if target is None:
            app_id = shlex.quote(json.dumps({'id': self.profile['home']['appId']}, separators=(',', ':')))
            if self.plan['adapter'] == 'native-home-standin':
                body += '(\n' + self.stop_native_script() + ')\n'
            if self.plan['adapter'] == 'home-directory-takeover':
                body += ('blocked=0\n'
                         'luna-send -n 1 -w 4000 luna://com.webos.applicationManager/blockSystemApp '
                         + app_id + ' > ' + shlex.quote(self.directory + '/restore-block.json') + ' 2>&1 || blocked=1\n'
                         'luna-send -n 1 -w 4000 luna://com.webos.applicationManager/releaseBlockSystemApp '
                         + app_id + ' > ' + shlex.quote(self.directory + '/restore-release.json') + ' 2>&1\n'
                         '[ "$blocked" = 0 ] || exit 6\n')
            body += ('luna-send -n 1 -w 4000 luna://com.webos.applicationManager/launch '
                     + app_id + ' > ' + shlex.quote(self.directory + '/restore-launch.json') + ' 2>&1\n'
                     'printf "%s\\n" LG_HOME_FILES_RESTORED > ' + shlex.quote(self.directory + '/recovery-status') + '\n')
        return body

    def stage_heartbeat(self):
        script = resources.files('home.operations').joinpath('heartbeat.js').read_bytes()
        self.shell('umask 077; cat > ' + shlex.quote(self.directory + '/heartbeat.js'), data=script)
        config = {'appId': self.profile['home']['appId'], 'transactionId': self.plan['transactionId'],
                  'token': secrets.token_hex(32)}
        self.shell('umask 077; cat > ' + shlex.quote(self.directory + '/bundle/wiios-home-session.json'),
                   data=canonical(config))

    def start_heartbeat(self):
        self.shell("node -e 'if (parseInt(process.versions.node, 10) < 8) process.exit(3)'")
        command = 'node ' + shlex.quote(self.directory + '/heartbeat.js') + ' ' + shlex.quote(self.directory)
        self.shell('nohup ' + command + ' </dev/null >/dev/null 2>&1 &')
        self.shell('i=0; until test -f ' + shlex.quote(self.directory + '/heartbeat-ready') +
                   '; do i=$((i + 1)); test "$i" -lt 5 || exit 6; sleep 1; done')

    def arm_watchdog(self, seconds):
        if not 30 <= seconds <= 600:
            raise InstallerError('TRIAL_TIMEOUT_INVALID', 'Trial recovery must have a bounded timeout.', 8)
        self.install_recovery_executor()
        self.stage_heartbeat()
        scratch = self.directory + '/recovery-self-test'
        check_source, check_target = scratch + '/source', scratch + '/target'
        self.shell('mkdir -p ' + shlex.quote(check_source) + ' ' + shlex.quote(check_target))
        self.shell(self.mount_command('bind', check_target, check_source))
        check = self.recovery_script(check_target, check_source).encode()
        self.shell('sh -s', data=check)
        if self.shell('findmnt -n -o SOURCE -M ' + shlex.quote(check_target) + ' || true').strip():
            raise InstallerError('RECOVERY_SELF_TEST_FAILED', 'The isolated rollback drill left a mount active.', 6)
        path = self.directory + '/restore.sh'
        self.shell('umask 077; cat > ' + shlex.quote(path) +
                   ' && chmod 700 ' + shlex.quote(path), data=self.recovery_script().encode())
        self.shell('sh -n ' + shlex.quote(path))
        ready = self.directory + '/watchdog-ready'
        command = ('umask 077; echo ready > ' + shlex.quote(ready) + '; sleep ' + str(seconds) +
                   '; if [ ! -e ' + shlex.quote(self.directory + '/watchdog-cancelled') +
                   ' ]; then sh ' + shlex.quote(path) + '; fi')
        process = self.shell('nohup sh -c ' + shlex.quote(command) +
                             ' >/dev/null 2>&1 </dev/null & echo $!')
        pid = process.strip().splitlines()[-1] if process.strip() else ''
        if not re.fullmatch(r'[1-9][0-9]{0,9}', pid):
            raise InstallerError('WATCHDOG_NOT_STARTED', 'The independent watchdog did not report a process ID.', 6)
        self.shell('i=0; until test -f ' + shlex.quote(ready) +
                   '; do i=$((i + 1)); test "$i" -lt 5 || exit 6; sleep 1; done')
        self.start_heartbeat()
        return {'armed': True, 'recoverySelfTestPassed': True, 'pid': int(pid), 'timeoutSeconds': seconds}

    def bind(self):
        if self.inspect_mounts():
            raise InstallerError('HOME_MOUNT_CONFLICT', 'Another Home mount was detected before activation.', 7)
        self.shell(self.mount_command('bind'))
        mounts = self.inspect_mounts()
        if len(mounts) != 1 or mounts[0].target != self.stock_target:
            raise InstallerError('HOME_MOUNT_UNVERIFIED', 'The new Home mount was not independently confirmed.', 6)
        self.mount_receipt = mounts[0].to_dict()
        return {'mount': self.mount_receipt, 'stagedSource': self.source, 'ownership': 'device-ledger-v1'}

    def restore_mount(self, receipt, allow_reboot=False):
        if not isinstance(receipt, dict) or (receipt and receipt.get('stagedSource') != self.source):
            raise InstallerError('MOUNT_RECEIPT_INVALID', 'The mount receipt is invalid.', 8)
        self.shell(self.mount_command('restore'))
        if self.inspect_mounts():
            raise InstallerError('HOME_RESTORE_UNCONFIRMED', 'The Home mount remains active.', 6)
        return {'restored': True, 'target': self.stock_target}

    def verify_staged_payload(self):
        for name, expected in self.bundle_manifest['files'].items():
            result = self.shell('sha256sum ' + shlex.quote(self.directory + '/bundle/' + name)).split()
            if not result or result[0] != expected:
                return False
        return True

    def refresh_manifest(self, protocol):
        if protocol != 'sam-block-release-v1' or self.profile['capabilities']['samManifestReload'] != 'available':
            raise InstallerError('SAM_REFRESH_UNQUALIFIED', 'A tested SAM manifest refresh protocol is required.', 3)
        app_id = self.profile['home']['appId']
        schema = self.shell('cat /etc/palm/schemas/sam/applicationManager.blockSystemApp.schema 2>/dev/null || true')
        payload = {'id': app_id}
        if '"forceBlockSystemApp"' in schema:
            payload['forceBlockSystemApp'] = False
        block_result = None
        try:
            block_result = self.transport.luna('luna://com.webos.applicationManager/blockSystemApp', payload)
            if not isinstance(block_result, dict) or block_result.get('returnValue') is not True:
                raise InstallerError('SAM_BLOCK_REFUSED', 'SAM did not accept a controlled Home refresh.', 5)
        finally:
            released = False
            for _ in range(3):
                try:
                    response = self.transport.luna('luna://com.webos.applicationManager/releaseBlockSystemApp', {'id': app_id})
                    if response.get('returnValue') is True:
                        released = True
                        break
                except Exception:
                    pass
            if not released:
                raise InstallerError('SAM_RELEASE_FAILED', 'SAM did not confirm the required Home unblock.', 6)
        return {'registeredRefresh': True, 'method': protocol}

    def manager_manifest(self, require_web=True):
        response = self.transport.luna('luna://com.webos.applicationManager/getAppInfo', {'id': self.profile['home']['appId']})
        app = response.get('appInfo') or response.get('app') or response
        if response.get('returnValue') is False or not isinstance(app, dict) or app.get('id') != self.profile['home']['appId']:
            raise InstallerError('SAM_HOME_UNCONFIRMED', 'SAM did not confirm the expected Home application.', 5)
        if require_web and (app.get('type') != 'web' or 'home' not in app.get('appCategory', [])):
            raise InstallerError('SAM_HOME_TYPE_MISMATCH', 'SAM has not registered WiiOS as a web Home.', 5)
        return {'samConfirmed': True, 'appId': app['id'], 'type': app.get('type')}

    def close_stock_home(self):
        response = self.transport.luna('luna://com.webos.applicationManager/close', {'id': self.profile['home']['appId']})
        if response.get('returnValue') is not True:
            raise InstallerError('HOME_CLOSE_REFUSED', 'SAM refused the current Home lifecycle transition.', 5)
        return {'closed': True}

    def launch_home(self):
        response = self.transport.luna('luna://com.webos.applicationManager/launch', {'id': self.profile['home']['appId']})
        if response.get('returnValue') is not True:
            raise InstallerError('HOME_LAUNCH_REFUSED', 'SAM did not accept the Home launch.', 5)
        return {'launchAccepted': True, 'visible': False}

    def stop_watchdog(self, receipt):
        pid = receipt.get('pid') if isinstance(receipt, dict) else None
        if not isinstance(pid, int) or not 1 <= pid <= 2147483647:
            raise InstallerError('WATCHDOG_PID_INVALID', 'The watchdog identifier is invalid.', 8)
        self.shell('umask 077; touch ' + shlex.quote(self.directory + '/watchdog-cancelled'))
        return {'disarmed': True, 'mechanism': 'transaction-cancellation-file'}

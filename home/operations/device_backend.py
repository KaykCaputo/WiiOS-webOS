from copy import deepcopy
import json
import shlex
import re

from home.operations.remote_trial import RemoteHomeTrial
from home.operations.guarded_boot import BOOT_DIRECTORY, BOOT_PREFIX, build_boot_hook
from installer.errors import InstallerError


class DeviceHomeBackend(RemoteHomeTrial):
    def __init__(self, transport, profile, plan, bundle_directory, bundle_manifest,
                 sam_protocol=None, physical_home_confirmed=False):
        super().__init__(transport, profile, plan, bundle_directory, bundle_manifest)
        self.sam_protocol = sam_protocol
        self.physical_home_confirmed = physical_home_confirmed
        self.receipts = {}
        self.physical_stock_confirmed = False

    def guarded_boot_artifact(self):
        native = self.plan['adapter'] == 'native-home-standin'
        expected_source = (self.native_payload['sha256'] if native else
                           self.bundle_manifest['files']['appinfo.json'])
        stock = (self.profile['home']['nativeEntrypointSha256'] if native else
                 self.profile['home']['stockManifestSha256'])
        files = dict(self.bundle_manifest['files'])
        if native:
            files['wam-launch.json'] = self.native_payload['launchSha256']
        return build_boot_hook(self.plan['transactionId'], self.stock_target,
                               self.source, stock, expected_source,
                               self.profile['home']['appId'], native, files, self.profile, self.sam_protocol)

    def preflight_persistence(self, plan, record):
        self.profile_check()
        if plan != self.plan or record.get('state') != 'LIVE_VERIFIED':
            raise InstallerError('PERSISTENCE_STATE_INVALID', 'A verified Home trial is required.', 8)
        owned = [event.get('receipt') for event in record['events']
                 if event['operation']['action'] in ('bind-home-directory', 'bind-native-standin-trial')
                 and event['state'] == 'APPLIED']
        if len(owned) != 1 or not owned[0].get('mount') or owned[0].get('stagedSource') != self.source:
            raise InstallerError('PERSISTENCE_MOUNT_UNOWNED', 'Only a verified WiiOS mount may persist.', 8)
        current = self.inspect_mounts()
        if len(current) != 1 or current[0].to_dict() != owned[0]['mount'] or not self.integrity(plan):
            raise InstallerError('PERSISTENCE_MOUNT_CHANGED', 'The active Home mount or payload has changed.', 7)
        self.shell('test -d ' + shlex.quote(BOOT_DIRECTORY) + ' && test ! -L ' +
                   shlex.quote(BOOT_DIRECTORY))
        artifact = self.guarded_boot_artifact()
        self.shell('test ! -e ' + shlex.quote(artifact['path']) + ' && test ! -L ' +
                   shlex.quote(artifact['path']))
        self.shell('command -v sha256sum && command -v mount && command -v umount && command -v findmnt && command -v nohup && command -v flock')
        return True

    def enable_guarded_boot(self):
        artifact = self.guarded_boot_artifact()
        hook = artifact['path']
        for name, content in (('boot-runtime.js', artifact['runtimeScript']), ('boot-profile.json', artifact['profileData'])):
            self.shell('umask 077; cat > ' + shlex.quote(self.directory + '/' + name), data=content)
        health = self.directory + '/boot-health.sh'
        self.shell('umask 077; cat > ' + shlex.quote(health + '.pending') +
                   ' && chmod 700 ' + shlex.quote(health + '.pending') +
                   ' && mv -n ' + shlex.quote(health + '.pending') + ' ' + shlex.quote(health),
                   data=artifact['healthScript'].encode())
        self.shell('sh -n ' + shlex.quote(health))
        self.shell('umask 077; cat > ' + shlex.quote(hook + '.pending') +
                   ' && chmod 700 ' + shlex.quote(hook + '.pending') +
                   ' && mv -n ' + shlex.quote(hook + '.pending') + ' ' + shlex.quote(hook),
                   data=artifact['script'].encode())
        self.shell('sh -n ' + shlex.quote(hook))
        actual = self.shell('sha256sum ' + shlex.quote(hook)).split()
        if not actual or actual[0] != artifact['sha256']:
            raise InstallerError('BOOT_HOOK_HASH_MISMATCH', 'The installed boot guard failed integrity verification.', 8)
        self.shell('umask 077; printf "0\\n" > ' + shlex.quote(self.directory + '/boot-failures') +
                   '; touch ' + shlex.quote(self.directory + '/boot-enabled'))
        return {'path': hook, 'sha256': artifact['sha256'], 'installed': True}

    def disable_guarded_boot(self, receipt):
        expected_path = BOOT_DIRECTORY + '/' + BOOT_PREFIX + self.plan['transactionId'][:16]
        artifact = receipt if receipt else self.guarded_boot_artifact()
        if (artifact.get('path') != expected_path or
                not re.fullmatch(r'[a-f0-9]{64}', artifact.get('sha256', ''))):
            raise InstallerError('BOOT_HOOK_OWNERSHIP_MISMATCH', 'The boot hook receipt is not owned by this transaction.', 8)
        self.shell('umask 077; touch ' + shlex.quote(self.directory + '/boot-disabled') +
                   '; rm -f ' + shlex.quote(self.directory + '/boot-enabled'))
        present = self.shell('if [ -e ' + shlex.quote(artifact['path']) + ' ]; then sha256sum ' +
                             shlex.quote(artifact['path']) + '; fi').split()
        if present:
            if present[0] != artifact['sha256']:
                raise InstallerError('BOOT_HOOK_MODIFIED', 'The boot hook was modified after installation.', 7)
            self.shell('rm -- ' + shlex.quote(artifact['path']))
        return {'disabled': True, 'removed': bool(present)}

    def reboot_identity(self):
        result = self.shell('cat /proc/sys/kernel/random/boot_id').strip()
        if not re.fullmatch(r'[a-f0-9-]{36}', result):
            raise InstallerError('BOOT_ID_UNAVAILABLE', 'The current boot identity is not available.', 6)
        return result

    def execute(self, operation):
        action = operation['action']
        if action == 'stage-immutable-payload':
            return self.stage_bundle()
        if action == 'arm-independent-watchdog':
            result = self.arm_watchdog(operation['seconds'])
            self.receipts['watchdog'] = result
            return result
        if action == 'bind-home-directory':
            if operation['target'] != self.stock_target:
                raise InstallerError('HOME_TARGET_CHANGED', 'The approved Home target changed.', 8)
            result = self.bind()
            self.receipts['mount'] = result
            return result
        if action == 'refresh-manifest':
            return self.refresh_manifest(self.sam_protocol)
        if action == 'verify-manager-manifest':
            return self.manager_manifest()
        if action == 'release-old-home':
            return self.close_stock_home()
        if action == 'launch-home':
            return self.launch_home()
        if action == 'enable-guarded-boot-hook':
            return self.enable_guarded_boot()
        if action == 'disarm-trial-watchdog':
            return self.stop_watchdog(self.receipts['watchdog'])
        raise InstallerError('HOME_OPERATION_UNIMPLEMENTED', 'This Home operation is not supported by the device executor.', 3)

    def integrity(self, plan):
        if plan != self.plan:
            raise InstallerError('HOME_PLAN_CHANGED', 'The approved Home plan has changed.', 8)
        for name, expected in self.bundle_manifest['files'].items():
            result = self.shell('sha256sum ' + shlex.quote(self.source + '/' + name))
            if not result.split() or result.split()[0] != expected:
                return False
        return True

    def ui_heartbeat(self):
        try:
            response = json.loads(self.shell('cat ' + shlex.quote(self.directory + '/ui-heartbeat.json')))
            uptime = float(self.shell('cat /proc/uptime').split()[0])
            return (response.get('transactionId') == self.plan['transactionId'] and
                    response.get('appId') == self.profile['home']['appId'] and
                    response.get('bootId') == self.reboot_identity() and
                    isinstance(response.get('uptime'), (float, int)) and
                    0 <= uptime - response['uptime'] <= 15 and response.get('uiReady') is True)
        except (ValueError, OSError, KeyError, IndexError, InstallerError):
            return False

    def health(self, plan):
        if plan != self.plan:
            raise InstallerError('HOME_PLAN_CHANGED', 'The approved Home plan has changed.', 8)
        result = {'H0': self.integrity(plan), 'H1': False, 'H2': False, 'H3': False, 'H4': False}
        try:
            self.shell(self.mount_command('check'))
            result['H1'] = True
            self.manager_manifest()
            result['H2'] = True
            result['H3'] = self.ui_heartbeat()
            response = self.transport.luna('luna://com.webos.applicationManager/getForegroundAppInfo', {})
            result['H4'] = self.physical_home_confirmed is True and response.get('returnValue') is True and (
                response.get('appId') == self.profile['home']['appId'] or
                response.get('foregroundAppId') == self.profile['home']['appId'])
        except Exception:
            pass
        return result

    def restore_owned(self, event, record):
        action = event['operation']['action']
        receipt = event.get('receipt', {})
        if action == 'enable-guarded-boot-hook':
            return self.disable_guarded_boot(receipt)
        if action == 'bind-home-directory':
            unmounted = self.restore_mount(receipt, allow_reboot=bool(record.get('bootIdBeforePersistence') and
                        self.reboot_identity() != record['bootIdBeforePersistence']))
            self.refresh_manifest(self.sam_protocol)
            self.launch_home()
            return unmounted
        if action in ('refresh-manifest', 'release-old-home'):
            return {'status': 'restoration-after-unmount'}
        if action == 'launch-home':
            return {'status': 'restoration-follows'}
        if action == 'arm-independent-watchdog':
            return self.stop_watchdog(receipt)
        if action in ('stage-immutable-payload', 'verify-manager-manifest'):
            return {'status': 'preserved-for-recovery'}
        raise InstallerError('HOME_ROLLBACK_UNIMPLEMENTED', 'The Home operation has no verified restoration path.', 6)

    def verify_stock_files(self, plan):
        if self.inspect_mounts():
            return False
        response = self.shell('sha256sum ' + shlex.quote(self.stock_target + '/appinfo.json'))
        return bool(response.split()) and response.split()[0] == self.profile['home']['stockManifestSha256']

    def verify_stock(self, plan):
        if not self.verify_stock_files(plan) or self.physical_stock_confirmed is not True:
            return False
        app_id = self.profile['home']['appId']
        try:
            response = self.transport.luna('luna://com.webos.applicationManager/getAppInfo', {'id': app_id})
            app = response.get('appInfo') or response.get('app') or {}
            if response.get('returnValue') is not True or app.get('id') != app_id or app.get('type') != self.profile['home']['implementation']:
                return False
            response = self.transport.luna('luna://com.webos.applicationManager/getAppLoadStatus', {'appId': app_id})
            if response.get('returnValue') is not True or response.get('isRunning') is False or not (
                    response.get('isRunning') is True or response.get('status') == 'running'):
                return False
            response = self.transport.luna('luna://com.webos.applicationManager/getForegroundAppInfo', {})
            return response.get('returnValue') is True and app_id in (response.get('appId'), response.get('foregroundAppId'))
        except Exception:
            return False

    def reboot_verified(self, plan):
        return False

    def verify_recovery_identity(self, record):
        if record.get('transactionId') != self.plan['transactionId'] or record.get('plan') != self.plan:
            raise InstallerError('RECOVERY_IDENTITY_CHANGED', 'The recovery transaction has changed.', 8)
        self.profile_check()
        return True

    def read_device_journal(self):
        output = self.shell('cat ' + shlex.quote(self.directory + '/journal.json'))
        try:
            record = json.loads(output)
        except ValueError as error:
            raise InstallerError('DEVICE_JOURNAL_INVALID', 'The remote journal is not valid JSON.', 6) from error
        self.verify_recovery_identity(record)
        return deepcopy(record)

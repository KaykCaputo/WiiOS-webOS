import hashlib
import json
import shlex

from compatibility.signatures import profile_digest
from home.operations.device_backend import DeviceHomeBackend
from home.standin import render_standin
from installer.errors import InstallerError


class NativeHomeBackend(DeviceHomeBackend):
    def __init__(self, transport, profile, plan, bundle_directory, bundle_manifest,
                 sam_contract, launch_payload, physical_home_confirmed=False):
        super().__init__(transport, profile, plan, bundle_directory, bundle_manifest,
                         None, physical_home_confirmed)
        self.native_contract = sam_contract
        self.launch_payload = launch_payload
        self.native_entrypoint = profile['home'].get('nativeEntrypoint')
        self.stock_target = self.native_entrypoint
        self.source = self.directory + '/standin.sh'
        self.native_payload = render_standin(profile['home']['appId'], launch_payload, sam_contract,
                                             self.directory + '/bundle/wam-launch.json')
        if not self.native_entrypoint or not self.native_entrypoint.startswith('/usr/palm/applications/com.webos.app.home/'):
            raise InstallerError('NATIVE_ENTRYPOINT_INVALID', 'An approved native Home entrypoint is required.', 3)

    def profile_check(self):
        if (self.transport.kind != 'root-ssh' or not self.profile['transport']['root'] or
                self.plan['adapter'] != 'native-home-standin' or
                self.profile['home']['implementation'] != 'native' or
                self.profile['home']['foreignMounts'] or self.profile['home']['conflictingHooks'] or
                self.profile['home']['namespaceVerified'] is not True or
                profile_digest(self.profile) != self.plan['deviceProfileDigest']):
            raise InstallerError('NATIVE_HOME_PROFILE_MISMATCH', 'Native Home replacement requires an exact qualified profile.', 8)

    def preflight(self, plan=None):
        if plan is not None and plan != self.plan:
            raise InstallerError('HOME_PLAN_CHANGED', 'The approved Home plan has changed.', 8)
        self.profile_check()
        if self.inspect_mounts():
            raise InstallerError('NATIVE_MOUNT_CONFLICT', 'A native Home mount already exists.', 7)
        actual = self.shell('sha256sum ' + shlex.quote(self.stock_target)).split()
        if not actual or actual[0] != self.profile['home']['nativeEntrypointSha256']:
            raise InstallerError('NATIVE_ENTRYPOINT_CHANGED', 'The original Home executable changed.', 8)
        self.shell('test -f ' + shlex.quote(self.stock_target) + ' && test ! -L ' + shlex.quote(self.stock_target))
        for binary in ('mount', 'umount', 'tar', 'sha256sum', 'nohup', 'sleep', 'findmnt', 'flock', 'luna-send', 'node'):
            self.shell('command -v ' + binary)
        self.shell("node -e 'if (parseInt(process.versions.node, 10) < 8) process.exit(3)'")

    def stage_bundle(self):
        old_source = self.source
        self.source = self.directory + '/bundle'
        try:
            super().stage_bundle()
        finally:
            self.source = old_source
        payload_path = self.directory + '/bundle/wam-launch.json'
        self.shell('umask 077; cat > ' + shlex.quote(payload_path),
                   data=self.native_payload['launchPayload'])
        self.shell('umask 077; cat > ' + shlex.quote(self.source) +
                   ' && chmod 700 ' + shlex.quote(self.source),
                   data=self.native_payload['script'])
        if self.shell('sha256sum ' + shlex.quote(self.source)).split()[0] != self.native_payload['sha256']:
            raise InstallerError('NATIVE_STANDIN_CHANGED', 'The staged native stand-in failed verification.', 8)
        self.shell('sh -n ' + shlex.quote(self.source))
        return {'staged': True, 'standinSha256': self.native_payload['sha256']}

    def integrity(self, plan):
        if plan != self.plan:
            raise InstallerError('HOME_PLAN_CHANGED', 'The approved Home plan has changed.', 8)
        for path, expected in ((self.source, self.native_payload['sha256']),
                               (self.directory + '/bundle/wam-launch.json', self.native_payload['launchSha256'])):
            actual = self.shell('sha256sum ' + shlex.quote(path)).split()
            if not actual or actual[0] != expected:
                return False
        return self.verify_staged_payload()

    def execute(self, operation):
        action = operation['action']
        if action in ('stage-immutable-payload', 'stage-home-standin'):
            return self.stage_bundle() if action == 'stage-immutable-payload' else {'staged': True}
        if action == 'verify-native-entrypoint':
            self.preflight()
            return {'originalVerified': True}
        if action == 'arm-independent-watchdog':
            result = self.arm_watchdog(operation['seconds'])
            self.receipts['watchdog'] = result
            return result
        if action == 'bind-native-standin-trial':
            if operation['target'] != self.stock_target:
                raise InstallerError('HOME_TARGET_CHANGED', 'The native entrypoint target changed.', 8)
            result = self.bind()
            self.receipts['mount'] = result
            return result
        if action == 'enable-guarded-boot-hook':
            return self.enable_guarded_boot()
        if action == 'disarm-trial-watchdog':
            return self.stop_watchdog(self.receipts['watchdog'])
        if action == 'release-old-home':
            return self.close_stock_home()
        if action == 'launch-home':
            return self.launch_home()
        if action == 'verify-native-home-lifecycle':
            runtime = self.native_runtime()
            if runtime.get('registered') is not True:
                raise InstallerError('NATIVE_STANDIN_NOT_REGISTERED', 'The native Home subscription is not registered.', 5)
            return {'processConfirmed': True, 'registrationConfirmed': True}
        raise InstallerError('NATIVE_OPERATION_UNIMPLEMENTED', 'This native Home operation is not qualified.', 3)

    def native_runtime(self):
        runtime = json.loads(self.shell('cat ' + shlex.quote(self.directory + '/native-runtime.json')))
        pid = runtime.get('pid')
        if not isinstance(pid, int) or not 1 <= pid <= 2147483647:
            raise InstallerError('NATIVE_RUNTIME_INVALID', 'The native runtime PID is invalid.', 5)
        command = self.shell('cat /proc/' + str(pid) + '/cmdline')
        if self.directory + '/bundle/wam-launch.json' not in command.split('\x00'):
            raise InstallerError('NATIVE_RUNTIME_CHANGED', 'The native runtime process identity changed.', 5)
        return runtime

    def manager_manifest(self, require_web=False):
        result = super().manager_manifest(require_web=False)
        if result.get('type') != 'native' or self.native_runtime().get('registered') is not True:
            raise InstallerError('NATIVE_RUNTIME_UNREGISTERED', 'The native lifecycle is not registered.', 5)
        return result

    def restore_owned(self, event, record):
        action = event['operation']['action']
        if action == 'enable-guarded-boot-hook':
            return self.disable_guarded_boot(event.get('receipt', {}))
        if action == 'bind-native-standin-trial':
            result = self.restore_mount(event.get('receipt', {}), allow_reboot=bool(
                record.get('bootIdBeforePersistence') and
                self.reboot_identity() != record['bootIdBeforePersistence']))
            self.shell('sh -s', data=self.stop_native_script().encode())
            self.launch_home()
            return result
        if action == 'release-old-home':
            return {'status': 'restoration-after-unmount'}
        if action == 'arm-independent-watchdog':
            return self.stop_watchdog(event.get('receipt', {}))
        if action in ('stage-immutable-payload', 'verify-native-entrypoint', 'stage-home-standin',
                      'launch-home', 'verify-native-home-lifecycle'):
            return {'status': 'preserved-for-recovery'}
        raise InstallerError('NATIVE_ROLLBACK_UNIMPLEMENTED', 'A native Home operation lacks a qualified restore.', 6)

    def verify_stock_files(self, plan):
        if self.inspect_mounts():
            return False
        actual = self.shell('sha256sum ' + shlex.quote(self.stock_target)).split()
        return bool(actual) and actual[0] == self.profile['home']['nativeEntrypointSha256']

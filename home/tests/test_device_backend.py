import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from compatibility.mountinfo import parse_mountinfo
from compatibility.signatures import profile_digest
from compatibility.tests.fixtures import profile
from home.operations.device_backend import DeviceHomeBackend
from installer.errors import InstallerError


class DeviceBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'index.html').write_text('hello')
        self.bundle = {'homeAppId': 'com.webos.app.home', 'stockManifestSha256': 'f' * 64,
                       'files': {'index.html': hashlib.sha256(b'hello').hexdigest()}}
        (self.root / 'wiios-home-bundle.json').write_text(json.dumps(self.bundle))
        self.profile = profile()
        self.profile['home'].update(appId='com.webos.app.home', implementation='web',
            effectiveDirectory='/usr/palm/applications/com.webos.app.home',
            stockManifestSha256='f' * 64, namespaceVerified=True)
        self.plan = {'transactionId': 'a' * 64, 'deviceProfileDigest': profile_digest(self.profile),
                     'adapter': 'home-directory-takeover'}
        self.connection = SimpleNamespace(kind='root-ssh', execute=Mock(return_value=''), luna=Mock())
        self.backend = DeviceHomeBackend(self.connection, self.profile, self.plan, self.root, self.bundle)

    def test_unrecognized_operations_fail_closed(self):
        for action in ('restart-sam', 'alter-stock-home', 'bind-native-standin-trial'):
            with self.assertRaises(InstallerError):
                self.backend.execute({'action': action})
        self.connection.execute.assert_not_called()

    def test_sam_refusal_always_attempts_release(self):
        self.backend.sam_protocol = 'sam-block-release-v1'
        self.profile['capabilities']['samManifestReload'] = 'available'
        self.connection.luna.side_effect = [{'returnValue': False}, {'returnValue': True}]
        with self.assertRaises(InstallerError):
            self.backend.execute({'action': 'refresh-manifest', 'target': '/usr/palm/applications/com.webos.app.home'})
        self.assertEqual(self.connection.luna.call_count, 2)
        self.assertTrue(self.connection.luna.call_args_list[1].args[0].endswith('/releaseBlockSystemApp'))

    def test_manager_mismatch_never_confirmed(self):
        self.connection.luna.return_value = {'returnValue': True, 'appInfo': {'id': 'com.webos.app.home', 'type': 'native'}}
        with self.assertRaises(InstallerError):
            self.backend.manager_manifest()

    def test_health_never_claims_physical_confirmation(self):
        self.backend.integrity = Mock(return_value=True)
        self.backend.inspect_mounts = Mock(return_value=[object()])
        self.backend.manager_manifest = Mock(return_value={'samConfirmed': True})
        self.connection.luna.return_value = {'returnValue': True, 'status': 'running', 'appId': 'com.webos.app.home'}
        health = self.backend.health(self.plan)
        self.assertFalse(health['H4'])
        self.assertTrue(health['H0'])
        self.assertTrue(health['H1'])
        self.backend.physical_home_confirmed = True
        self.assertTrue(self.backend.health(self.plan)['H4'])

    def test_stock_hash_alone_is_not_operational_confirmation(self):
        self.backend.inspect_mounts = Mock(return_value=[])
        self.connection.execute.return_value = 'f' * 64 + '  appinfo.json'
        self.assertTrue(self.backend.verify_stock_files(self.plan))
        self.assertFalse(self.backend.verify_stock(self.plan))
        self.connection.luna.assert_not_called()

    def test_staging_data_does_not_contain_unverified_files(self):
        self.connection.execute.return_value = hashlib.sha256(b'hello').hexdigest() + '  index.html'
        result = self.backend.stage_bundle()
        self.assertTrue(result['staged'])
        first = self.connection.execute.call_args_list[0]
        self.assertIn('tar -xz', first.args[0])
        self.assertGreater(len(first.kwargs['data']), 40)

    def test_remote_journal_must_match_plan(self):
        self.connection.execute.return_value = json.dumps({'transactionId': 'a' * 64, 'plan': self.plan})
        report = self.backend.read_device_journal()
        self.assertEqual(report['plan'], self.plan)
        self.connection.execute.return_value = json.dumps({'transactionId': 'b' * 64, 'plan': self.plan})
        with self.assertRaises(InstallerError):
            self.backend.read_device_journal()

    def test_persistence_accepts_receipt_after_device_journal_round_trip(self):
        for optional in ('', 'shared:8 master:1 '):
            with self.subTest(optional=optional):
                mount = parse_mountinfo('20 1 8:1 /owned ' + self.backend.stock_target +
                                        ' rw ' + optional + '- ext4 /dev/root rw')[0]
                self.backend.inspect_mounts = Mock(return_value=[mount])
                self.backend.integrity = Mock(return_value=True)
                self.backend.guarded_boot_artifact = Mock(return_value={'path': '/owned/hook'})
                record = json.loads(json.dumps({'state': 'LIVE_VERIFIED', 'events': [{
                    'operation': {'action': 'bind-home-directory'}, 'state': 'APPLIED',
                    'receipt': {'mount': mount.to_dict(), 'stagedSource': self.backend.source}}]}))
                self.assertTrue(self.backend.preflight_persistence(self.plan, record))
                record['events'][0]['receipt']['mount']['mountId'] += 1
                with self.assertRaises(InstallerError) as raised:
                    self.backend.preflight_persistence(self.plan, record)
                self.assertEqual(raised.exception.code, 'PERSISTENCE_MOUNT_CHANGED')

    def test_recovery_uses_original_hook_receipt_after_installer_update(self):
        from home.operations.guarded_boot import BOOT_DIRECTORY, BOOT_PREFIX
        path = BOOT_DIRECTORY + '/' + BOOT_PREFIX + self.plan['transactionId'][:16]
        receipt = {'path': path, 'sha256': 'a' * 64}
        self.backend.guarded_boot_artifact = Mock(side_effect=AssertionError('Must not regenerate an older hook'))
        self.connection.execute.side_effect = ['', 'a' * 64 + '  ' + path, '']
        self.assertTrue(self.backend.disable_guarded_boot(receipt)['removed'])
        self.backend.guarded_boot_artifact.assert_not_called()

    def test_recovery_never_removes_modified_or_foreign_hook(self):
        from home.operations.guarded_boot import BOOT_DIRECTORY, BOOT_PREFIX
        path = BOOT_DIRECTORY + '/' + BOOT_PREFIX + self.plan['transactionId'][:16]
        self.connection.execute.side_effect = ['', 'b' * 64 + '  ' + path]
        with self.assertRaises(InstallerError):
            self.backend.disable_guarded_boot({'path': path, 'sha256': 'a' * 64})
        self.assertFalse(any(call.args[0].startswith('rm --') for call in self.connection.execute.call_args_list))
        self.connection.execute.reset_mock()
        with self.assertRaises(InstallerError):
            self.backend.disable_guarded_boot({'path': '/other/launcher', 'sha256': 'a' * 64})
        self.connection.execute.assert_not_called()

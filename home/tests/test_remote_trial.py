import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from compatibility.tests.fixtures import profile
from compatibility.signatures import profile_digest
from home.operations.remote_trial import RemoteHomeTrial, validated_target, verified_archive
from installer.errors import InstallerError


class RemoteTrialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.bundle = self.directory / 'bundle'
        self.bundle.mkdir()
        (self.bundle / 'index.html').write_text('<html></html>')
        self.manifest = {'homeAppId': 'com.webos.app.home', 'stockManifestSha256': 'b' * 64,
                         'files': {'index.html': hashlib.sha256(b'<html></html>').hexdigest()}}
        (self.bundle / 'wiios-home-bundle.json').write_text(json.dumps(self.manifest))
        self.device = profile()
        self.device['home'].update(appId='com.webos.app.home', implementation='web',
            effectiveDirectory='/usr/palm/applications/com.webos.app.home', stockManifestSha256='b' * 64,
            namespaceVerified=True, foreignMounts=[], conflictingHooks=[])
        self.transport = SimpleNamespace(kind='root-ssh', execute=Mock())
        self.plan = {'transactionId': 'a' * 64, 'deviceProfileDigest': profile_digest(self.device),
                     'adapter': 'home-directory-takeover'}
        self.runner = RemoteHomeTrial(self.transport, self.device, self.plan, self.bundle, self.manifest)

    def test_archive_rejects_modified_or_extra_files(self):
        self.assertGreater(len(verified_archive(self.bundle, self.manifest)), 20)
        (self.bundle / 'index.html').write_text('modified')
        with self.assertRaises(InstallerError):
            verified_archive(self.bundle, self.manifest)
        (self.bundle / 'index.html').write_text('<html></html>')
        (self.bundle / 'unexpected.js').write_text('alert(1)')
        with self.assertRaises(InstallerError):
            verified_archive(self.bundle, self.manifest)

    def test_targets_reject_path_traversal(self):
        self.assertEqual(validated_target('/usr/palm/applications/com.webos.app.home'),
                         '/usr/palm/applications/com.webos.app.home')
        for path in ('/etc/passwd', '/usr/palm/applications/com.webos.app.home/../../etc',
                     '/usr/palm/applications/com.webos.app.home;touch /tmp/x'):
            with self.assertRaises(InstallerError):
                validated_target(path)

    def test_wrong_platform_and_foreign_mounts_are_blocked(self):
        self.runner.profile_check()
        self.transport.kind = 'developer-mode'
        with self.assertRaises(InstallerError):
            self.runner.profile_check()
        self.transport.kind = 'root-ssh'
        self.device['home']['foreignMounts'].append('/tmp/untrusted')
        with self.assertRaises(InstallerError):
            self.runner.profile_check()

    def test_watchdog_self_test_precedes_arming(self):
        seen = []
        def remote(command, data=None, timeout=25):
            seen.append((command, data))
            if command.startswith('sha256sum '):
                return hashlib.sha256(Path('home/operations/owned_mount.sh').read_bytes()).hexdigest() + '  executor'
            if command.startswith('findmnt '):
                return ''
            if 'echo $!' in command:
                return '123\n'
            return ''
        self.transport.execute.side_effect = remote
        result = self.runner.arm_watchdog(90)
        self.assertTrue(result['recoverySelfTestPassed'])
        commands = [command for command, _ in seen]
        self.assertLess(next(i for i, c in enumerate(commands) if 'owned-mount.sh bind ' in c),
                        next(i for i, c in enumerate(commands) if c.startswith('nohup ')))
        self.assertTrue(any('findmnt -n -o SOURCE -M' in c for c in commands))
        self.assertIn('owned-mount.sh restore ', self.runner.recovery_script())

    def test_mismatched_mount_receipt_never_unmounts(self):
        self.runner.inspect_mounts = Mock(return_value=[])
        with self.assertRaises(InstallerError):
            self.runner.restore_mount({'stagedSource': '/other'})
        self.transport.execute.assert_not_called()

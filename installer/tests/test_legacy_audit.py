import json
from importlib.resources import files
from pathlib import Path
import unittest

from home.operations.legacy_audit import audit_legacy_recovery
from installer.errors import InstallerError


class ReadOnlyLegacyDevice:
    kind = 'root-ssh'

    def __init__(self):
        self.metadata = json.loads(files('home.operations').joinpath('legacy-recovery.json').read_text())
        self.commands = []
        self.corrupt = False
        self.same_boot = True
        self.receipts = True

    def execute(self, command, timeout=20):
        self.commands.append(command)
        if command == 'id -u':
            return '0\n'
        if command == 'readlink /proc/self/ns/mnt':
            return 'mnt:[1]\n'
        if command.startswith('test -f '):
            if not self.receipts:
                raise InstallerError('TRANSPORT_FAILED', 'Missing journal receipts', 4)
            return ''
        raise AssertionError('Unexpected or mutating command: ' + command)

    def read(self, path):
        self.commands.append('read:' + path)
        if path == self.metadata['base'] + '/state/status':
            return 'ACTIVE\n'
        if path == self.metadata['base'] + '/state/namespace':
            return 'mnt:[1]\n'
        if path == self.metadata['base'] + '/state/boot-id':
            return 'boot-known\n'
        if path == '/proc/sys/kernel/random/boot_id':
            return 'boot-known\n' if self.same_boot else 'boot-other\n'
        name = Path(path).name
        if name in self.metadata['files']:
            data = (Path(__file__).resolve().parents[2] / 'fullhome-integration' / 'bundle' / name).read_text()
            return data + 'modified' if self.corrupt and name == 'rollback.sh' else data
        raise AssertionError('Unexpected path: ' + path)


def installed_profile():
    return {'home': {'appId': 'com.webos.app.fullhome', 'implementation': 'qml',
                     'ownershipStatus': 'VERIFIED', 'namespaceVerified': True,
                     'ownedMounts': [{}, {}, {}, {}], 'foreignMounts': [],
                     'conflictingHooks': [], 'recognizedHooks': ['99-wiios-fullhome']},
            'wiiOsInstallation': {'homeAdapter': 'qml-redirect', 'transactionId': 'diag-3e891511b377'}}


class ReadOnlyRecoveryTests(unittest.TestCase):
    def test_healthy_preflight_reads_without_modifying_tv(self):
        device = ReadOnlyLegacyDevice()
        result = audit_legacy_recovery(device, installed_profile())
        self.assertTrue(result['ok'])
        self.assertEqual(result['assessment'], 'PRECHECK_PASSED')
        self.assertFalse(result['independentRecoveryRehearsed'])
        self.assertFalse(result['recoveryQualified'])
        self.assertEqual(result['mode'], 'READ_ONLY')
        self.assertTrue(all(command in ('id -u', 'readlink /proc/self/ns/mnt') or
                            command.startswith(('read:', 'test -f ')) for command in device.commands))

    def test_modified_rollback_is_blocked(self):
        device = ReadOnlyLegacyDevice()
        device.corrupt = True
        result = audit_legacy_recovery(device, installed_profile())
        self.assertFalse(result['ok'])
        self.assertIn('rollback.sh', result['mismatchedRecoveryFiles'])

    def test_boot_mismatch_blocks_precheck(self):
        device = ReadOnlyLegacyDevice()
        device.same_boot = False
        self.assertFalse(audit_legacy_recovery(device, installed_profile())['checks']['sameBootIdentity'])

    def test_missing_receipts_blocks_precheck(self):
        device = ReadOnlyLegacyDevice()
        device.receipts = False
        self.assertEqual(audit_legacy_recovery(device, installed_profile())['assessment'], 'PRECHECK_BLOCKED')

    def test_unknown_home_fails_closed(self):
        device = ReadOnlyLegacyDevice()
        values = installed_profile()
        values['home']['ownershipStatus'] = 'UNVERIFIED'
        self.assertFalse(audit_legacy_recovery(device, values)['ok'])

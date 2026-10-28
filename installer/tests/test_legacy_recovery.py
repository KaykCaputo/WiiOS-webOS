import unittest

from home.operations.legacy_recovery import restore_legacy
from legacy_fixture import RECOVERY_FILES, patch_recovery_metadata
from installer.errors import InstallerError


class LegacyDevice:
    kind = 'root-ssh'

    def __init__(self):
        self.commands = []
        self.status = 'ACTIVE'
        self.corrupt = False

    def read(self, path):
        if path.endswith('/state/status'):
            return self.status
        if self.corrupt:
            return 'unrecognized recovery payload'
        return RECOVERY_FILES[path.rsplit('/', 1)[-1]]

    def execute(self, command, timeout=20):
        self.commands.append(command)
        if command == 'id -u':
            return '0'
        if '/rollback.sh' in command:
            self.status = 'RESTORED'
        return ''


class LegacyRecoveryTests(unittest.TestCase):
    def setUp(self):
        patch_recovery_metadata(self, 'home.operations.legacy_recovery')

    def test_recovery_checks_existing_scripts_before_disabling_hook_and_restoring(self):
        device = LegacyDevice()
        result = restore_legacy(device, 'diag-3e891511b377')
        self.assertEqual(result['state'], 'LG_HOME_FILES_RESTORED')
        self.assertFalse(result['homeConfirmed'])
        self.assertIn('disable-startup.sh', device.commands[1])
        self.assertIn('rollback.sh', device.commands[2])

    def test_unknown_scripts_never_execute(self):
        device = LegacyDevice()
        device.corrupt = True
        with self.assertRaises(InstallerError):
            restore_legacy(device, 'diag-3e891511b377')
        self.assertEqual(device.commands, ['id -u'])

    def test_unknown_transaction_refused_before_connection(self):
        device = LegacyDevice()
        with self.assertRaises(InstallerError):
            restore_legacy(device, 'other-transaction')
        self.assertEqual(device.commands, [])

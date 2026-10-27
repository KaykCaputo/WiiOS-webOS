from types import SimpleNamespace
import unittest

from compatibility.probe import probe
from installer.errors import InstallerError


class ReadOnlyDevice:
    kind = 'developer-mode'
    connection = SimpleNamespace(endpoint='prisoner@192.0.2.1:9922')

    def __init__(self):
        self.commands = []

    def fingerprint(self):
        return 'SHA256:synthetic'

    def execute(self, command):
        self.commands.append(command)
        return {'id -u': '1000', 'uname -m': 'armv7l', 'command -v luna-send-pub': '/usr/bin/luna-send-pub'}[command]

    def read(self, path):
        self.commands.append('read:' + path)
        raise InstallerError('NOT_FOUND', 'Synthetic missing path.', 4)

    def luna(self, uri, payload):
        self.commands.append(uri)
        if uri.endswith('/getSystemInfo'):
            return {'returnValue': True, 'modelName': 'SYNTHETIC_MODEL', 'firmwareVersion': 'TEST_ONLY', 'serialNumber': 'MUST_NOT_EXPORT'}
        return {'returnValue': False, 'errorText': 'Access denied'}


class ProbeTests(unittest.TestCase):
    def test_ht01_probe_without_root_is_read_only_and_redacted(self):
        device = ReadOnlyDevice()
        result = probe(device)
        self.assertFalse(result['transport']['root'])
        self.assertIsNone(result['wiiOsInstallation']['appInstalled'])
        self.assertEqual(result['capabilities']['lunaApplicationListing'], 'unavailable')
        self.assertEqual(result['capabilities']['lunaApplicationLaunch'], 'unknown')
        self.assertNotIn('MUST_NOT_EXPORT', str(result))
        self.assertFalse(any(word in command for command in device.commands for word in ('mount ', 'mkdir', 'registerApp', '/launch', '/install')))

    def test_developer_mode_unexpected_root_is_refused(self):
        device = ReadOnlyDevice()
        execute = device.execute
        device.execute = lambda command: '0' if command == 'id -u' else execute(command)
        with self.assertRaises(InstallerError):
            probe(device)

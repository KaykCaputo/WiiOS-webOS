from contextlib import redirect_stdout
import io
import tempfile
import unittest

from installer.application import ApplicationInstaller, Artifact
from installer.errors import InstallerError
from scripts.build import build


class PackageDevice:
    kind = 'developer-mode'

    def __init__(self, artifact, complete=True):
        self.artifact, self.complete = artifact, complete
        self.installed = None
        self.commands = []

    def execute(self, command, data=None, timeout=20):
        self.commands.append(command)
        if command.startswith('if [ -f'):
            return '{"id":"com.wiios.launcher","version":"' + self.installed + '"}' if self.installed else 'ABSENT'
        if command.startswith('sha256sum'):
            return self.artifact.digest + '  application.ipk'
        return ''

    def luna(self, uri, payload):
        self.commands.append(uri)
        if self.complete:
            self.installed = None if uri.endswith('/remove') else self.artifact.version
        return {'returnValue': True}


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        with redirect_stdout(io.StringIO()):
            cls.artifact = Artifact(build(output=cls.directory.name))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_ht19_developer_install_has_no_root_home_or_privacy_mutations(self):
        device = PackageDevice(self.artifact)
        result = ApplicationInstaller(device, sleep=lambda seconds: None).install(self.artifact, 'a' * 64)
        self.assertEqual(result['state'], 'APP_INSTALLED')
        self.assertFalse(result['uiConfirmed'])
        self.assertFalse(any(word in command for command in device.commands for word in ('webosbrew', 'mount ', '/etc/hosts', 'metrics', 'init.d')))

    def test_ht22_same_version_reinstall_is_idempotent(self):
        device = PackageDevice(self.artifact)
        device.installed = self.artifact.version
        result = ApplicationInstaller(device).install(self.artifact, 'a' * 64)
        self.assertFalse(result['changed'])
        self.assertFalse(any('/dev/install' in command for command in device.commands))

    def test_service_acceptance_does_not_confirm_install(self):
        device = PackageDevice(self.artifact, complete=False)
        with self.assertRaises(InstallerError) as raised:
            ApplicationInstaller(device, sleep=lambda seconds: None).install(self.artifact, 'a' * 64)
        self.assertEqual(raised.exception.code, 'APP_INSTALL_UNCONFIRMED')

    def test_application_removal_checks_absence(self):
        device = PackageDevice(self.artifact)
        device.installed = self.artifact.version
        result = ApplicationInstaller(device).uninstall()
        self.assertEqual(result['state'], 'APP_ABSENT')

import json
from types import SimpleNamespace
import unittest

from compatibility.discovery import choose_home, classify_home, sam_registration
from compatibility.probe import probe
from compatibility.resolver import resolve
from compatibility.schema import validate_document
from installer.errors import InstallerError


class RootReadOnlyDevice:
    kind = 'root-ssh'
    connection = SimpleNamespace(endpoint='root@192.0.2.2:22')

    def __init__(self, manifests=None, sam=None, running=None):
        self.commands = []
        self.manifests = manifests or {}
        self.sam = sam or {}
        self.running = running or []

    def fingerprint(self):
        return 'SHA256:synthetic'

    def execute(self, command):
        self.commands.append(command)
        if command == 'id -u':
            return '0'
        if command == 'uname -m':
            return 'armv7l'
        if command == 'command -v luna-send':
            return '/usr/bin/luna-send'
        if command == 'readlink /proc/self/ns/mnt':
            return 'mnt:[1]'
        if command.startswith('for name in sam WebAppMgr;'):
            return 'sam mnt:[1]\nWebAppMgr mnt:[1]'
        if command.startswith('if [ -d /var/lib/webosbrew/init.d ]'):
            return ''
        if command.startswith('sha256sum '):
            raise InstallerError('NOT_FOUND', 'No QML candidate.', 4)
        raise AssertionError(command)

    def read(self, path):
        self.commands.append('read:' + path)
        if path == '/proc/self/mountinfo':
            return '24 0 0:21 / / rw - tmpfs tmpfs rw\n'
        app = path.rsplit('/', 1)[0].rsplit('/', 1)[-1]
        if app in self.manifests and path.endswith('/appinfo.json'):
            return json.dumps(self.manifests[app])
        raise InstallerError('NOT_FOUND', 'Missing path.', 4)

    def luna(self, uri, payload):
        self.commands.append(uri)
        if uri.endswith('/getSystemInfo'):
            return {'returnValue': True, 'modelName': 'SIMULATED', 'sdkVersion': '10.3.1',
                    'firmwareVersion': 'SIM-1', 'serialNumber': 'PRIVATE'}
        if uri.endswith('/status'):
            return {'returnValue': True, 'status': {'apps': []}}
        if uri.endswith('/listLaunchPoints'):
            return {'returnValue': True, 'launchPoints': []}
        if uri.endswith('/running'):
            return {'returnValue': True, 'running': [{'id': item} for item in self.running]}
        if uri.endswith('/getAppInfo'):
            return self.sam.get(payload['id'], {'returnValue': False})
        raise AssertionError(uri)


def manifest(app_id, kind, categories=None):
    return {'id': app_id, 'type': kind, 'main': 'index.html',
            'appCategory': categories if categories is not None else []}


def registered(app_id, kind, categories=None):
    return {'returnValue': True, 'appInfo': manifest(app_id, kind, categories)}


class DiscoveryTests(unittest.TestCase):
    def test_identifies_unique_sam_home_when_not_running(self):
        app_id = 'com.webos.app.home'
        device = RootReadOnlyDevice({app_id: manifest(app_id, 'flutter', ['home'])},
                                   {app_id: registered(app_id, 'flutter', ['home'])})
        result = probe(device)
        validate_document(result, 'device-profile')
        self.assertEqual(result['home']['appId'], app_id)
        self.assertEqual(result['home']['implementation'], 'flutter')
        self.assertEqual(result['home']['selectionEvidence'], 'unique-sam-home-role')
        self.assertTrue(result['home']['namespaceVerified'])
        self.assertEqual(result['capabilities']['ipkInstall'], 'available')
        self.assertEqual(resolve(result)['homeStatus'], 'HOME_EXPERIMENTAL')
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertFalse(any('mount --bind' in cmd or '/dev/install' in cmd or 'mkdir ' in cmd
                             for cmd in device.commands))

    def test_ambiguity_disables_home_takeover(self):
        ids = ('com.webos.app.home', 'com.webos.app.fullhome')
        manifests = {app_id: manifest(app_id, 'web', ['home']) for app_id in ids}
        sam = {app_id: registered(app_id, 'web', ['home']) for app_id in ids}
        result = probe(RootReadOnlyDevice(manifests, sam))
        self.assertIsNone(result['home']['appId'])
        self.assertEqual(result['home']['selectionEvidence'], 'ambiguous-sam-home-role')
        self.assertEqual(resolve(result)['selectedMode'], 'app-only')
        self.assertIn('HOME_ACTIVE_ID_UNCONFIRMED', resolve(result)['reasonCodes'])

    def test_sam_type_mismatch_blocks_qualification(self):
        app_id = 'com.webos.app.home'
        result = probe(RootReadOnlyDevice({app_id: manifest(app_id, 'web', ['home'])},
                                         {app_id: registered(app_id, 'native', ['home'])}))
        self.assertTrue(result['home']['candidates'][0]['samTypeMismatch'])
        self.assertEqual(resolve(result)['reasonCodes'], ['HOME_SAM_MANIFEST_MISMATCH'])
        self.assertEqual(resolve(result)['homeStatus'], 'CONFLICT')

    def test_sam_must_confirm_the_same_app_id(self):
        result = sam_registration('com.webos.app.home', registered('com.webos.app.other', 'web', ['home']))
        self.assertFalse(result['registered'])

    def test_native_executable_fallback(self):
        self.assertEqual(classify_home('com.webos.app.home', {'main': '/usr/bin/com.webos.app.home'}, {}),
                         ('native', 'native-executable-path'))
        self.assertEqual(classify_home('com.webos.app.home', {'main': 'index.html'}, {}),
                         ('unknown', 'unrecognized-manifest'))

    def test_running_home_requires_sam_registration(self):
        candidate = {'appId': 'com.webos.app.home', 'sam': {'registered': False, 'homeRole': False}}
        self.assertEqual(choose_home([candidate], ['com.webos.app.home'])[0], None)

    def test_stock_home_candidate_not_in_sam_stays_app_only(self):
        app_id = 'com.webos.app.home'
        result = probe(RootReadOnlyDevice({app_id: manifest(app_id, 'web')}))
        self.assertEqual(result['home']['selectionEvidence'], 'home-unregistered')
        self.assertIsNone(result['home']['appId'])
        self.assertTrue(result['home']['namespaceVerified'])
        self.assertEqual(resolve(result)['selectedMode'], 'app-only')


if __name__ == '__main__':
    unittest.main()

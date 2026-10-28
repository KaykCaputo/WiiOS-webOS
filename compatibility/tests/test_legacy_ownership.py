from hashlib import sha256
from importlib.resources import files
import json
from types import SimpleNamespace
import unittest

from compatibility.legacy import BASE, HOOK, SOURCES, TARGETS, inspect_legacy
from compatibility.mountinfo import parse_mountinfo
from compatibility.probe import probe
from compatibility.resolver import resolve


class LegacyDevice:
    kind = 'root-ssh'
    connection = SimpleNamespace(endpoint='root@192.0.2.44:22')

    def __init__(self):
        metadata = json.loads(files('home.operations').joinpath('legacy-recovery.json').read_text())
        bundle = files('home.operations').joinpath('legacy-recovery.json')
        self.values = {}
        for name in metadata['files']:
            if name == HOOK:
                source = bundle.parent.parent.joinpath('..', 'fullhome-integration', 'bundle', name)
            else:
                source = bundle.parent.parent.joinpath('..', 'fullhome-integration', 'bundle', name)
            self.values[BASE + '/' + name] = source.read_text()
        self.values['/var/lib/webosbrew/init.d/' + HOOK] = self.values[BASE + '/' + HOOK]
        self.values[BASE + '/state/status'] = 'ACTIVE\n'
        self.values[BASE + '/state/namespace'] = 'mnt:[1]\n'
        self.values[BASE + '/state/boot-id'] = 'boot-synthetic\n'
        self.values['/proc/sys/kernel/random/boot_id'] = 'boot-synthetic\n'
        self.mount_lines = []
        for index, (source, target) in enumerate(zip(SOURCES, TARGETS), start=1):
            state = BASE + '/state/' + str(index)
            row = f'{100+index} 2 8:1 /synthetic/{index} {target} ro - ext4 /dev/mock rw\n'
            self.mount_lines.append(row)
            self.values[state + '.source'] = source + '\n'
            self.values[state + '.target'] = target + '\n'
            self.values[state + '.intent'] = 'ready\n'
            self.values[state + '.owned'] = row
            self.values[state + '.before'] = ''
            self.values[state + '.coordinates'] = f'8:1 /synthetic/{index}\n'
            self.values[state + '.inode'] = f'1:{index}\n'
        self.values['/proc/self/mountinfo'] = ''.join(self.mount_lines)
        self.values['/usr/palm/applications/com.webos.app.fullhome/appinfo.json'] = json.dumps(
            {'id': 'com.webos.app.fullhome', 'type': 'native', 'main': '/usr/bin/home'})
        self.values['/usr/palm/applications/com.webos.app.home/appinfo.json'] = ''
        self.commands = []

    def fingerprint(self):
        return 'SHA256:synthetic'

    def read(self, path):
        self.commands.append('read:' + path)
        if path not in self.values or path.endswith('/com.webos.app.home/appinfo.json'):
            raise ValueError('Unknown path')
        return self.values[path]

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
            return 'sam mnt:[1]\nWebAppMgr mnt:[1]\n'
        if command.startswith('if [ -d /var/lib/webosbrew/init.d ]'):
            return HOOK + '\n'
        if command.startswith("stat -c '%d:%i' -- "):
            for index, (source, target) in enumerate(zip(SOURCES, TARGETS), start=1):
                if command.endswith(source) or command.endswith(target):
                    return '1:' + str(index)
        if command.startswith('sha256sum '):
            return sha256(command.encode()).hexdigest() + '  file'
        raise ValueError('Unexpected command: ' + command)

    def luna(self, uri, payload):
        self.commands.append(uri)
        if uri.endswith('getSystemInfo'):
            return {'returnValue': True, 'modelName': 'SIMULATED', 'sdkVersion': '4.5',
                    'firmwareVersion': 'TEST', 'boardType': 'SIMULATED_BOARD'}
        if uri.endswith('getAppInfo'):
            return {'returnValue': True, 'appInfo': {'id': payload['id'], 'type': 'native',
                                                    'appCategory': ['home']}}
        if uri.endswith('running'):
            return {'returnValue': True, 'running': [{'id': 'com.webos.app.fullhome'}]}
        return {'returnValue': True}


class LegacyOwnershipTests(unittest.TestCase):
    def test_verified_legacy_mounts_are_owned_not_foreign(self):
        device = LegacyDevice()
        report = inspect_legacy(device, parse_mountinfo(device.values['/proc/self/mountinfo']), 'mnt:[1]', [HOOK])
        self.assertEqual(report['status'], 'VERIFIED')
        self.assertEqual(len(report['ownedMounts']), 4)
        self.assertEqual(report['recognizedHooks'], [HOOK])
        result = probe(device)
        self.assertEqual(result['home']['ownershipStatus'], 'VERIFIED')
        self.assertEqual(result['home']['foreignMounts'], [])
        self.assertEqual(result['home']['conflictingHooks'], [])
        self.assertEqual(result['wiiOsInstallation']['homeAdapter'], 'qml-redirect')
        status = resolve(result)
        self.assertEqual(status['homeStatus'], 'HOME_INSTALLED')
        self.assertEqual(status['selectedMode'], 'home-replacement')

    def test_foreign_stacked_mount_never_becomes_owned(self):
        device = LegacyDevice()
        device.values['/proc/self/mountinfo'] += (
            '300 2 8:1 /foreign ' + TARGETS[0] + ' ro - ext4 /dev/mock rw\n')
        result = probe(device)
        self.assertEqual(result['home']['ownershipStatus'], 'UNVERIFIED')
        self.assertTrue(result['home']['foreignMounts'])
        self.assertEqual(resolve(result)['homeStatus'], 'CONFLICT')
        self.assertEqual(resolve(result)['reasonCodes'], ['HOME_OWNERSHIP_UNVERIFIED'])

    def test_modified_hook_is_not_trusted(self):
        device = LegacyDevice()
        device.values['/var/lib/webosbrew/init.d/' + HOOK] += 'modified\n'
        result = probe(device)
        self.assertEqual(result['home']['ownershipStatus'], 'UNVERIFIED')
        self.assertEqual(result['home']['recognizedHooks'], [])
        self.assertIn(HOOK, result['home']['conflictingHooks'])

    def test_stale_boot_identifier_blocks_ownership(self):
        device = LegacyDevice()
        device.values[BASE + '/state/boot-id'] = 'old-boot\n'
        result = probe(device)
        self.assertEqual(result['home']['ownershipStatus'], 'UNVERIFIED')
        self.assertEqual(resolve(result)['homeStatus'], 'CONFLICT')
        self.assertEqual(resolve(result)['reasonCodes'], ['HOME_OWNERSHIP_UNVERIFIED'])

    def test_verified_privacy_hook_is_not_home_conflict(self):
        device = LegacyDevice()
        from compatibility.legacy import PRIVACY_HOOK
        source = files('home.operations').joinpath('legacy-recovery.json').parent.parent.joinpath(
            '..', 'privacy', PRIVACY_HOOK)
        device.values['/var/lib/webosbrew/init.d/' + PRIVACY_HOOK] = source.read_text()
        original = device.execute
        def execute(command):
            if command.startswith('if [ -d /var/lib/webosbrew/init.d ]'):
                return HOOK + '\n' + PRIVACY_HOOK + '\n'
            return original(command)
        device.execute = execute
        result = probe(device)
        self.assertIn(PRIVACY_HOOK, result['home']['recognizedHooks'])
        self.assertEqual(result['home']['conflictingHooks'], [])
        self.assertEqual(resolve(result)['homeStatus'], 'HOME_INSTALLED')

    def test_verified_qml_ownership_resolves_ambiguous_sam_and_metrics_hook(self):
        device = LegacyDevice()
        from compatibility.legacy import METRICS_HOOK
        device.values['/var/lib/webosbrew/init.d/' + METRICS_HOOK] = (
            '#!/bin/sh\nexec sh /var/lib/webosbrew/wiios-metrics/control.sh start\n')
        home_manifest = json.dumps({'id': 'com.webos.app.home', 'type': 'native', 'main': '/usr/bin/home'})
        original_read, original_execute = device.read, device.execute
        def read(path):
            if path == '/usr/palm/applications/com.webos.app.home/appinfo.json':
                return home_manifest
            return original_read(path)
        def execute(command):
            if command.startswith('if [ -d /var/lib/webosbrew/init.d ]'):
                return HOOK + '\n' + METRICS_HOOK + '\n'
            return original_execute(command)
        device.read, device.execute = read, execute
        result = probe(device)
        self.assertEqual(result['home']['ownershipStatus'], 'VERIFIED')
        self.assertEqual(result['home']['appId'], 'com.webos.app.fullhome')
        self.assertEqual(result['home']['implementation'], 'qml')
        self.assertEqual(result['home']['selectionEvidence'], 'verified-wiios-qml-ownership')
        self.assertTrue(result['home']['namespaceVerified'])
        self.assertIn(METRICS_HOOK, result['home']['recognizedHooks'])
        self.assertEqual(result['home']['conflictingHooks'], [])
        self.assertEqual(resolve(result)['homeStatus'], 'HOME_INSTALLED')

    def test_modified_metrics_hook_still_blocks_home(self):
        device = LegacyDevice()
        from compatibility.legacy import METRICS_HOOK
        device.values['/var/lib/webosbrew/init.d/' + METRICS_HOOK] = (
            '#!/bin/sh\nexec sh /var/lib/webosbrew/wiios-metrics/control.sh start\nextra\n')
        original_execute = device.execute
        def execute(command):
            if command.startswith('if [ -d /var/lib/webosbrew/init.d ]'):
                return HOOK + '\n' + METRICS_HOOK + '\n'
            return original_execute(command)
        device.execute = execute
        result = probe(device)
        self.assertNotIn(METRICS_HOOK, result['home']['recognizedHooks'])
        self.assertEqual(result['home']['conflictingHooks'], [METRICS_HOOK])
        self.assertEqual(resolve(result)['homeStatus'], 'CONFLICT')

    def test_unrecognized_startup_hook_still_blocks(self):
        device = LegacyDevice()
        original = device.execute
        def execute(command):
            if command.startswith('if [ -d /var/lib/webosbrew/init.d ]'):
                return HOOK + '\n' + '99-another-home-replacement' + '\n'
            return original(command)
        device.execute = execute
        result = probe(device)
        self.assertEqual(result['home']['ownershipStatus'], 'VERIFIED')
        self.assertEqual(result['home']['conflictingHooks'], ['99-another-home-replacement'])
        self.assertEqual(resolve(result)['homeStatus'], 'CONFLICT')

    def test_readonly_inspection_never_changes_remote_mounts(self):
        device = LegacyDevice()
        probe(device)
        self.assertFalse(any(cmd.startswith(('mount ', 'umount ', 'rm ', 'mkdir ', 'mv '))
                             for cmd in device.commands))


if __name__ == '__main__':
    unittest.main()

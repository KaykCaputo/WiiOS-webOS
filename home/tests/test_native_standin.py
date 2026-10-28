import subprocess
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from home.standin import render_standin
from installer.errors import InstallerError


class NativeStandinTests(unittest.TestCase):
    def test_renders_valid_shell_and_fixed_sam_contract(self):
        payload = {'id': 'com.webos.app.home'}
        result = render_standin('com.webos.app.home', payload, 'register-native-app-v1',
                                '/var/lib/wiios/home-transactions/' + 'a' * 64 + '/bundle/wam-launch.json')
        self.assertEqual(subprocess.run(['sh', '-n'], input=result['script'], capture_output=True).returncode, 0)
        self.assertIn(b'registerNativeApp', result['script'])
        self.assertTrue(result['script'].rstrip().endswith(b'register-native-app-v1'))
        self.assertIn(b'launchApp', result['script'])

    def test_untrusted_launch_payload_and_path_are_rejected(self):
        for payload in ({'id': 'com.webos.app.other'}, {'appId': 'com.webos.app.other'}):
            with self.assertRaises(InstallerError):
                render_standin('com.webos.app.home', payload, 'register-app-v2',
                                '/var/lib/wiios/home-transactions/' + 'a' * 64 + '/bundle/wam-launch.json')
        with self.assertRaises(InstallerError):
            render_standin('com.webos.app.home', {'id': 'com.webos.app.home'}, 'untrusted-contract',
                            '/var/lib/wiios/home-transactions/' + 'a' * 64 + '/bundle/wam-launch.json')


class NativeLifecycleExecutionTests(unittest.TestCase):
    def execute_lifecycle(self, event, contract='register-native-app-v1'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'bundle'
            bundle.mkdir()
            payload = bundle / 'wam-launch.json'
            payload.write_text('{"id":"com.webos.app.home"}')
            stub = root / 'luna-send'
            stub.write_text('#!' + sys.executable + '\n' +
                'import json, os, sys, time\n'
                'if "launchApp" in " ".join(sys.argv):\n'
                '    print(json.dumps({"returnValue": True}))\n'
                'else:\n'
                '    event = os.environ["FAKE_EVENT"]\n'
                '    field = os.environ["FAKE_FIELD"]\n'
                '    if event != "timeout":\n'
                '        print(json.dumps({"returnValue": event != "rejected", field: event}), flush=True)\n'
                '    if event != "eof": time.sleep(15 if event == "timeout" else 2)\n')
            stub.chmod(0o700)
            script = Path('home/native_lifecycle.js').read_text()
            result = subprocess.run(['node', '-e', script, 'com.webos.app.home', str(payload), contract],
                env=dict(os.environ, PATH=directory + os.pathsep + os.environ['PATH'], FAKE_EVENT=event,
                         FAKE_FIELD='event' if contract == 'register-app-v2' else 'message'),
                capture_output=True, timeout=11)
            runtime = json.loads((root / 'native-runtime.json').read_text())
            return result.returncode, runtime

    def test_close_and_stop_exit_the_parent(self):
        for contract in ('register-native-app-v1', 'register-app-v2'):
            for event in ('close', 'stop'):
                with self.subTest(contract=contract, event=event):
                    code, runtime = self.execute_lifecycle(event, contract)
                    self.assertEqual(code, 0)
                    self.assertEqual(runtime['state'], 'EXITED')
                    self.assertFalse(runtime['registered'])

    def test_rejection_subscription_loss_and_timeout_fail(self):
        for event in ('rejected', 'eof', 'timeout'):
            with self.subTest(event=event):
                code, runtime = self.execute_lifecycle(event)
                self.assertNotEqual(code, 0)
                self.assertEqual(runtime['state'], 'FAILED')

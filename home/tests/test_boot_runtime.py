import json
from pathlib import Path
import subprocess
import unittest

from compatibility.tests.fixtures import profile


class BootRuntimeTests(unittest.TestCase):
    def execute(self, running=None, firmware='TEST_ONLY', heartbeat=True, namespace='mnt:[1]', action='health', foreground='com.webos.app.home', heartbeat_uptime=30, previous=None):
        fixture = {'identity': profile()['identity'], 'transactionId': 'a' * 64,
                   'appId': 'com.webos.app.home', 'native': False,
                   'samProtocol': 'sam-block-release-v1', 'main': 'index.html'}
        payload = {'config': fixture, 'firmware': firmware, 'namespace': namespace, 'heartbeat': heartbeat,
                   'running': running if running is not None else {'returnValue': True, 'isRunning': True},
                   'script': Path('home/operations/boot_runtime.js').read_text(), 'action': action,
                   'foreground': foreground, 'heartbeatUptime': heartbeat_uptime, 'previous': previous}
        runner = '''var vm = require('vm');
var input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
var calls = [];
var fs = {
  readlinkSync: function (path) { return path === '/proc/self/ns/mnt' ? 'mnt:[1]' : input.namespace; },
  readFileSync: function (path) {
    if (/runtime-health.json$/.test(path)) return JSON.stringify(input.previous);
    if (/boot-profile.json$/.test(path)) return JSON.stringify(input.config);
    if (/boot_id$/.test(path)) return 'boot-one';
    if (/uptime$/.test(path)) return '32.0 10.0';
    if (input.heartbeat) return JSON.stringify({transactionId: input.config.transactionId,
      appId: input.config.appId, bootId: 'boot-one', uptime: input.heartbeatUptime, uiReady: true});
    throw new Error('ENOENT');
  }
};
var cp = {execFileSync: function (name, args) {
  calls.push([name, args]);
  if (name === 'uname') return 'armv7l';
  if (name === 'pidof') return '123';
  var method = args[4];
  if (/getSystemInfo$/.test(method)) return JSON.stringify({returnValue: true, modelName: 'SYNTHETIC_MODEL', boardType: 'SYNTHETIC_BOARD', firmwareVersion: input.firmware, sdkVersion: '4.5'});
  if (/getAppInfo$/.test(method)) return JSON.stringify({returnValue: true, appInfo: {id: input.config.appId, type: 'web', appCategory: ['home'], main: 'index.html'}});
  if (/getAppLoadStatus$/.test(method)) return JSON.stringify(input.running);
  if (/getForegroundAppInfo$/.test(method)) return JSON.stringify({returnValue: true, appId: input.foreground});
  return '{"returnValue":true}';
}};
var output = '';
var fakeProcess = {stdout: {write: function (value) { output += value; }}, argv: ['node','runtime','/owned',input.action], stderr: {write: function () {}}};
vm.runInNewContext(input.script, {require: function (name) { return name === 'fs' ? fs : cp; }, process: fakeProcess});
console.log(JSON.stringify({code: fakeProcess.exitCode || 0, calls: calls, output: output}));
'''
        result = subprocess.run(['node', '-e', runner], input=json.dumps(payload), text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_accepted_but_stopped_home_fails_health(self):
        result = self.execute({'returnValue': True, 'status': 'not running', 'isRunning': False})
        self.assertNotEqual(result['code'], 0)

    def test_changed_firmware_and_namespace_fail_before_refresh(self):
        self.assertNotEqual(self.execute(firmware='UPDATED', action='preflight')['code'], 0)
        self.assertNotEqual(self.execute(namespace='mnt:[2]', action='preflight')['code'], 0)

    def test_missing_heartbeat_is_not_live_ui(self):
        self.assertNotEqual(self.execute(heartbeat=False)['code'], 0)
        self.assertEqual(self.execute()['code'], 0)

    def test_refresh_releases_sam(self):
        result = self.execute(action='refresh')
        methods = [args[4] for name, args in result['calls'] if name == 'luna-send']
        self.assertEqual([method.rsplit('/', 1)[1] for method in methods], ['blockSystemApp', 'releaseBlockSystemApp'])

    def test_background_app_and_hdmi_defer_ui_validation(self):
        for foreground in ('netflix', 'com.webos.app.hdmi1'):
            with self.subTest(foreground=foreground):
                result = self.execute(foreground=foreground, heartbeat=False,
                                      running={'returnValue': True, 'isRunning': False})
                self.assertEqual(result['code'], 0)
                state = json.loads(result['output'])
                self.assertEqual(state['state'], 'HOME_SUSPENDED')
                self.assertFalse(state['foregroundConfirmed'])
                self.assertFalse(state['uiConfirmed'])

    def test_return_to_home_requires_a_fresh_heartbeat(self):
        self.assertEqual(self.execute(foreground='netflix', heartbeat_uptime=0)['code'], 0)
        self.assertNotEqual(self.execute(heartbeat_uptime=0)['code'], 0)
        self.assertEqual(json.loads(self.execute()['output'])['state'], 'HOME_VISIBLE')

    def test_unknown_foreground_does_not_count_as_suspended(self):
        self.assertNotEqual(self.execute(foreground=None)['code'], 0)

    def test_resume_has_one_monitor_interval_to_restore_heartbeat(self):
        suspended = {'state': 'HOME_SUSPENDED'}
        result = self.execute(heartbeat=False, previous=suspended)
        self.assertEqual(result['code'], 0)
        resuming = json.loads(result['output'])
        self.assertEqual(resuming['state'], 'HOME_RESUMING')
        self.assertFalse(resuming['uiConfirmed'])
        self.assertNotEqual(self.execute(heartbeat=False, previous=resuming)['code'], 0)
        result = self.execute(previous=resuming)
        self.assertEqual(json.loads(result['output'])['state'], 'HOME_VISIBLE')

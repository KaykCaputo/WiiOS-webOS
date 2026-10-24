'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const cp = require('node:child_process');
const vm = require('node:vm');
const base = path.resolve(__dirname, '..');
if (!fs.existsSync(path.join(base, '../fullhome-original.tar'))) {
  test('firmware redirect fixture', {skip: 'Original firmware fixture is not distributed'}, () => {});
} else {
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wiios-redirect-test-'));
const bundle = path.join(tmp, 'bundle');
cp.execFileSync('python3', [path.join(base, 'prepare.py'), '--backup', path.join(base, '../fullhome-original.tar'), '--output', bundle, '--redirect-trial']);
const main = fs.readFileSync(path.join(bundle, 'main.qml'), 'utf8');
const ctrl = fs.readFileSync(path.join(bundle, 'UIController.qml'), 'utf8');
const manifest = JSON.parse(fs.readFileSync(path.join(bundle, 'manifest.json')));
function fn(source, name) {
  const start = source.indexOf('    function ' + name + '(');
  assert.notEqual(start, -1);
  return source.slice(start, source.indexOf('\n    }', start) + 6);
}
function context(reply) {
  const calls = [];
  const root = {wiiosFallback: false, wiiosRedirectPending: false, wiiosRequestSequence: 0,
    executeLaunch: (...args) => calls.push(['native', ...args]), dismissApp: () => calls.push(['hide'])};
  const c = vm.createContext({root, rootWindow: {wiiosIntent: 'homeKey', wiiosTrace: () => {}},
    Date, wiiosLaunchTimeout: {restart() {}, stop() {}},
    interfaces: {application: {simpleLaunch: (id, params, done) => {calls.push(['launch', id]); if (reply !== undefined) done(reply);}}}});
  vm.runInContext(fn(main, 'wiiosReadIntent') + '\n' + fn(ctrl, 'wiiosResumeNative') + '\n' + fn(ctrl, 'wiiosTryRedirect'), c);
  root.wiiosResumeNative = c.wiiosResumeNative;
  return {c, calls};
}
test('physical Home, explicit Home, boot classified; inputs/preload/recovery excluded', () => {
  const {c} = context();
  for (const p of [{launchType: 'homeKey'}, {activateType: 'home'}, {activateType: 'powerOn'}]) assert.ok(c.wiiosReadIntent({parameters: p}));
  for (const p of [{launchType: 'homeKey', activateType: 'launchByInput'}, {snapshot: true, launchType: 'homeKey'}, {wiiosNativeHome: true, activateType: 'home'}, {activateType: 'editMode'}]) assert.equal(c.wiiosReadIntent({parameters: p}), '');
  assert.equal(c.wiiosReadIntent({reason: 'preload', parameters: {launchType: 'homeKey'}}), '');
});
test('main mode from Home launches WiiOS and hides LG only on accepted launch', () => {
  const {c, calls} = context({returnValue: true});
  assert.equal(c.wiiosTryRedirect('main', null, false), true);
  assert.deepEqual(calls, [['launch', 'com.wiios.launcher'], ['hide']]);
  assert.equal(c.wiiosTryRedirect('main', null, false), false);
});
test('rejection falls back to native with original arguments', () => {
  const {c, calls} = context({returnValue: false});
  c.wiiosTryRedirect('main', 'extra', false);
  assert.deepEqual(calls, [['launch', 'com.wiios.launcher'], ['native', 'main', 'extra', false]]);
  assert.equal(c.root.wiiosFallback, false);
});
test('timeout falls back once; delayed success cannot hide native Home', () => {
  const {c, calls} = context(); let done;
  c.interfaces.application.simpleLaunch = (id, params, cb) => { done = cb; };
  c.wiiosTryRedirect('main', null, false);
  c.wiiosResumeNative('timeout'); done({returnValue: true}); c.wiiosResumeNative('timeout');
  assert.deepEqual(calls, [['native', 'main', null, false]]);
});
test('lease expiry and HDMI leave original execution intact', () => {
  const {c, calls} = context();
  assert.equal(c.wiiosTryRedirect('launchByInput', {}, false), false);
  c.Date = function () {this.getTime = () => manifest.deadline * 1000 + 1;};
  assert.equal(c.wiiosTryRedirect('main', null, false), false);
  assert.deepEqual(calls, []);
});
test('missing interface or thrown call cannot suppress original Home', () => {
  const {c, calls} = context();
  c.interfaces.application.simpleLaunch = () => {throw Error('no service');};
  assert.equal(c.wiiosTryRedirect('main', null, false), false);
  assert.equal(c.root.wiiosRedirectPending, false);
  assert.deepEqual(calls, []);
});
process.on('exit', () => fs.rmSync(tmp, {recursive: true}));

}

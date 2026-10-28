'use strict';
var fs = require('fs');
var childProcess = require('child_process');
var base = process.argv[2];
var action = process.argv[3];
var config = JSON.parse(fs.readFileSync(base + '/boot-profile.json', 'utf8'));
function luna(method, payload) {
  var data = childProcess.execFileSync('luna-send', ['-n', '1', '-w', '5000',
    'luna://com.webos.' + method, JSON.stringify(payload)], {timeout: 6000, maxBuffer: 65536, encoding: 'utf8'});
  var value = JSON.parse(data);
  if (!value || value.returnValue !== true) throw new Error('SERVICE_REJECTED');
  return value;
}
function namespaces() {
  var own = fs.readlinkSync('/proc/self/ns/mnt');
  ['sam', 'WebAppMgr'].forEach(function (name) {
    var pids = childProcess.execFileSync('pidof', [name], {timeout: 2000, encoding: 'utf8'}).trim().split(/\s+/);
    if (!pids.length) throw new Error('PROCESS_NAMESPACE_UNKNOWN');
    pids.forEach(function (pid) {
      if (!/^[1-9][0-9]*$/.test(pid) || fs.readlinkSync('/proc/' + pid + '/ns/mnt') !== own) throw new Error('NAMESPACE_MISMATCH');
    });
  });
}
function preflight() {
  var actual = luna('service.tv.systemproperty/getSystemInfo', {keys: ['modelName', 'boardType', 'firmwareVersion', 'sdkVersion']});
  var keys = {model: 'modelName', board: 'boardType', firmware: 'firmwareVersion', sdkVersion: 'sdkVersion'};
  Object.keys(keys).forEach(function (key) {
    if (!config.identity[key] || actual[keys[key]] !== config.identity[key]) throw new Error('FIRMWARE_PROFILE_CHANGED');
  });
  var architecture = childProcess.execFileSync('uname', ['-m'], {timeout: 2000, encoding: 'utf8'}).trim();
  if (architecture !== config.identity.architecture) throw new Error('ARCHITECTURE_CHANGED');
  namespaces();
}
function refresh() {
  if (config.native) return;
  if (config.samProtocol !== 'sam-block-release-v1') throw new Error('SAM_PROTOCOL_UNKNOWN');
  try {
    luna('applicationManager/blockSystemApp', {id: config.appId});
  } finally {
    luna('applicationManager/releaseBlockSystemApp', {id: config.appId});
  }
}
function health() {
  preflight();
  var response = luna('applicationManager/getAppInfo', {id: config.appId});
  var app = response.appInfo || response.app;
  if (!app || app.id !== config.appId || app.type !== (config.native ? 'native' : 'web')) throw new Error('MANIFEST_MISMATCH');
  if (!config.native && (!Array.isArray(app.appCategory) || app.appCategory.indexOf('home') === -1 || app.main !== config.main)) throw new Error('HOME_MANIFEST_MISMATCH');
  var foreground = luna('applicationManager/getForegroundAppInfo', {});
  var foregroundId = foreground.appId || foreground.foregroundAppId;
  if (typeof foregroundId !== 'string' || !foregroundId) throw new Error('FOREGROUND_UNKNOWN');
  if (foregroundId !== config.appId) return {state: 'HOME_SUSPENDED', foregroundConfirmed: false, uiConfirmed: false};
  var previous;
  try { previous = JSON.parse(fs.readFileSync(base + '/runtime-health.json', 'utf8')); } catch (ignore) { previous = null; }
  if (previous && previous.state === 'HOME_SUSPENDED') return {state: 'HOME_RESUMING', foregroundConfirmed: true, uiConfirmed: false};
  var running = luna('applicationManager/getAppLoadStatus', {appId: config.appId});
  if (running.isRunning === false || !(running.isRunning === true || running.status === 'running')) throw new Error('HOME_NOT_RUNNING');
  var heartbeat = JSON.parse(fs.readFileSync(base + '/ui-heartbeat.json', 'utf8'));
  var boot = fs.readFileSync('/proc/sys/kernel/random/boot_id', 'utf8').trim();
  var uptime = parseFloat(fs.readFileSync('/proc/uptime', 'utf8'));
  if (heartbeat.transactionId !== config.transactionId || heartbeat.appId !== config.appId || heartbeat.bootId !== boot ||
      heartbeat.uiReady !== true || typeof heartbeat.uptime !== 'number' || uptime < heartbeat.uptime || uptime - heartbeat.uptime > 15) throw new Error('UI_HEARTBEAT_MISSING');
  return {state: 'HOME_VISIBLE', foregroundConfirmed: true, uiConfirmed: true};
}
try {
  if (action === 'preflight') preflight();
  else if (action === 'refresh') refresh();
  else if (action === 'health') process.stdout.write(JSON.stringify(health()) + '\n');
  else throw new Error('BOOT_OPERATION_INVALID');
} catch (error) {
  process.stderr.write(String(error.message) + '\n');
  process.exitCode = 1;
}

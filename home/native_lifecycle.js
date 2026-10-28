'use strict';
var childProcess = require('child_process');
var fs = require('fs');
var path = require('path');
var app = process.argv[1];
var payloadPath = process.argv[2];
var contract = process.argv[3];
var field = contract === 'register-app-v2' ? 'event' : 'message';
var method = contract === 'register-app-v2' ? 'registerApp' : 'registerNativeApp';
var state = 'STARTING';
var registered = false;
var ending = false;
var pendingLaunch = null;
var buffer = '';
var statePath = path.join(path.dirname(path.dirname(payloadPath)), 'native-runtime.json');
var subscription;
var deadline;
function record() {
  fs.writeFileSync(statePath + '.pending', JSON.stringify({pid: process.pid, state: state, registered: registered}), {mode: 384});
  fs.renameSync(statePath + '.pending', statePath);
}
function finish(code) {
  if (ending) return;
  ending = true;
  registered = false;
  state = code === 0 ? 'EXITED' : 'FAILED';
  clearTimeout(deadline);
  try { record(); } catch (error) { code = 1; }
  if (pendingLaunch) pendingLaunch.kill('SIGTERM');
  if (subscription) subscription.kill('SIGTERM');
  setTimeout(function () {
    if (pendingLaunch) pendingLaunch.kill('SIGKILL');
    if (subscription) subscription.kill('SIGKILL');
    process.exit(code);
  }, 500);
}
function launch() {
  if (ending || pendingLaunch) return;
  state = 'STARTING';
  record();
  pendingLaunch = childProcess.execFile('luna-send', ['-n', '1', '-w', '8000',
    'luna://com.palm.webappmanager/launchApp', fs.readFileSync(payloadPath, 'utf8')],
  {timeout: 9000, maxBuffer: 8192}, function (error, output) {
    pendingLaunch = null;
    if (ending) return;
    try {
      if (error || JSON.parse(output).returnValue !== true) return finish(1);
      state = 'HIDDEN';
      record();
    } catch (failure) { finish(1); }
  });
}
function receive(line) {
  if (ending || !line.trim()) return;
  try {
    var reply = JSON.parse(line);
    if (!reply || reply.returnValue === false) return finish(1);
    var event = reply[field];
    if (event === 'close' || event === 'stop') return finish(0);
    if (event === 'registered' && reply.returnValue === true) {
      if (!registered) {
        registered = true;
        clearTimeout(deadline);
        launch();
      }
    } else if (!registered) {
      finish(1);
    } else if (event === 'relaunch') {
      launch();
    } else if (event === 'pause' || event === 'suspend') {
      state = 'HIDDEN';
      record();
    }
  } catch (error) { finish(1); }
}
process.on('SIGTERM', function () { finish(0); });
process.on('SIGINT', function () { finish(0); });
process.on('SIGHUP', function () { finish(1); });
process.on('uncaughtException', function () { finish(1); });
fs.writeFileSync(path.join(path.dirname(statePath), 'native-pid'), String(process.pid) + '\n' +
  fs.readFileSync('/proc/self/stat', 'utf8').slice(fs.readFileSync('/proc/self/stat', 'utf8').lastIndexOf(')') + 2).split(' ')[19] + '\n', {mode: 384});
record();
subscription = childProcess.spawn('luna-send', ['-i', '-a', app,
  'luna://com.webos.applicationManager/' + method, '{}'], {stdio: ['ignore', 'pipe', 'ignore']});
subscription.on('error', function () { finish(1); });
subscription.on('exit', function () { subscription = null; finish(1); });
subscription.stdout.on('data', function (data) {
  buffer += data.toString();
  if (buffer.length > 16384) return finish(1);
  var newline;
  while ((newline = buffer.indexOf('\n')) !== -1) {
    receive(buffer.slice(0, newline));
    buffer = buffer.slice(newline + 1);
  }
});
deadline = setTimeout(function () { finish(1); }, 8000);

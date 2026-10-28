'use strict';
var fs = require('fs');
var http = require('http');
var crypto = require('crypto');
var base = process.argv[2];
var config = JSON.parse(fs.readFileSync(base + '/bundle/wiios-home-session.json', 'utf8'));
var boot = fs.readFileSync('/proc/sys/kernel/random/boot_id', 'utf8').trim();
var last = 0;
var server = http.createServer(function (request, response) {
  var origin = request.headers.origin;
  if (request.headers.host !== '127.0.0.1:19084' || (origin !== 'null' && origin !== 'file://')) {
    response.writeHead(403); response.end(); return;
  }
  response.setHeader('Access-Control-Allow-Origin', origin);
  response.setHeader('Vary', 'Origin');
  if (request.method === 'OPTIONS') {
    response.setHeader('Access-Control-Allow-Methods', 'POST');
    response.setHeader('Access-Control-Allow-Headers', 'X-WiiOS-Token, Content-Type');
    response.writeHead(204); response.end(); return;
  }
  var token = request.headers['x-wiios-token'];
  if (request.url !== '/heartbeat' || request.method !== 'POST' || typeof token !== 'string' ||
      token.length !== config.token.length || !crypto.timingSafeEqual(Buffer.from(token), Buffer.from(config.token))) {
    response.writeHead(403); response.end(); return;
  }
  if (Date.now() - last < 1000) { response.writeHead(429); response.end(); return; }
  var body = '';
  request.setTimeout(3000, function () { request.destroy(); });
  request.on('data', function (chunk) {
    body += chunk.toString();
    if (body.length > 1024) request.destroy();
  });
  request.on('end', function () {
    try {
      var value = JSON.parse(body);
      if (value.appId !== config.appId || value.transactionId !== config.transactionId || value.uiReady !== true) throw new Error('INVALID_HEARTBEAT');
      last = Date.now();
      var record = {appId: config.appId, transactionId: config.transactionId, bootId: boot,
        uptime: parseFloat(fs.readFileSync('/proc/uptime', 'utf8')), uiReady: true};
      fs.writeFileSync(base + '/ui-heartbeat.pending', JSON.stringify(record), {mode: 384});
      fs.renameSync(base + '/ui-heartbeat.pending', base + '/ui-heartbeat.json');
      response.writeHead(204); response.end();
    } catch (error) { response.writeHead(400); response.end(); }
  });
});
server.on('error', function () { process.exit(1); });
server.listen(19084, '127.0.0.1', function () {
  fs.writeFileSync(base + '/heartbeat-ready', boot, {mode: 384});
});
setInterval(function () {
  if (fs.existsSync(base + '/boot-disabled') || fs.existsSync(base + '/trial-expired')) process.exit(0);
}, 2000);

'use strict';
var fs = require('fs'), http = require('http'), os = require('os'), crypto = require('crypto');

var METRICS_FINGERPRINT = crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex');
function cpu(text) {
  var line = /^cpu\s+(.+)$/m.exec(text);
  if (!line) return null;
  var values = line[1].trim().split(/\s+/).slice(0, 8).map(Number);
  if (values.length < 4 || values.some(function (v) {return !isFinite(v) || v < 0;})) return null;
  var total = values.reduce(function (a, b) {return a + b;}, 0);
  return {total: total, idle: values[3] + (values[4] || 0)};
}
function utilization(previous, next) {
  if (!previous || !next) return null;
  var total = next.total - previous.total, idle = next.idle - previous.idle;
  if (total <= 0 || idle < 0 || idle > total) return null;
  return Math.round(1000 * (1 - idle / total)) / 10;
}
function memory(text) {
  var values = {}, pattern = /^(\w+):\s+(\d+) kB$/gm, m;
  while ((m = pattern.exec(text))) values[m[1]] = Number(m[2]);
  if (!(values.MemTotal > 0)) return null;
  var estimated = values.MemAvailable === undefined;
  var available = estimated ? (values.MemFree || 0) + (values.Buffers || 0) + (values.Cached || 0) + (values.SReclaimable || 0) - (values.Shmem || 0) : values.MemAvailable;
  available = Math.max(0, Math.min(values.MemTotal, available));
  return {totalKiB: values.MemTotal, availableKiB: available, usedKiB: values.MemTotal - available, estimated: estimated};
}
function read(path) {try {return fs.readFileSync(path, 'utf8');} catch (e) {return '';}}
function temperature() {

  var zones;
  try {zones = fs.readdirSync('/sys/class/thermal');} catch (e) {return null;}
  for (var i = 0; i < zones.length; i++) {
    if (!/^thermal_zone\d+$/.test(zones[i])) continue;
    var dir = '/sys/class/thermal/' + zones[i];
    var type = read(dir + '/type').trim();
    var raw = read(dir + '/temp').trim();
    if (!type || !/^-?\d+$/.test(raw)) continue;
    var c = Number(raw) / 1000;
    if (c >= -40 && c <= 150) return {celsius: c, sensor: type};
  }
  return null;
}
function collector() {
  var last = null, cached = null, time = 0;
  return function () {
    var now = Date.now();
    if (cached && now - time < 1800) return cached;
    var next = cpu(read('/proc/stat')), thermal = temperature();
    cached = {schema: 1, sampledAt: now, cpuPercent: utilization(last, next), memory: memory(read('/proc/meminfo')),
      temperatureC: thermal ? thermal.celsius : null, temperatureSensor: thermal ? thermal.sensor : null,
      uptimeSeconds: Math.floor(os.uptime())};
    last = next; time = now;
    return cached;
  };
}
function server(sample, apps) {
  return http.createServer(function (req, res) {

    if (!/^(127\.0\.0\.1|localhost):19083$/.test(req.headers.host || '')) {res.writeHead(403); res.end(); return;}
    var origin = req.headers.origin;
    if (origin && origin !== 'null' && !/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(origin)) {res.writeHead(403); res.end(); return;}
    res.setHeader('Access-Control-Allow-Origin', origin || 'null');
    res.setHeader('Vary', 'Origin'); res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    if (req.method !== 'GET') {res.writeHead(404); res.end(); return;}
    if (apps && req.url === '/v1/health') {
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({schema: 1, pid: process.pid, catalogFingerprint: apps.fingerprint || null,
        metricsFingerprint: METRICS_FINGERPRINT}));
      return;
    }
    if (apps && req.url === '/v1/apps') {
      apps.list(function (error, result) {
        res.setHeader('Content-Type', 'application/json');
        if (error) {console.error('WiiOS app catalog: ' + error.message); res.writeHead(503); res.end(JSON.stringify({returnValue: false, errorText: 'Application list unavailable'})); return;}
        res.end(JSON.stringify(result));
      });
      return;
    }
    if (apps && req.url.indexOf('/v1/images/') === 0) {apps.serve(req.url, res); return;}
    if (req.url !== '/v1/stats') {res.writeHead(404); res.end(); return;}
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify(sample()));
  });
}
module.exports = {cpu: cpu, utilization: utilization, memory: memory, collector: collector, server: server};
if (require.main === module) {
  var sample = collector(); sample();
  var app = server(sample, require('./catalog')());
  app.listen(19083, '127.0.0.1', function () {console.log('WiiOS metrics listening on loopback only');});

  if (process.argv[2] === '--trial') {
    setTimeout(function () {app.close();}, 600000);
  }
  process.on('SIGTERM', function () {
    app.close(function () {process.exit(0);});
    setTimeout(function () {process.exit(0);}, 3000);
  });
}

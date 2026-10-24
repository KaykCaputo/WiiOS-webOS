'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const catalog = require('../root-services/catalog');

test('installed application images are discovered and served without bundled artwork', async () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'wiios-apps-'));
  const app = path.join(base, 'app.demo');
  fs.mkdirSync(app, {recursive: true});
  const icon = Buffer.from('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082', 'hex');
  fs.writeFileSync(path.join(app, 'icon.png'), icon);
  try {
    const svc = catalog({roots: [base], execute: (command, args, options, cb) => cb(null, JSON.stringify({returnValue: true, launchPoints: [{id: 'app.demo', title: 'Demo', largeIcon: 'icon.png'}]}))});
    const result = await new Promise((resolve, reject) => svc.list((err, value) => err ? reject(err) : resolve(value)));
    assert.equal(result.launchPoints.length, 1);
    const items = result.launchPoints[0].images;
    assert.ok(items.length > 0, 'expected original app artwork');
    const token = items[0].src.split('/').pop();
    const response = {status: null, bytes: null, headers: {}, writeHead(status) {this.status = status;}, setHeader(key, value) {this.headers[key] = value;}, end(bytes) {this.bytes = bytes;}};
    svc.serve('/v1/images/' + token, response);
    assert.equal(response.headers['Content-Type'], 'image/png');
    assert.deepEqual(response.bytes, icon);
    assert.equal(result.source, 'local');
  } finally {
    fs.rmSync(base, {recursive: true, force: true});
  }
});

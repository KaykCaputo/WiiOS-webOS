'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function environment(initial) {
  const saved = Object.assign({}, initial || {});
  const outbound = [];
  const storage = {
    getItem(key) {return saved[key] || null;},
    setItem(key, value) {saved[key] = value;},
    removeItem(key) {delete saved[key];}
  };
  class Socket {
    constructor(url) {this.url = url; outbound.push(['connect', url]); Socket.last = this;}
    send(json) {
      const packet = JSON.parse(json);
      outbound.push([packet.type, packet.uri || packet.id, packet.payload && packet.payload['client-key']]);
      if (packet.type === 'register') {
        this.onmessage({data: JSON.stringify({type: 'registered', payload: {'client-key': 'approved-key'}})});
      } else if (packet.type === 'request') {
        this.onmessage({data: JSON.stringify({type: 'response', id: packet.id, payload: {returnValue: true,
          launchPoints: [{id: 'app.valid', title: 'Valid'}]}})});
      }
    }
    close() {}
  }
  const window = {localStorage: storage, WebSocket: Socket,
    setTimeout() {return 1;}, clearTimeout() {}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'ssap-provider.js'), 'utf8'),
    {window, JSON, Number, Object, Array, RegExp, String});
  return {window, outbound, saved, Socket};
}

test('SSAP never connects before explicit pairing and rejects public endpoints', () => {
  const {window, outbound} = environment();
  assert.equal(window.WiiSSAP.configured(), false);
  assert.equal(window.WiiSSAP.configure('203.0.113.9', false), false);
  assert.equal(window.WiiSSAP.configure('192.168.1.4;evil', false), false);
  assert.equal(outbound.length, 0);
});

test('SSAP registers with permission prompt and preserves application listing', () => {
  const {window, outbound, saved, Socket} = environment();
  assert.equal(window.WiiSSAP.configure('192.168.68.50', false), true);
  window.WiiSSAP.list((error, result) => {
    assert.equal(error, null);
    assert.equal(result.source, 'ssap');
    assert.equal(result.launchPoints[0].id, 'app.valid');
  });
  Socket.last.onopen();
  assert.deepEqual(outbound.map(item => item[0]), ['connect', 'register', 'request']);
  assert.equal(outbound[0][1], 'ws://192.168.68.50:3000');
  assert.equal(JSON.parse(saved['wiios.ssap.pairing.v1']).key, 'approved-key');
  window.WiiSSAP.disconnect();
  assert.equal(window.WiiSSAP.configured(), false);
  assert.equal(saved['wiios.ssap.pairing.v1'], undefined);
});

test('SSAP supports an explicitly selected secure transport', () => {
  const {window, outbound} = environment();
  window.WiiSSAP.configure('10.10.10.10', true);
  window.WiiSSAP.list(() => {});
  assert.equal(outbound[0][1], 'wss://10.10.10.10:3001');
});

test('SSAP reconnects with a stored secure client key', () => {
  const stored = JSON.stringify({host: '192.168.1.50', transport: 'wss', key: 'existing-key'});
  const {window, outbound, Socket} = environment({'wiios.ssap.pairing.v1': stored});
  assert.equal(window.WiiSSAP.configured(), true);
  window.WiiSSAP.list(() => {});
  Socket.last.onopen();
  assert.equal(outbound[0][1], 'wss://192.168.1.50:3001');
  assert.equal(outbound[1][2], 'existing-key');
});

test('SSAP ignores an unsafe stored endpoint', () => {
  const stored = JSON.stringify({host: '203.0.113.10', transport: 'wss', key: 'existing-key'});
  const {window, outbound} = environment({'wiios.ssap.pairing.v1': stored});
  assert.equal(window.WiiSSAP.configured(), false);
  window.WiiSSAP.list(() => {});
  assert.equal(outbound.length, 0);
});

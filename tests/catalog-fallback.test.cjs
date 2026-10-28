'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function environment(store, listing) {
  const localStorage = {
    getItem(key) { return store[key] || null; },
    setItem(key, value) { store[key] = value; }
  };
  function XMLHttpRequest() {}
  XMLHttpRequest.prototype.open = function () {};
  XMLHttpRequest.prototype.send = function () { this.onerror(); };
  const window = {localStorage, XMLHttpRequest, WiiTV: {list: listing}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'library.js'), 'utf8'),
    {window, Date, JSON, Object, Array, String, RegExp});
  return window;
}

test('catalog survives lost Luna and local services without losing app assignments', () => {
  const store = {};
  const initial = environment(store, done => done(null, {returnValue: true, launchPoints: [
    {id: 'app.demo', title: 'Demo'}, {id: 'com.webos.app.home', title: 'Home'}
  ]}));
  initial.WiiLibrary.refresh((error, apps) => {
    assert.equal(error, null);
    assert.equal(apps.length, 1);
  });
  const disconnected = environment(store, done => done({errorText: 'Restricted firmware'}));
  disconnected.WiiLibrary.refresh((error, apps) => {
    assert.equal(error, null);
    assert.equal(apps.length, 1);
    assert.equal(apps[0].id, 'app.demo');
  });
  assert.equal(disconnected.WiiLibrary.diagnostics().stale, true);
  assert.equal(disconnected.WiiLibrary.diagnostics().source, 'snapshot-cache');
});

test('catalog refuses expired, malformed or foreign application snapshots', () => {
  for (const payload of [
    '{broken',
    JSON.stringify({version: 1, savedAt: Date.now() - 40 * 86400000, apps: [{id: 'valid.app', name: 'Valid'}]}),
    JSON.stringify({version: 1, savedAt: Date.now(), apps: [{id: '../../unsafe', name: 'Bad'}]})
  ]) {
    const store = {'wiios.catalog.snapshot.v1': payload};
    const tv = environment(store, done => done({errorText: 'Blocked'}));
    tv.WiiLibrary.refresh((error, apps) => {
      assert.ok(error);
      assert.equal(apps, undefined);
    });
  }
});

test('fresh Luna listing restores normal catalog status after stale data', () => {
  const store = {};
  let count = 0;
  const tv = environment(store, done => {
    count += 1;
    if (count === 2) return done({errorText: 'Unavailable'});
    done(null, {returnValue: true, launchPoints: [{id: 'app.demo', title: 'Demo'}]});
  });
  tv.WiiLibrary.refresh(() => {});
  tv.WiiLibrary.refresh(() => {});
  assert.equal(tv.WiiLibrary.diagnostics().stale, true);
  tv.WiiLibrary.refresh(() => {});
  assert.equal(tv.WiiLibrary.diagnostics().stale, false);
  assert.equal(tv.WiiLibrary.diagnostics().source, 'luna');
});

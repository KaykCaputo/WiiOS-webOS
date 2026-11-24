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

test('Home Chooser is used if the local helper is absent and falls back when it is denied', () => {
  let luna = 0;
  const tv = environment({}, done => {
    luna++;
    done(null, {launchPoints: [{id: 'app.luna', title: 'Luna'}]});
  });
  tv.WiiChooser = {enabled: () => true, list: done => done(null, {
    source: 'home-chooser', launchPoints: [{id: 'app.chooser', title: 'Chooser'}]
  })};
  tv.WiiLibrary.refresh((error, apps) => {
    assert.equal(error, null);
    assert.equal(apps[0].id, 'app.chooser');
    assert.equal(tv.WiiLibrary.listedByChooser('app.chooser'), true);
    assert.equal(luna, 0);
  });
  tv.WiiChooser.list = done => done({errorText: 'Permission denied'});
  tv.WiiLibrary.refresh((error, apps) => {
    assert.equal(error, null);
    assert.equal(apps[0].id, 'app.luna');
    assert.equal(luna, 1);
  });
});

test('banner choices survive a new launcher session and refresh only when the image changes', () => {
  const store = {};
  const source = token => ({
    source: 'local',
    launchPoints: [{id: 'app.demo', title: 'Demo', images: [
      {src: 'http://127.0.0.1:19083/v1/images/' + token.repeat(64), kind: 'icon', background: '#123abc'}
    ]}]
  });
  const initial = environment(store);
  initial.WiiLibrary.accept(source('a'));
  const reopened = environment(store);
  assert.equal(reopened.WiiLibrary.image('app.demo').choices[0].background, '#123abc');
  assert.equal(reopened.WiiLibrary.diagnostics().source, 'snapshot-cache');
  reopened.WiiLibrary.accept(source('a'));
  assert.equal(reopened.WiiLibrary.artworkVersion(), 0);
  reopened.WiiLibrary.accept(source('b'));
  assert.equal(reopened.WiiLibrary.artworkVersion(), 1);
  assert.match(environment(store).WiiLibrary.image('app.demo').choices[0].src, /b{64}$/);
});

test('Luna falls back to installed apps when launch points have no usable apps', () => {
  const tv = environment({});
  const calls = [];
  tv.WiiTV.request = (method, params, done) => {
    calls.push(method);
    if (method === 'listLaunchPoints') {
      done(null, {launchPoints: [{id: 'com.webos.app.home'}, {id: 'app.hidden', visible: false}]});
    } else {
      done(null, {apps: [{id: 'app.demo', icon: 'icon.png', folderPath: '/usr/palm/applications/app.demo'}]});
    }
  };
  tv.WiiLibrary.refresh((error, apps) => {
    assert.equal(error, null);
    assert.deepEqual(calls, ['listLaunchPoints', 'listApps']);
    assert.equal(apps[0].id, 'app.demo');
    assert.equal(tv.WiiLibrary.image('app.demo').choices[0].src, 'file:///usr/palm/applications/app.demo/icon.png');
  });
});

test('paired TV artwork is saved and restored only for the paired host', () => {
  const store = {};
  const tv = environment(store, done => done({errorText: 'Denied'}));
  tv.WiiSSAP = {configured: () => true, address: () => '192.168.1.7', list: done => done(null, {
    source: 'ssap',
    launchPoints: [{id: 'app.demo', bgImage: 'http://192.168.1.8:3000/resources/untrusted.png',
      largeIcon: 'http://192.168.1.7:3000/resources/%2e%2e/private.png',
      icon: 'http://192.168.1.7:3000/resources/valid.png'}]
  })};
  tv.WiiLibrary.refresh((error, apps) => {
    assert.equal(error, null);
    assert.equal(apps.length, 1);
    const choices = tv.WiiLibrary.image('app.demo').choices;
    assert.equal(choices.length, 1);
    assert.equal(choices[0].src, 'http://192.168.1.7:3000/resources/valid.png');
  });
  const reopened = environment(store);
  assert.equal(reopened.WiiLibrary.image('app.demo'), null);
});

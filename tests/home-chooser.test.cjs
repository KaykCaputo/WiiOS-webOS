'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'home-chooser.js'), 'utf8');
const icon = 'data:image/png;base64,iVBORw0KGgo=';

function setup({permitted = true, enabled = true, store = {}, iconPath = '/app/icon.png'} = {}) {
  const calls = [];
  const window = {
    WIIOS_HOME_CHOOSER_API: enabled,
    localStorage: {getItem: key => store[key], setItem: (key, value) => {store[key] = value;}},
    WiiTV: {
      chooserRequest(method, payload, done) {
        calls.push([method, JSON.parse(JSON.stringify(payload))]);
        const results = {
          getInfo: {apiVersion: 3, root: true, permitted, isSelectedHome: false},
          listLaunchPoints: {launchPoints: [
            {id: 'app.demo', title: 'Demo', launchPointId: 'demo_default', icon: iconPath},
            {id: 'app.extra', title: 'Extra', launchPointId: 'extra_default', icon: '/app/extra.png'},
            {id: 'com.wiios.launcher', title: 'WiiOS'},
            {id: 'app.demo', lptype: 'bookmark'}
          ]},
          getIcons: {icons: [{dataUrl: icon}]}
        };
        done(null, results[method]);
      }
    }
  };
  vm.runInNewContext(source, {window});
  return {chooser: window.WiiChooser, calls, store};
}

test('Home Chooser discovers apps without being the selected Home and fetches only requested icons', () => {
  const {chooser, calls} = setup();
  chooser.list((error, result) => {
    assert.equal(error, null);
    assert.deepEqual(Array.from(result.launchPoints, entry => entry.id), ['app.demo', 'app.extra']);
  });
  chooser.icons(['app.demo', 'app.demo'], changed => assert.equal(changed, true));
  chooser.icons(['app.demo'], changed => assert.equal(changed, false));
  assert.equal(chooser.image('app.demo').choices[0].src, icon);
  assert.deepEqual(calls, [['getInfo', {}], ['listLaunchPoints', {}],
    ['getIcons', {items: [{launchPointId: 'demo_default', size: 'icon'}]}]]);
});

test('stored Home Chooser icons are reused until the launch point icon changes', () => {
  const first = setup();
  first.chooser.list(() => {});
  first.chooser.icons(['app.demo'], () => {});
  const reopened = setup({store: first.store});
  assert.equal(reopened.chooser.image('app.demo').choices[0].src, icon);
  reopened.chooser.list(() => {});
  reopened.chooser.icons(['app.demo'], changed => assert.equal(changed, false));
  const updated = setup({store: first.store, iconPath: '/app/new-icon.png'});
  updated.chooser.list((error, result) => {
    assert.equal(error, null);
    assert.equal(result.artworkChanged, true);
  });
  assert.equal(updated.chooser.image('app.demo'), null);
});

test('Home Chooser permission denial and the standard package avoid privileged discovery', () => {
  const denied = setup({permitted: false});
  denied.chooser.list(error => assert.ok(error));
  assert.equal(denied.calls.length, 1);
  const standard = setup({enabled: false});
  standard.chooser.list(error => assert.ok(error));
  assert.equal(standard.calls.length, 0);
});

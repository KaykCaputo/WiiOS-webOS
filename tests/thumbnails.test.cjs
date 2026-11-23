'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.resolve(__dirname, '../thumbnails.js'), 'utf8');
const source = 'http://127.0.0.1:19083/v1/images/' + 'a'.repeat(64);

function fixture(type) {
  const data = new ArrayBuffer(20);
  const view = new DataView(data);
  if (type === 'jpeg') view.setUint16(0, 0xffd8);
  if (type === 'apng') {
    view.setUint32(0, 0x89504e47);
    view.setUint32(4, 0x0d0a1a0a);
    view.setUint32(12, 0x6163544c);
  }
  const saved = new Map(), draws = [], revoked = [];
  let requests = 0, sequence = 0;
  const store = {
    get(key) {
      const request = {result: saved.get(key)};
      queueMicrotask(() => request.onsuccess());
      return request;
    },
    put(item) { saved.set(item.key, item); },
    count() {
      const request = {result: saved.size};
      queueMicrotask(() => request.onsuccess());
      return request;
    }
  };
  function create() {
    const window = {
      URL: {createObjectURL: () => 'blob:test-' + ++sequence, revokeObjectURL: url => revoked.push(url)},
      Blob,
      HTMLCanvasElement: {prototype: {toBlob() {}}},
      indexedDB: {open() {
        const request = {result: {transaction: () => ({objectStore: () => store})}};
        queueMicrotask(() => request.onsuccess());
        return request;
      }},
      XMLHttpRequest: function () {
        this.open = () => {};
        this.send = () => {
          requests++;
          this.status = 200;
          this.response = data;
          queueMicrotask(() => this.onload());
        };
      },
      Image: function () {
        this.naturalWidth = 1600;
        this.naturalHeight = 900;
        Object.defineProperty(this, 'src', {set: () => queueMicrotask(() => this.onload())});
      },
      document: {createElement: () => ({
        getContext: () => ({drawImage: (_, ...args) => draws.push(args)}),
        toBlob: callback => queueMicrotask(() => callback(new Blob(['thumbnail'])))
      })}
    };
    vm.runInNewContext(code, {window});
    return window.WiiThumbnails;
  }
  function tile(src = source) {
    return {
      hasAttribute: () => true, getAttribute: () => src,
      parentNode: {classList: {contains: () => false}},
      naturalWidth: 1600, naturalHeight: 900
    };
  }
  const wait = () => new Promise(resolve => setImmediate(resolve));
  return {create, tile, wait, saved, draws, revoked, requests: () => requests};
}

test('large JPEG banners use the displayed resolution and reuse the persistent thumbnail after relaunch', async () => {
  const f = fixture('jpeg');
  const first = f.create(), image = f.tile();
  await f.wait();
  first.attach(image, 1, () => {});
  await f.wait();
  assert.equal(image.src, source);
  first.loaded(image);
  const apply = await new Promise(resolve => assert.equal(first.prepare(draw => draw(), resolve), true));
  assert.equal(image.src, source);
  apply();
  assert.match(image.src, /^blob:/);
  assert.equal(f.saved.size, 1);
  assert.deepEqual(f.draws[0].slice(-2), [253, 143]);
  const second = f.create(), same = f.tile(), changed = f.tile(source.replace(/a$/, 'b'));
  await f.wait();
  second.attach(same, 1, () => {});
  second.attach(changed, 1, () => {});
  await f.wait();
  assert.match(same.src, /^blob:/);
  assert.equal(changed.src, source.replace(/a$/, 'b'));
  assert.equal(f.requests(), 1);
  const url = same.src;
  assert.equal(second.restore(same), true);
  assert.ok(f.revoked.includes(url));
  assert.equal(same.src, source);
});

test('animated PNG is kept as the original and retired grid images are excluded', async () => {
  const f = fixture('apng');
  const thumbnails = f.create(), retired = f.tile(), image = f.tile();
  await f.wait();
  for (const item of [retired, image]) thumbnails.attach(item, 1, () => {});
  await f.wait();
  for (const item of [retired, image]) thumbnails.loaded(item);
  thumbnails.release(retired);
  const apply = await new Promise(resolve => assert.equal(thumbnails.prepare(draw => draw(), resolve), true));
  assert.equal(apply, null);
  assert.equal(image.src, source);
  assert.equal(f.requests(), 1);
  assert.equal(f.saved.size, 0);
  assert.equal(thumbnails.prepare(draw => draw(), () => {}), false);
});

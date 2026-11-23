(function (root) {
  'use strict';
  var budget = 40, maxSize = 192 * 1024, maxSource = 8 * 1024 * 1024, lifetime = 7 * 86400000;
  var cache = null, binding = new WeakMap(), pending = [];
  var sourceURL = /^(?:http:\/\/127\.0\.0\.1:19083\/v1\/images\/[a-f0-9]{64}|file:\/\/\/)/;
  var enabled = root.URL && root.URL.createObjectURL && root.HTMLCanvasElement.prototype.toBlob;

  if (enabled && root.indexedDB) {
    try {
      var opening = root.indexedDB.open('wiios.thumbnails.v1', 1);
      opening.onupgradeneeded = function () { opening.result.createObjectStore('images', {keyPath: 'key'}).createIndex('saved', 'saved'); };
      opening.onsuccess = function () { cache = opening.result; };
    } catch (ignore) {}
  }

  function lookup(key, done) {
    if (!cache || !key) {done(null); return;}
    var request;
    try {request = cache.transaction('images').objectStore('images').get(key);}
    catch (ignore) {done(null); return;}
    request.onerror = function () {done(null);};
    request.onsuccess = function () {
      var item = request.result;
      done(item && Date.now() - item.saved < lifetime && item.blob && item.blob.size <= maxSize ? item.blob : null);
    };
  }

  function save(key, blob) {
    if (!cache || !key) return;
    try {
      var store = cache.transaction('images', 'readwrite').objectStore('images');
      store.put({key: key, blob: blob, saved: Date.now()});
      var count = store.count();
      count.onsuccess = function () {
        var excess = count.result - budget;
        if (excess <= 0) return;
        var cursor = store.index('saved').openKeyCursor();
        cursor.onsuccess = function () {
          if (!cursor.result || excess-- <= 0) return;
          store.delete(cursor.result.primaryKey);
          cursor.result.continue();
        };
      };
    } catch (ignore) {}
  }

  function release(image) {
    if (!image) return;
    var previous = binding.get(image), index = pending.indexOf(image);
    if (index >= 0) pending.splice(index, 1);
    if (previous && previous.url) root.URL.revokeObjectURL(previous.url);
    binding.delete(image);
  }

  function use(image, record, blob) {
    if (binding.get(image) !== record) return;
    try {record.url = root.URL.createObjectURL(blob);}
    catch (ignore) { image.src = record.source; return; }
    image.src = record.url;
  }

  function attach(image, scale, ready) {
    if (!image || !image.hasAttribute('data-grid-src')) return;
    var source = image.getAttribute('data-grid-src'), icon = image.parentNode.classList.contains('art-app-icon');
    if (!enabled || !sourceURL.test(source)) {image.src = source; return;}
    var width = Math.min(1024, Math.ceil(246 * (icon ? .70 : 1) * scale * 1.025));
    var height = Math.min(576, Math.ceil(139 * (icon ? .76 : 1) * scale * 1.025));
    var key = source.indexOf('http:') === 0 ? source + ':' + width + 'x' + height + ':' + icon : null;
    var record = {source: source, key: key, width: width, height: height, icon: icon, url: null, attempted: false, ready: ready};
    binding.set(image, record);
    lookup(key, function (blob) {
      if (binding.get(image) !== record) return;
      if (blob) use(image, record, blob);
      else image.src = source;
    });
  }

  function restore(image) {
    var record = binding.get(image);
    if (!record || !record.url) return false;
    release(image);
    image.src = record.source;
    return true;
  }

  function dimensions(record, width, height) {
    var ratio = Math.min(record.width / width, record.height / height);
    if (record.icon) return {width: Math.ceil(width * ratio), height: Math.ceil(height * ratio), ratio: ratio};
    return {width: record.width, height: record.height, ratio: Math.max(record.width / width, record.height / height)};
  }

  function loaded(image) {
    var record = binding.get(image);
    if (!record || record.url || record.attempted || !image.naturalWidth || !image.naturalHeight) return;
    if (dimensions(record, image.naturalWidth, image.naturalHeight).ratio > .75) return;
    if (pending.indexOf(image) < 0) pending.push(image);
    record.ready();
  }

  function staticType(buffer) {
    var bytes = new DataView(buffer);
    if (bytes.byteLength < 12) return null;
    if (bytes.getUint16(0) === 0xffd8) return 'image/jpeg';
    if (bytes.getUint32(0) === 0x89504e47 && bytes.getUint32(4) === 0x0d0a1a0a) {
      for (var offset = 8; offset + 12 <= bytes.byteLength;) {
        var length = bytes.getUint32(offset), type = bytes.getUint32(offset + 4);
        if (type === 0x6163544c || length > bytes.byteLength - offset - 12) return null;
        if (type === 0x49444154) return 'image/png';
        offset += length + 12;
      }
    }
    return null;
  }

  function resize(source, record, schedule, done) {
    var request = new root.XMLHttpRequest();
    try {
      request.open('GET', source, true); request.responseType = 'arraybuffer'; request.timeout = 5000;
      request.onerror = request.ontimeout = request.onabort = function () {done(null);};
      request.onprogress = function (event) {if (event.loaded > maxSource) request.abort();};
      request.onload = function () {
        var data = request.response, type = data && data.byteLength <= maxSource && staticType(data);
        if (!type || (request.status !== 0 && request.status !== 200)) {done(null); return;}
        var original = new root.Image(), url;
        try {url = root.URL.createObjectURL(new root.Blob([data], {type: type}));}
        catch (ignore) {done(null); return;}
        original.onerror = function () {root.URL.revokeObjectURL(url); done(null);};
        original.onload = function () {
          root.URL.revokeObjectURL(url);
          schedule(function () {
            var canvas = root.document.createElement('canvas');
            var width = original.naturalWidth, height = original.naturalHeight, fit = dimensions(record, width, height);
            if (fit.ratio > .75) {done(null); return;}
            canvas.width = fit.width; canvas.height = fit.height;
            try {
              var context = canvas.getContext('2d');
              context.imageSmoothingQuality = 'high';
              var sw = Math.min(width, fit.width / fit.ratio), sh = Math.min(height, fit.height / fit.ratio);
              context.drawImage(original, (width - sw) / 2, (height - sh) / 2, sw, sh, 0, 0, fit.width, fit.height);
              canvas.toBlob(function (blob) {done(blob && blob.size <= maxSize ? blob : null);}, 'image/png');
            } catch (ignore) {done(null);}
          });
        };
        original.src = url;
      };
      request.send();
    } catch (ignore) {done(null);}
  }

  function prepare(schedule, done) {
    if (!pending.length) return false;
    var image = pending.shift(), record = binding.get(image);
    record.attempted = true;
    lookup(record.key, function (cached) {
      if (cached) {done(function () {use(image, record, cached);}); return;}
      if (binding.get(image) !== record) {done(null); return;}
      resize(record.source, record, schedule, function (blob) {
        if (blob) save(record.key, blob);
        done(blob ? function () {use(image, record, blob);} : null);
      });
    });
    return true;
  }

  root.WiiThumbnails = {attach: attach, release: release, restore: restore, loaded: loaded, prepare: prepare};
}(window));

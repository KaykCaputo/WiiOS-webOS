(function (root) {
  'use strict';
  var points = [], images = Object.create(null), endpoint = 'http://127.0.0.1:19083', lastSource = 'unknown', lastError = '', stale = false;
  var cacheKey = 'wiios.catalog.snapshot.v1', cacheLimit = 48 * 1024, maxAgeMs = 30 * 24 * 60 * 60 * 1000; 
  function validImage(value, local) {
    if (typeof value !== 'string') return '';
    if (local) return /^http:\/\/127\.0\.0\.1:19083\/v1\/images\/[a-f0-9]{64}$/.test(value) ? value : '';
    if (value.indexOf('file://') === 0) value = value.slice(7);
    if (value.split('/').indexOf('..') !== -1 || /[\x00-\x1f]/.test(value)) return '';
    if (!/^\/(?:usr\/palm|media\/(?:cryptofs\/apps|developer\/apps)\/usr\/palm|mnt\/otncabi\/usr\/palm)\/applications\/[A-Za-z0-9_.-]+\/.+\.(?:png|jpe?g|webp)$/i.test(value)) return '';
    return 'file://' + value;
  }
  function snapshot() {
    try {
      if (!root.localStorage) return null;
      var raw = root.localStorage.getItem(cacheKey);
      if (!raw || raw.length > cacheLimit) return null;
      var cached = JSON.parse(raw);
      if (!cached || cached.version !== 1 || typeof cached.savedAt !== 'number' ||
          cached.savedAt > Date.now() + 60000 || Date.now() - cached.savedAt > maxAgeMs ||
          !Array.isArray(cached.apps) || cached.apps.length > 512) return null;
      var seen = Object.create(null), entries = [];
      cached.apps.forEach(function (app) {
        if (!app || typeof app.id !== 'string' || !/^[A-Za-z0-9_.-]{1,160}$/.test(app.id) ||
            typeof app.name !== 'string' || seen[app.id] || entries.length >= 512) return;
        if (['com.wiios.launcher', 'com.webos.app.home', 'com.webos.app.fullhome'].indexOf(app.id) !== -1) return;
        seen[app.id] = true;
        entries.push({id: app.id, name: app.name.slice(0, 40)});
      });
      return entries.length ? entries : null;
    } catch (ignore) { return null; }
  }
  function persist() {
    try {
      if (!root.localStorage || !points.length) return;
      var raw = JSON.stringify({version: 1, savedAt: Date.now(), apps: points});
      if (raw.length <= cacheLimit) root.localStorage.setItem(cacheKey, raw);
    } catch (ignore) {}
  }
  function useSnapshot() {
    var entries = points.length ? points : snapshot();
    if (!entries) return null;
    points = entries;
    stale = true;
    lastSource = points === entries && images && Object.keys(images).length ? 'memory-cache' : 'snapshot-cache';
    return points;
  }
  function accept(response) {
    var seen = Object.create(null), next = [], artwork = Object.create(null), local = response.source === 'local';
    response.launchPoints.slice(0, 512).forEach(function (point) {
      if (!point || typeof point.id !== 'string' || !/^[A-Za-z0-9_.-]{1,160}$/.test(point.id) || seen[point.id] || point.visible === false) return;
      if (['com.wiios.launcher', 'com.webos.app.home', 'com.webos.app.fullhome'].indexOf(point.id) !== -1) return;
      seen[point.id] = true;
      next.push({id: point.id, name: String(point.title || point.id).slice(0, 40)});
      var candidates = local && Array.isArray(point.images) ? point.images.slice(0, 8) :
        [{src: point.bgImage, kind: 'banner'}, {src: point.largeIcon, kind: 'icon'}, {src: point.icon, kind: 'icon'}];

      if (point.id === 'netflix') candidates.sort(function (a, b) {
        return (a.kind === 'icon' ? 0 : 1) - (b.kind === 'icon' ? 0 : 1);
      });
      var choices = [];
      candidates.forEach(function (entry) {
        if (!entry) return;
        var src = validImage(entry.src, local);
        if (src) choices.push({src: src, kind: entry.kind === 'banner' ? 'banner' : 'icon', recommended: entry.recommended !== false, background: local && /^#[0-9a-f]{6}$/i.test(entry.background) ? entry.background : ''});
      });
      if (choices.length) artwork[point.id] = {choices: choices, background: /^#[0-9a-f]{6}$/i.test(point.bgColor) ? point.bgColor : '#eef0f2'};
    });
    points = next; images = artwork; lastSource = local ? 'local' : response.source === 'ssap' ? 'ssap' : 'luna'; lastError = ''; stale = false; persist(); 
    return points;
  }
  function refresh(done) {
    var xhr, finished = false;
    function fallback() {
      if (finished) return;
      finished = true;
      root.WiiTV.list(function (error, response) {
        if (error || !response || !Array.isArray(response.launchPoints) || !response.launchPoints.length) {
          lastError = error && error.errorText || 'Application list unavailable';
          if (root.WiiSSAP && root.WiiSSAP.configured()) {
            root.WiiSSAP.list(function (ssapError, ssapResponse) {
              if (!ssapError && ssapResponse && Array.isArray(ssapResponse.launchPoints) && ssapResponse.launchPoints.length) {done(null, accept(ssapResponse)); return;}
              var cached = useSnapshot(); if (cached) {done(null, cached); return;}
              done(ssapError || error || {errorText: lastError});
            });
            return;
          }
          var cached = useSnapshot(); if (cached) {done(null, cached); return;} done(error || {errorText: lastError}); return;
        }
        if (response.source !== 'ssap') response.source = 'luna';
        done(null, accept(response));
      });
    }
    try {
      xhr = new root.XMLHttpRequest();
      xhr.open('GET', endpoint + '/v1/apps', true); xhr.timeout = 5500;
      xhr.onerror = xhr.ontimeout = xhr.onabort = fallback;
      xhr.onload = function () {
        if (finished) return;
        var response;
        try {response = JSON.parse(xhr.responseText);} catch (e) {fallback(); return;}
        if (xhr.status !== 200 || response.returnValue !== true || response.source !== 'local' || !Array.isArray(response.launchPoints) || !response.launchPoints.length) {fallback(); return;}
        finished = true; done(null, accept(response));
      };
      xhr.send();
    } catch (e) {fallback();}
  }
  root.WiiLibrary = {refresh: refresh, accept: accept,
    entries: function () {return points;}, image: function (id) {return images[id] || null;},
    diagnostics: function () {return {source: lastSource, error: lastError, stale: stale, apps: points.length, withImages: Object.keys(images).length};}};
}(window));

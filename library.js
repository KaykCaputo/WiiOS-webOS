(function (root) {
  'use strict';
  var points = [], images = Object.create(null), endpoint = 'http://127.0.0.1:19083', lastSource = 'unknown', lastError = '', stale = false;
  var cacheKey = 'wiios.catalog.snapshot.v1', cacheLimit = 256 * 1024, maxAgeMs = 30 * 24 * 60 * 60 * 1000;
  var artworkVersion = 0, savedAt = 0;
  function validImage(value, local) {
    if (typeof value !== 'string') return '';
    if (local) return /^http:\/\/127\.0\.0\.1:19083\/v1\/images\/[a-f0-9]{64}$/.test(value) ? value : '';
    if (value.indexOf('file://') === 0) value = value.slice(7);
    if (value.split('/').indexOf('..') !== -1 || /[\x00-\x1f]/.test(value)) return '';
    if (!/^\/(?:usr\/palm|media\/(?:cryptofs\/apps|developer\/apps)\/usr\/palm|mnt\/otncabi\/usr\/palm)\/applications\/[A-Za-z0-9_.-]+\/.+\.(?:png|jpe?g|webp)$/i.test(value)) return '';
    return 'file://' + value;
  }
  function color(value) { return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value : ''; }
  function imageChoices(candidates, local) {
    var choices = [];
    candidates.slice(0, 8).forEach(function (entry) {
      if (!entry || typeof entry.src !== 'string' || entry.src.length > 2048) return;
      var src = validImage(entry.src, local);
      if (src) choices.push({src: src, kind: entry.kind === 'banner' ? 'banner' : 'icon',
        recommended: entry.recommended !== false, background: local ? color(entry.background) : ''});
    });
    return choices;
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
      var seen = Object.create(null), entries = [], artwork = Object.create(null);
      cached.apps.forEach(function (app) {
        if (!app || typeof app.id !== 'string' || !/^[A-Za-z0-9_.-]{1,160}$/.test(app.id) ||
            typeof app.name !== 'string' || seen[app.id] || entries.length >= 512) return;
        if (['com.wiios.launcher', 'com.webos.app.home', 'com.webos.app.fullhome'].indexOf(app.id) !== -1) return;
        seen[app.id] = true;
        entries.push({id: app.id, name: app.name.slice(0, 40)});
        var image = app.artwork;
        if (image && Array.isArray(image.choices)) {
          var choices = imageChoices(image.choices, image.local === true);
          if (choices.length) artwork[app.id] = {choices: choices, background: color(image.background) || '#eef0f2'};
        }
      });
      return entries.length ? {apps: entries, artwork: artwork, savedAt: cached.savedAt} : null;
    } catch (ignore) { return null; }
  }
  function persist() {
    try {
      if (!root.localStorage) return;
      var budget = cacheLimit - JSON.stringify(points).length - 128;
      var apps = points.map(function (app) {
        var image = images[app.id];
        if (!image || budget <= 0) return app;
        var artwork = {choices: image.choices, background: image.background,
          local: image.choices[0].src.indexOf(endpoint + '/') === 0};
        var size = JSON.stringify(artwork).length + 14;
        if (size > budget) return app;
        budget -= size;
        return {id: app.id, name: app.name, artwork: artwork};
      });
      var now = Date.now(), raw = JSON.stringify({version: 1, savedAt: now, apps: apps});
      if (raw.length <= cacheLimit) { root.localStorage.setItem(cacheKey, raw); savedAt = now; }
    } catch (ignore) {}
  }
  function useSnapshot() {
    if (!points.length) return null;
    stale = true;
    if (lastSource !== 'snapshot-cache') lastSource = 'memory-cache';
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
        return (a && a.kind === 'icon' ? 0 : 1) - (b && b.kind === 'icon' ? 0 : 1);
      });
      var choices = imageChoices(candidates, local);
      if (choices.length) {
        var candidate = {choices: choices, background: color(point.bgColor) || '#eef0f2'};
        var previous = images[point.id];
        artwork[point.id] = previous && JSON.stringify(candidate) === JSON.stringify(previous) ? previous : candidate;
      }
    });
    var oldIds = Object.keys(images), newIds = Object.keys(artwork);
    var changed = oldIds.length !== newIds.length || newIds.some(function (id) {
      return artwork[id] !== images[id];
    });
    var catalogChanged = JSON.stringify(next) !== JSON.stringify(points);
    if (changed) { images = artwork; artworkVersion++; }
    if (catalogChanged) points = next;
    lastSource = local ? 'local' : response.source === 'ssap' ? 'ssap' : 'luna'; lastError = ''; stale = false;
    if (changed || catalogChanged || Date.now() - savedAt >= 24 * 60 * 60 * 1000) persist();
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
  var cached = snapshot();
  if (cached) {
    points = cached.apps; images = cached.artwork; savedAt = cached.savedAt; stale = true; lastSource = 'snapshot-cache';
  }
  root.WiiLibrary = {refresh: refresh, accept: accept,
    artworkVersion: function () {return artworkVersion;},
    entries: function () {return points;}, image: function (id) {return images[id] || null;},
    diagnostics: function () {return {source: lastSource, error: lastError, stale: stale, apps: points.length, withImages: Object.keys(images).length};}};
}(window));

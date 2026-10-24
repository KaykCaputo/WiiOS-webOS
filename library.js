(function (root) {
  'use strict';
  var points = [], images = Object.create(null), endpoint = 'http://127.0.0.1:19083', lastSource = 'unknown', lastError = ''; 
  function validImage(value, local) {
    if (typeof value !== 'string') return '';
    if (local) return /^http:\/\/127\.0\.0\.1:19083\/v1\/images\/[a-f0-9]{64}$/.test(value) ? value : '';
    if (value.indexOf('file://') === 0) value = value.slice(7);
    if (value.split('/').indexOf('..') !== -1 || /[\x00-\x1f]/.test(value)) return '';
    if (!/^\/(?:usr\/palm|media\/(?:cryptofs\/apps|developer\/apps)\/usr\/palm|mnt\/otncabi\/usr\/palm)\/applications\/[A-Za-z0-9_.-]+\/.+\.(?:png|jpe?g|webp)$/i.test(value)) return '';
    return 'file://' + value;
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
    points = next; images = artwork; lastSource = local ? 'local' : 'luna'; lastError = ''; 
    return points;
  }
  function refresh(done) {
    var xhr, finished = false;
    function fallback() {
      if (finished) return;
      finished = true;
      root.WiiTV.list(function (error, response) {
        if (error || !response || !Array.isArray(response.launchPoints)) {lastError = error && error.errorText || 'Application list unavailable'; done(error || {errorText: lastError}); return;}
        response.source = 'luna';
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
        if (xhr.status !== 200 || response.returnValue !== true || response.source !== 'local' || !Array.isArray(response.launchPoints)) {fallback(); return;}
        finished = true; done(null, accept(response));
      };
      xhr.send();
    } catch (e) {fallback();}
  }
  root.WiiLibrary = {refresh: refresh, accept: accept,
    entries: function () {return points;}, image: function (id) {return images[id] || null;},
    diagnostics: function () {return {source: lastSource, error: lastError, apps: points.length, withImages: Object.keys(images).length};}};
}(window));

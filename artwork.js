(function (root) {
  'use strict';
  var memo = Object.create(null), keys = [], saveTimer = null, deferredUntil = 0;
  var cacheKey = 'wiios.generated.artwork.v1', cacheLimit = 160 * 1024, maxEntries = 128;
  try {
    var raw = root.localStorage.getItem(cacheKey);
    var cached = raw && raw.length <= cacheLimit && JSON.parse(raw);
    if (Array.isArray(cached)) cached.slice(-maxEntries).forEach(function (entry) {
      if (!Array.isArray(entry) || typeof entry[0] !== 'string' || entry[0].length > 260 ||
          typeof entry[1] !== 'string' || entry[1].length > 4096 ||
          !/^data:image\/svg\+xml;charset=utf-8,[A-Za-z0-9_.~%-]+$/.test(entry[1]) || memo[entry[0]]) return;
      keys.push(entry[0]); memo[entry[0]] = entry[1];
    });
  } catch (ignore) {}
  function flush() {
    var delay = deferredUntil - Date.now();
    if (delay > 0) { saveTimer = root.setTimeout(flush, delay); return; }
    saveTimer = null;
    try {
      var cache = JSON.stringify(keys.map(function (key) {return [key, memo[key]];}));
      if (cache.length <= cacheLimit) root.localStorage.setItem(cacheKey, cache);
    } catch (ignore) {}
  }
  function remember(key, image) {
    memo[key] = image;
    keys.push(key);
    if (keys.length > maxEntries) delete memo[keys.shift()];
    if (saveTimer === null) saveTimer = root.setTimeout(flush, Math.max(0, deferredUntil - Date.now()));
  }
  function escape(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&apos;'}[c];
    });
  }
  function hex(id) {
    var value = 2166136261;
    for (var i = 0; i < id.length; i++) {
      value = Math.imul ? Math.imul(value ^ id.charCodeAt(i), 16777619) : (value * 33 + id.charCodeAt(i));
      value >>>= 0;
    }
    var h = value % 360;

    function hsv(hue, saturation, v) {
      var c = v * saturation, x = c * (1 - Math.abs((hue / 60) % 2 - 1));
      var m = v - c, p = hue < 60 ? [c,x,0] : hue < 120 ? [x,c,0] : hue < 180 ? [0,c,x] : hue < 240 ? [0,x,c] : hue < 300 ? [x,0,c] : [c,0,x];
      return '#' + p.map(function (part) { var n = Math.round((part + m) * 255).toString(16); return n.length < 2 ? '0' + n : n; }).join('');
    }
    return hsv(h, .7, .64);
  }
  function source(channel) {
    if (!channel || !channel.id) return '';
    var name = String(channel.name || channel.id).slice(0, 40);
    var key = JSON.stringify([channel.id, name]);
    if (memo[key]) return memo[key];
    var safe = escape(name), size = Math.min(49, Math.max(16, Math.floor(445 / (Math.max(1, name.length) * .65))));
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="280" viewBox="0 0 500 280">' +
      '<rect width="500" height="280" fill="' + hex(channel.id) + '"/>' +
      '<path d="M0 232 Q160 105 320 240 T560 96 V280 H0Z" fill="#fff" opacity=".12"/>' +
      '<circle cx="450" cy="-10" r="140" fill="#fff" opacity=".09"/>' +
      '<rect x="35" y="45" width="430" height="188" rx="35" fill="#fff" opacity=".11"/>' +
      '<text x="250" y="145" font-family="Arial,Helvetica,sans-serif" font-weight="bold" font-size="' + size + '" text-anchor="middle" fill="#fff">' + safe + '</text>' +
      '<text x="250" y="185" font-family="Arial,Helvetica,sans-serif" font-size="19" text-anchor="middle" fill="#fff" opacity=".78">WiiOS Channel</text></svg>';

    var image = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg).replace(/[!'()*]/g, function (c) {
      return '%' + c.charCodeAt(0).toString(16).toUpperCase();
    });
    remember(key, image);
    return image;
  }
  root.WiiArt = {source: source, deferSave: function (until) {deferredUntil = until;}};
}(window));

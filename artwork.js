(function (root) {
  'use strict';
  var memo = Object.create(null);
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
    var key = channel.id + ':' + name;
    if (memo[key]) return memo[key];
    var safe = escape(name), size = Math.min(49, Math.max(16, Math.floor(445 / (Math.max(1, name.length) * .65))));
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="280" viewBox="0 0 500 280">' +
      '<rect width="500" height="280" fill="' + hex(channel.id) + '"/>' +
      '<path d="M0 232 Q160 105 320 240 T560 96 V280 H0Z" fill="#fff" opacity=".12"/>' +
      '<circle cx="450" cy="-10" r="140" fill="#fff" opacity=".09"/>' +
      '<rect x="35" y="45" width="430" height="188" rx="35" fill="#fff" opacity=".11"/>' +
      '<text x="250" y="145" font-family="Arial,Helvetica,sans-serif" font-weight="bold" font-size="' + size + '" text-anchor="middle" fill="#fff">' + safe + '</text>' +
      '<text x="250" y="185" font-family="Arial,Helvetica,sans-serif" font-size="19" text-anchor="middle" fill="#fff" opacity=".78">WiiOS Channel</text></svg>';

    memo[key] = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg).replace(/[!'()*]/g, function (c) {
      return '%' + c.charCodeAt(0).toString(16).toUpperCase();
    });
    return memo[key];
  }
  root.WiiArt = {source: source};
}(window));

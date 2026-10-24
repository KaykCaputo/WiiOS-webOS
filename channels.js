(function (root) {
  'use strict';
  var catalog = [
    {name: 'Live TV', id: 'com.webos.app.livetv', theme: 'disc'},
    {name: 'YouTube', id: 'youtube.leanback.v4', theme: 'mii'},
    {name: 'Photos & Videos', id: 'com.webos.app.photovideo', theme: 'photos'},
    {name: 'LG Content Store', id: 'com.webos.app.discovery', theme: 'shop'},
    {name: 'Homebrew Channel', id: 'org.webosbrew.hbchannel', theme: 'shop'},
    {name: 'USB · Photos & Videos', id: 'com.webos.app.photovideo', theme: 'photos'},
    {name: 'USB · Music', id: 'com.webos.app.music', theme: 'music'},
    {name: 'Netflix', id: 'netflix', theme: 'weather'},
    {name: 'Prime Video', id: 'amazon', theme: 'news'},
    {name: 'Web Browser', id: 'com.webos.app.browser', theme: 'internet'},
    {name: 'Spotify', id: 'spotify-beehive', theme: 'music'},
    {name: 'Disney+', id: 'com.disney.disneyplus-prod', theme: 'weather'},
    {name: 'Globoplay', id: 'globoplaywebos', theme: 'photos'},
    {name: 'Crunchyroll', id: 'com.crunchyroll.webapp', theme: 'news'},
    {name: 'HBO Max', id: 'com.wbd.stream', theme: 'weather'},
    {name: 'HDMI 1', id: 'com.webos.app.hdmi1', theme: 'disc'},
    {name: 'HDMI 2', id: 'com.webos.app.hdmi2', theme: 'disc'},
    {name: 'HDMI 3', id: 'com.webos.app.hdmi3', theme: 'disc'},
    {name: 'HDMI 4 (if available)', id: 'com.webos.app.hdmi4', theme: 'disc'}
  ];
  var themes = ['disc', 'mii', 'photos', 'shop', 'weather', 'news', 'internet', 'music'];
  function empty() { return {name: 'Empty Channel', id: '', theme: 'empty', symbol: ''}; }
  function clean(value) {
    if (!value || typeof value !== 'object') return empty();
    var id = typeof value.id === 'string' ? value.id.trim().slice(0, 160) : '';
    if (!id || !/^[A-Za-z0-9_.-]+$/.test(id)) return empty();
    return {id: id, name: typeof value.name === 'string' ? value.name.slice(0, 40) : id,
      theme: themes.indexOf(value.theme) >= 0 ? value.theme : 'internet',
      symbol: typeof value.symbol === 'string' ? value.symbol.slice(0, 8) : ''};
  }
  function normalize(values) { var result = [], i; for (i = 0; i < 48; i++) result.push(clean(values && values[i])); return result; }
  function defaults(preview) {
    if (preview) return catalog.slice(0, 12);
    var entries = root.WiiLibrary ? root.WiiLibrary.entries() : [];
    var result = [];
    entries.forEach(function (entry) {
      var known = catalog.filter(function (c) { return c.id === entry.id; })[0];
      result.push(clean({id: entry.id, name: entry.name, theme: known ? known.theme : 'internet'}));
    });
    return result;
  }
  function fillUnused(values, preview) {
    var result = normalize(values), present = {};
    result.forEach(function(entry) { if (entry.id) present[entry.id] = true; });
    defaults(preview).forEach(function(entry) {
      if (present[entry.id]) return;
      var firstEmpty = result.findIndex(function(channel) { return !channel.id; });
      if (firstEmpty < 0) return;
      result[firstEmpty] = clean(entry); present[entry.id] = true;
    });
    return result;
  }
  function load(storage, preview) {
    var value;
    try {
      value = JSON.parse(storage.getItem(preview ? 'wiios.preview.v2' : 'wiios.channels.v2'));
      if (Array.isArray(value)) return {channels: normalize(value), fresh: false};
      value = JSON.parse(storage.getItem('wiios.channels.v1'));
      if (Array.isArray(value)) return {channels: normalize(value), fresh: false};
    } catch (ignore) {}
    return {channels: normalize(defaults(preview)), fresh: true};
  }
  root.WiiChannels = {catalog: catalog, themes: themes, empty: empty, clean: clean, normalize: normalize, load: load, fillUnused: fillUnused};
}(window));

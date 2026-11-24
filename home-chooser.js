(function (root) {
  'use strict';
  var cacheKey = 'wiios.homechooser.icons.v1', budget = 512 * 1024, maxIcon = 128 * 1024;
  var cached = Object.create(null), records = Object.create(null), order = [], bytes = 0;
  var available = false, busy = false, retryAt = 0;
  var status = null, checkedAt = 0, probing = [];
  function validId(id) { return typeof id === 'string' && /^[A-Za-z0-9_.-]{1,128}$/.test(id); }
  function validIcon(src) {
    return typeof src === 'string' && src.length <= maxIcon &&
      /^data:image\/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$/.test(src);
  }
  function remove(id) {
    if (!cached[id]) return;
    bytes -= cached[id].src.length;
    delete cached[id];
    order.splice(order.indexOf(id), 1);
  }
  function remember(id, key, src, background) {
    remove(id);
    var image = {choices: [{src: src, kind: 'icon', recommended: true, background: background}], background: background};
    cached[id] = {key: key, src: src, background: background, image: image};
    order.push(id);
    bytes += src.length;
    while (bytes > budget || order.length > 48) remove(order[0]);
  }
  function persist() {
    try {
      root.localStorage.setItem(cacheKey, JSON.stringify(order.map(function (id) {
        var entry = cached[id]; return [id, entry.key, entry.src, entry.background];
      })));
    } catch (ignore) {}
  }
  function color(value) {
    return typeof value === 'string' && /^#[a-f0-9]{6}$/i.test(value) ? value : '#eef0f2';
  }
  function loadCache() {
    try {
      var raw = root.localStorage.getItem(cacheKey);
      var entries = raw && raw.length <= budget + 65536 && JSON.parse(raw);
      if (Array.isArray(entries)) entries.slice(-48).forEach(function (entry) {
        if (Array.isArray(entry) && validId(entry[0]) && typeof entry[1] === 'string' &&
            entry[1].length <= 2300 && validIcon(entry[2])) remember(entry[0], entry[1], entry[2], color(entry[3]));
      });
    } catch (ignore) {}
  }
  function enabled() {return !!(root.WiiTV && root.WiiTV.isTV && root.WiiTV.chooserRequest);}
  function probe(done, force) {
    if (!enabled()) {if (done) done(null); return;}
    if (probing.length) {if (done) probing.push(done); return;}
    if (!force && checkedAt && Date.now() - checkedAt < 30000) {if (done) done(status); return;}
    probing.push(done);
    root.WiiTV.chooserRequest('getInfo', {}, function (error, info) {
      checkedAt = Date.now();
      status = !error && info ? info : null;
      var waiting = probing;
      probing = [];
      waiting.forEach(function (callback) {if (callback) callback(status);});
    });
  }
  function list(done) {
    if (!enabled()) {done({errorText: 'Home Chooser discovery is unavailable.'}); return;}
    var request = root.WiiTV.chooserRequest;
    probe(function (info) {
      available = false;
      if (!info || info.root !== true || info.permitted !== true || !(info.apiVersion >= 2)) {
        done({errorText: 'Home Chooser discovery requires an elevated service with API level 2 and app permission.'}); return;
      }
      request('listLaunchPoints', {}, function (failure, result) {
        if (failure || !result || !Array.isArray(result.launchPoints)) {
          done(failure || {errorText: 'Home Chooser returned no launch points.'}); return;
        }
        var next = Object.create(null), points = [], changed = false;
        result.launchPoints.slice(0, 512).forEach(function (entry) {
          if (!entry || !validId(entry.id) || next[entry.id] || entry.visible === false ||
              entry.lptype === 'bookmark' || entry.id === 'com.wiios.launcher' ||
              entry.id === 'com.webos.app.home' || entry.id === 'com.webos.app.fullhome') return;
          var size = !entry.icon && entry.largeIcon ? 'largeIcon' : 'icon';
          var background = color(entry.bgColor), launchPoint = validId(entry.launchPointId) ? entry.launchPointId : '';
          var key = JSON.stringify([launchPoint, String(entry[size] || '').slice(0, 2048), background]);
          next[entry.id] = {key: key, background: background,
            item: launchPoint ? {launchPointId: launchPoint, size: size} : {id: entry.id, size: size}};
          if (records[entry.id] && records[entry.id].key === key) next[entry.id].noIcon = records[entry.id].noIcon;
          points.push({id: entry.id, title: entry.title, visible: true});
        });
        if (!points.length) {done({errorText: 'Home Chooser returned no usable apps.'}); return;}
        order.slice().forEach(function (id) {
          if (!next[id] || cached[id].key !== next[id].key) {remove(id); changed = true;}
        });
        if (changed) persist();
        records = next; retryAt = 0; available = true;
        done(null, {source: 'home-chooser', launchPoints: points, artworkChanged: changed});
      });
    });
  }
  function icons(ids, done) {
    if (!available || busy || Date.now() < retryAt) {done(false); return;}
    var wanted = Object.create(null), requested = [];
    ids.forEach(function (id) {
      if (!records[id] || records[id].noIcon || wanted[id] || cached[id] || requested.length >= 12) return;
      wanted[id] = true; requested.push({id: id, record: records[id]});
    });
    if (!requested.length) {done(false); return;}
    busy = true;
    root.WiiTV.chooserRequest('getIcons', {items: requested.map(function (entry) {return entry.record.item;})}, function (error, result) {
      busy = false;
      var changed = false;
      if (error || !result || !Array.isArray(result.icons) || result.icons.length !== requested.length) {
        retryAt = Date.now() + 10000; done(false); return;
      }
      requested.forEach(function (entry, i) {
        var icon = result.icons[i], current = records[entry.id];
        if (!current || current.key !== entry.record.key || !icon) return;
        if (validIcon(icon.dataUrl)) {
          remember(entry.id, current.key, icon.dataUrl, current.background); changed = true;
        } else if (icon.errorCode !== 'overBudget') current.noIcon = true;
      });
      if (changed) persist();
      done(changed);
    });
  }
  if (enabled()) loadCache();
  root.WiiChooser = {enabled: enabled, probe: probe, list: list, icons: icons,
    isSelectedHome: function () {return !!(status && status.isSelectedHome === true);},
    image: function (id) {return cached[id] ? cached[id].image : null;}};
}(window));

(function (root) {
  'use strict';
  var pending = [];
  function request(method, parameters, done) {
    var bridge, timer, settled = false;
    function finish(error, result) {
      if (settled) return;
      settled = true; clearTimeout(timer);
      var index = pending.indexOf(bridge);
      if (index !== -1) pending.splice(index, 1);
      if (bridge) {
        bridge.onservicecallback = function () {};
        try { bridge.cancel(); } catch (ignore) {}
      }
      done(error, result);
    }
    if (typeof root.PalmServiceBridge !== 'function') {
      done({errorCode: 'PREVIEW', errorText: 'Browser preview. No application was launched.'});
      return {cancel: function () {}};
    }
    try {
      bridge = new root.PalmServiceBridge(); pending.push(bridge);
      bridge.onservicecallback = function (json) {
        var result;
        try { result = JSON.parse(json); } catch (error) {
          finish({errorCode: 'PARSE', errorText: 'Invalid TV response.'}); return;
        }
        if (!result || result.returnValue !== true) { finish(result || {errorText: 'Empty TV response.'}); return; }
        finish(null, result);
      };
      timer = setTimeout(function () { finish({errorCode: 'TIMEOUT', errorText: 'TV did not respond within 5 seconds.'}); }, 5000);
      bridge.call('luna://com.webos.applicationManager/' + method, JSON.stringify(parameters || {}));
    } catch (error) { finish({errorCode: 'BRIDGE', errorText: String(error.message || error)}); }
    return {cancel: function () { finish({errorCode: 'CANCELLED', errorText: 'Request canceled.'}); }};
  }
  function uninstall(id, done) {
    if (!/^[A-Za-z0-9_.-]+$/.test(id)) { done({errorText: 'Invalid app ID.'}); return; }
    if (typeof root.PalmServiceBridge !== 'function') { done({errorText: 'Uninstallation is unavailable in browser preview.'}); return; }
    var bridge, timer, finished = false;
    function finish(error, result) {
      if (finished) return;
      finished = true; clearTimeout(timer);
      if (bridge) { bridge.onservicecallback = function () {}; try { bridge.cancel(); } catch (ignore) {} }
      done(error, result);
    }
    try {
      bridge = new root.PalmServiceBridge();
      bridge.onservicecallback = function (json) {
        var result;
        try { result = JSON.parse(json); } catch (e) { finish({errorText: 'Invalid service response.'}); return; }
        if (result.returnValue === false) { finish(result); return; }

        if (result.statusValue === 31) { finish(null, {completed: true}); return; }
        if (result.statusValue === 25 || result.errorCode) { finish(result); }
      };
      timer = setTimeout(function () { finish({errorText: 'No uninstall completion confirmation received. Check LG Home.'}); }, 20000);
      bridge.call('luna://com.webos.appInstallService/remove', JSON.stringify({id: id, subscribe: true}));
    } catch (e) { finish({errorText: String(e.message || e)}); }
  }
  function canUninstall(id) {

    return !!id && /^[A-Za-z0-9_.-]+$/.test(id) &&
      id !== 'com.wiios.launcher' && id !== 'org.webosbrew.hbchannel' &&
      id !== 'com.disney.alch.prod.lrd.app-disabled-system' &&
      id.indexOf('com.webos.') !== 0 && id.indexOf('com.palm.') !== 0 &&
      !/^hdmi/i.test(id) && id.indexOf('usb') === -1 && id !== 'lgchannels.br';
  }
  root.WiiTV = {
    isTV: typeof root.PalmServiceBridge === 'function', request: request,
    list: function (done) { return request('listLaunchPoints', {}, done); },
    check: function (id, done) { return request('getAppLoadStatus', {appId: id}, done); },
    launch: function (id, done) { return request('launch', {id: id}, done); },
    uninstall: uninstall, canUninstall: canUninstall
  };
}(window));

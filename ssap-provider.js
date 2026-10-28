(function (root) {
  'use strict';
  var storageKey = 'wiios.ssap.pairing.v1', connection = null, timeoutMs = 7000;
  function validHost(host) {
    if (typeof host !== 'string' || !/^\d{1,3}(?:\.\d{1,3}){3}$/.test(host)) return false;
    var bytes = host.split('.').map(Number);
    if (bytes.some(function (n) {return n < 0 || n > 255;})) return false;
    return bytes[0] === 10 || bytes[0] === 192 && bytes[1] === 168 || bytes[0] === 172 && bytes[1] >= 16 && bytes[1] <= 31;
  }
  function load() {
    try {
      var item = JSON.parse(root.localStorage.getItem(storageKey) || '{}');
      if (validHost(item.host) && (item.transport === 'ws' || item.transport === 'wss') &&
          (!item.key || typeof item.key === 'string' && item.key.length <= 512)) return item;
    } catch (ignored) {}
    return null;
  }
  connection = load();
  function configure(host, secure) {
    if (!validHost(host)) return false;
    connection = {host: host, transport: secure ? 'wss' : 'ws', key: ''};
    try {root.localStorage.setItem(storageKey, JSON.stringify(connection));} catch (ignored) {}
    return true;
  }
  function disconnect() {
    connection = null;
    try {root.localStorage.removeItem(storageKey);} catch (ignored) {}
  }
  function sendRequest(uri, payload, done) {
    if (!connection || !root.WebSocket) {done({errorText: 'SSAP is not configured or supported.'}); return;}
    var settings = {host: connection.host, transport: connection.transport, key: connection.key};
    var socket, timer, finished = false, registered = false;
    function finish(error, value) {
      if (finished) return;
      finished = true;
      root.clearTimeout(timer);
      if (socket) {socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null; try {socket.close();} catch (ignored) {}}
      done(error, value);
    }
    try {
      socket = new root.WebSocket(settings.transport + '://' + settings.host + ':' + (settings.transport === 'wss' ? 3001 : 3000));
      timer = root.setTimeout(function () {finish({errorText: 'SSAP connection timed out.'});}, timeoutMs);
      socket.onerror = function () {finish({errorText: 'SSAP transport unavailable.'});};
      socket.onclose = function () {finish({errorText: 'SSAP connection closed.'});};
      socket.onopen = function () {
        var manifest = {manifestVersion: 1, appVersion: '1.0', signed: {appId: 'com.wiios.launcher', created: '2026-10-27', vendorId: 'WiiOS', localizedAppNames: {'': 'WiiOS'}, localizedVendorNames: {'': 'WiiOS'}, permissions: ['READ_INSTALLED_APPS']}, permissions: ['READ_INSTALLED_APPS']};
        var register = {type: 'register', id: 'wiios-register', payload: {pairingType: 'PROMPT', forcePairing: false, manifest: manifest}};
        if (settings.key) register.payload['client-key'] = settings.key;
        socket.send(JSON.stringify(register));
      };
      socket.onmessage = function (message) {
        var value;
        try {value = JSON.parse(message.data);} catch (ignored) {finish({errorText: 'Invalid SSAP response.'}); return;}
        if (!value || typeof value !== 'object') return;
        if (value.type === 'error') {finish({errorText: 'SSAP rejected the request.'}); return;}
        if (!registered && value.type === 'registered') {
          registered = true;
          var key = value.payload && value.payload['client-key'];
          if (typeof key === 'string' && key.length > 0 && key.length <= 512 && connection &&
              connection.host === settings.host && connection.transport === settings.transport) {
            connection.key = key;
            try {root.localStorage.setItem(storageKey, JSON.stringify(connection));} catch (ignored) {}
          }
          socket.send(JSON.stringify({type: 'request', id: 'wiios-request', uri: uri, payload: payload || {}}));
        } else if (registered && value.id === 'wiios-request' && value.type === 'response') {
          if (!value.payload || value.payload.returnValue === false) {finish({errorText: 'SSAP application access was denied.'}); return;}
          finish(null, value.payload);
        }
      };
    } catch (ignored) {finish({errorText: 'Could not open a TV-local SSAP connection.'});}
  }
  function list(done) {
    sendRequest('ssap://com.webos.applicationManager/listLaunchPoints', {}, function (error, data) {
      if (error) {done(error); return;}
      if (!Array.isArray(data.launchPoints)) {done({errorText: 'SSAP did not return launch points.'}); return;}
      done(null, {returnValue: true, source: 'ssap', launchPoints: data.launchPoints});
    });
  }
  function check(appId, done) {
    if (typeof appId !== 'string' || !/^[A-Za-z0-9_.-]{1,160}$/.test(appId)) {
      done({errorText: 'Invalid application ID.'}); return;
    }
    list(function (error, value) {
      if (error) {done(error); return;}
      done(null, {returnValue: true, exist: value.launchPoints.some(function (app) {
        return app && app.id === appId;
      })});
    });
  }
  function launch(appId, done) {
    if (typeof appId !== 'string' || !/^[A-Za-z0-9_.-]{1,160}$/.test(appId)) {
      done({errorText: 'Invalid application ID.'}); return;
    }
    sendRequest('ssap://com.webos.applicationManager/launch', {id: appId}, done);
  }
  function inputs(done) {
    sendRequest('ssap://tv/getExternalInputList', {}, function (error, data) {
      if (error) {done(error); return;}
      if (!Array.isArray(data.devices)) {done({errorText: 'TV inputs are not exposed by SSAP.'}); return;}
      done(null, data.devices.filter(function (item) {
        return item && typeof item.id === 'string' && /^HDMI_[1-9][0-9]?$/.test(item.id);
      }));
    });
  }
  function switchInput(inputId, done) {
    if (typeof inputId !== 'string' || !/^HDMI_[1-9][0-9]?$/.test(inputId)) {
      done({errorText: 'Invalid TV input identifier.'}); return;
    }
    inputs(function (error, devices) {
      if (error) {done(error); return;}
      if (!devices.some(function (entry) {return entry.id === inputId;})) {
        done({errorText: 'The requested input was not reported by the TV.'}); return;
      }
      sendRequest('ssap://tv/switchInput', {inputId: inputId}, done);
    });
  }
  root.WiiSSAP = {configure: configure, disconnect: disconnect, list: list, check: check, launch: launch, inputs: inputs, switchInput: switchInput,
    configured: function () {return !!(connection && connection.key);},
    address: function () {return connection ? connection.host : '';} };
}(window));

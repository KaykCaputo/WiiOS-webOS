(function (root) {
  'use strict';
  var music = new Audio(), context, gain, buffers = {}, loading = {}, sources = [], urls = {};
  var assets = root.WII_AUDIO_ASSETS || {}, unlocked = false, suspended = false;
  var preferences = {enabled: true, music: 0.35, effects: 0.6}, errors = {};
  var names = ['menu', 'hover', 'select', 'back', 'page', 'start'];
  try {
    var saved = JSON.parse(localStorage.getItem('wiios.audio.v2'));
    if (saved) {
      preferences.enabled = saved.enabled !== false;
      ['music', 'effects'].forEach(function (key) {
        if (typeof saved[key] === 'number') preferences[key] = Math.max(0, Math.min(1, saved[key]));
      });
    }
  } catch (ignore) {}
  music.loop = true; music.preload = 'auto'; music.volume = preferences.music;
  if (assets.menu) music.src = assets.menu;
  music.onerror = function () { errors.menu = 'Unable to play music.'; };
  function playMusic() {
    if (suspended || document.hidden || !preferences.enabled || !assets.menu || preferences.music === 0) return;
    try {
      var promise = music.play();
      if (promise && promise.catch) promise.catch(function () { errors.menu = 'Press OK to enable audio.'; });
    } catch (ignore) {}
  }
  music.onended = function () {
    if (suspended || document.hidden || !preferences.enabled || preferences.music === 0) return;
    try { music.currentTime = 0; } catch (ignore) {}
    playMusic();
  };
  function decode(key, data, done) {
    if (!context) { if (done) done('Web Audio unavailable.'); return; }
    context.decodeAudioData(data, function (buffer) {
      if (buffer.duration > 12) { errors[key] = 'Effects must be 12 seconds or shorter.'; if (done) done(errors[key]); return; }
      buffers[key] = buffer; delete errors[key]; if (done) done();
    }, function () { errors[key] = 'Unsupported audio format.'; if (done) done(errors[key]); });
  }
  function loadEffects() {
    names.slice(1).forEach(function (key) {
      if (!assets[key] || buffers[key] || loading[key]) return;
      loading[key] = true;
      var xhr = new XMLHttpRequest();
      xhr.open('GET', assets[key], true); xhr.responseType = 'arraybuffer'; xhr.timeout = 8000;
      xhr.onload = function () {
        if ((xhr.status === 0 || xhr.status === 200) && xhr.response) decode(key, xhr.response);
        else errors[key] = 'Sound file unavailable.';
      };
      xhr.onerror = xhr.ontimeout = function () { errors[key] = 'Unable to load sound effect.'; };
      xhr.send();
    });
  }
  function unlock() {
    unlocked = true;
    if (!context) {
      var AC = root.AudioContext || root.webkitAudioContext;
      if (AC) {
        try { context = new AC(); gain = context.createGain(); gain.gain.value = preferences.enabled ? preferences.effects : 0; gain.connect(context.destination); }
        catch (ignore) {}
      }
    }
    if (context && context.state === 'suspended') {
      var result = context.resume(); if (result && result.catch) result.catch(function () {});
    }
    if (context) loadEffects(); playMusic();
  }
  function effect(key) {
    if (!preferences.enabled || suspended || !context || !buffers[key] || sources.length >= 4) return;
    var source = context.createBufferSource(); source.buffer = buffers[key]; source.connect(gain); sources.push(source);
    source.onended = function () { var i = sources.indexOf(source); if (i >= 0) sources.splice(i, 1); source.disconnect(); };
    source.start(0);
  }
  function pause() {
    suspended = true; music.pause();
    sources.slice().forEach(function (source) { try { source.stop(); } catch (ignore) {} });
  }
  function resume() { if (document.hidden) return; suspended = false; playMusic(); }
  function set(key, value) {
    preferences[key] = key === 'enabled' ? !!value : Math.max(0, Math.min(1, Number(value) || 0));
    music.volume = preferences.music; if (gain) gain.gain.value = preferences.enabled ? preferences.effects : 0;
    if (!preferences.enabled || preferences.music === 0) music.pause(); else playMusic();
    try { localStorage.setItem('wiios.audio.v2', JSON.stringify(preferences)); } catch (ignore) {}
  }
  function importFile(key, file, done) {
    if (names.indexOf(key) < 0 || !file || !/\.(mp3|wav|ogg)$/i.test(file.name)) { done('Choose an MP3, WAV or OGG file.'); return; }
    if (file.size > (key === 'menu' ? 25 : 2) * 1024 * 1024) { done('File too large: music max 25 MB; effects max 2 MB.'); return; }
    unlock();
    if (key === 'menu') {
      music.pause(); if (urls.menu) URL.revokeObjectURL(urls.menu);
      urls.menu = URL.createObjectURL(file); assets.menu = urls.menu; music.src = urls.menu;
      delete errors.menu; playMusic(); done();
    } else {
      var reader = new FileReader(); reader.onload = function () { decode(key, reader.result, done); };
      reader.onerror = function () { done('Unable to read file.'); }; reader.readAsArrayBuffer(file);
    }
  }
  document.addEventListener('visibilitychange', function () { if (document.hidden) pause(); else resume(); });
  document.addEventListener('webOSRelaunch', resume);
  root.addEventListener('pageshow', resume); root.addEventListener('focus', resume); root.addEventListener('pagehide', pause);
  playMusic();
  root.WiiAudio = {unlock: unlock, effect: effect, pause: pause, resume: resume, set: set, importFile: importFile,
    preferences: preferences, names: names, status: function (key) { return errors[key] || (assets[key] || buffers[key] ? 'Loaded' : 'No file'); }};
}(window));

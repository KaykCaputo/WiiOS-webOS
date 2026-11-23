'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ASSETS = {
  menu: 'assets/audio/menu.mp3', hover: 'assets/audio/hover.mp3',
  select: 'assets/audio/select.mp3', back: 'assets/audio/back.mp3',
  page: 'assets/audio/page.mp3', start: 'assets/audio/start.mp3'
};

function environment(decode) {
  const requests = [];
  let music, plays = 0;
  function XMLHttpRequest() {
    requests.push(this);
    this.onload = this.onerror = this.ontimeout = null;
  }
  XMLHttpRequest.prototype.open = function () {};
  XMLHttpRequest.prototype.send = function () {};
  function Audio() {
    music = {
      loop: false, preload: '', volume: 1, paused: true,
      play() { plays++; this.paused = false; return {catch() {}}; },
      pause() { this.paused = true; }
    };
    return music;
  }
  function AudioContext() {
    this.state = 'running';
    this.resume = () => ({catch() {}});
    this.createGain = () => ({connect() {}, gain: {value: 1}});
    this.decodeAudioData = (data, ok, fail) => {
      if (decode === 'ok') ok({duration: 1});
      else fail();
    };
  }
  const window = {
    localStorage: {getItem: () => null, setItem() {}},
    WII_AUDIO_ASSETS: ASSETS,
    AudioContext,
    addEventListener() {},
    XMLHttpRequest,
    URL: {createObjectURL: () => 'blob:x', revokeObjectURL() {}}
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'audio.js'), 'utf8'),
    {window, document: {addEventListener() {}, hidden: false}, Audio, XMLHttpRequest, localStorage: window.localStorage,
     URL: window.URL, JSON, Object, Array, String, Math, RegExp, Number});
  return {window, requests, music, plays: () => plays};
}

test('navigation does not ask the browser to play already running music', () => {
  const {window, music, plays} = environment('ok');
  const audio = window.WiiAudio;
  audio.unlock();
  audio.unlock();
  assert.equal(plays(), 1);
  audio.pause();
  audio.resume();
  assert.equal(plays(), 2);
  music.onended();
  assert.equal(plays(), 3);
});

test('a failed load can be retried', () => {
  const {window, requests} = environment('fail');
  window.WiiAudio.unlock();
  assert.equal(requests.length, 5);
  requests.forEach(xhr => xhr.onerror());
  window.WiiAudio.unlock();
  assert.equal(requests.length, 10);
});

test('a decoded effect is cached and not requested again', () => {
  const {window, requests} = environment('ok');
  window.WiiAudio.unlock();
  assert.equal(requests.length, 5);
  requests.forEach(xhr => {
    xhr.status = 200; xhr.response = 'audio bytes'; xhr.onload();
  });
  window.WiiAudio.unlock();
  assert.equal(requests.length, 5);
});

test('a decode failure leaves the effect retryable', () => {
  const {window, requests} = environment('fail');
  window.WiiAudio.unlock();
  requests.forEach(xhr => {
    xhr.status = 200; xhr.response = 'audio bytes'; xhr.onload();
  });
  window.WiiAudio.unlock();
  assert.equal(requests.length, 10);
});

test('parallel unlocks never duplicate an in-flight request', () => {
  const {window, requests} = environment('ok');
  window.WiiAudio.unlock();
  window.WiiAudio.unlock();
  window.WiiAudio.unlock();
  assert.equal(requests.length, 5);
});

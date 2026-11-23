(function (root) {
  'use strict';
  var recording = null;
  function now() {return root.performance.now();}
  function sample(time) {
    if (!recording) return;
    if (recording.previous !== null && recording.intervals.length < 7200) {
      recording.intervals.push(time - recording.previous);
    }
    recording.previous = time;
    if (recording.intervals.length >= 7200) return;
    recording.frame = root.requestAnimationFrame(sample);
  }
  function start() {
    if (recording || root.document.hidden) return false;
    recording = {start: now(), previous: null, intervals: [], events: {}, frame: root.requestAnimationFrame(sample)};
    return true;
  }
  function mark(event) {
    if (recording) recording.events[event] = (recording.events[event] || 0) + 1;
  }
  function stop() {
    if (!recording) return null;
    var sample = recording, intervals = sample.intervals.slice().sort(function (a, b) {return a - b;});
    recording = null;
    root.cancelAnimationFrame(sample.frame);
    var total = intervals.reduce(function (sum, interval) {return sum + interval;}, 0);
    function percentile(value) {
      return intervals.length ? intervals[Math.max(0, Math.ceil(intervals.length * value) - 1)] : null;
    }
    return {measurement: 'requestAnimationFrame', renderer: root.document.getElementById('stage').classList.contains('strip-renderer') ? 'strip' : 'pages',
      viewport: [root.innerWidth, root.innerHeight], pixelRatio: root.devicePixelRatio || 1,
      seconds: (now() - sample.start) / 1000, intervals: intervals.length, sampleLimitReached: intervals.length >= 7200,
      hidden: root.document.hidden, fps: total > 0 ? intervals.length * 1000 / total : null,
      p50Ms: percentile(.50), p95Ms: percentile(.95), p99Ms: percentile(.99),
      over33Ms: intervals.filter(function (interval) {return interval > 33;}).length, events: sample.events};
  }
  root.WiiPerformance = {start: start, mark: mark, stop: stop};
}(window));

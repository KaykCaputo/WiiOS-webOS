(function (root) {
  'use strict';
  function mount(container, options) {
    var stopped = false, frame = null, poll = null, xhr = null, started = null, frames = 0;
    var labels = [['cpu', 'CPU'], ['memory', 'RAM'], ['temperature', 'TEMP'], ['fps', 'FPS']];
    var values = {}, table = document.createElement('dl'), note = document.createElement('p');
    table.className = 'stats-table'; note.className = 'sr-only';
    labels.forEach(function (item) {
      var title = document.createElement('dt'), value = document.createElement('dd');
      title.textContent = item[1]; value.textContent = '—'; values[item[0]] = value;
      var row = document.createElement('div'); row.className = 'stat-item stat-' + item[0];
      row.appendChild(title); row.appendChild(value); table.appendChild(row);
    });
    container.appendChild(table); container.appendChild(note);
    function unavailable() {
      values.cpu.textContent = '—'; values.memory.textContent = '—'; values.temperature.textContent = '—';
      note.textContent = options.isTV ? 'Device metrics unavailable. Interface FPS is measured locally.' : 'Browser preview: only interface FPS is measured. Device metrics require the collector on the TV.';
    }
    function number(value) {return typeof value === 'number' && isFinite(value);}
    function show(data) {
      if (!data || data.schema !== 1 || !number(data.sampledAt) || Math.abs(Date.now() - data.sampledAt) > 10000) {unavailable(); return;}
      values.cpu.textContent = number(data.cpuPercent) && data.cpuPercent >= 0 && data.cpuPercent <= 100 ? data.cpuPercent.toFixed(1) + '%' : '—';
      var m = data.memory;
      values.memory.textContent = m && number(m.usedKiB) && number(m.totalKiB) && m.usedKiB >= 0 && m.totalKiB > 0 && m.usedKiB <= m.totalKiB ? (m.usedKiB / 1024).toFixed(0) + ' / ' + (m.totalKiB / 1024).toFixed(0) + ' MiB' + (m.estimated ? ' (est.)' : '') : '—';
      values.temperature.textContent = number(data.temperatureC) && data.temperatureC >= -40 && data.temperatureC <= 150 && data.temperatureSensor ? data.temperatureC.toFixed(1) + ' °C' : '—';
      note.textContent = 'Updated every 2 seconds. Used memory excludes available memory. FPS measures WiiOS animation callbacks, not video or game frames.';
    }
    function update() {
      if (stopped || document.hidden || !options.isTV || xhr) return;
      var request = new XMLHttpRequest(); xhr = request;
      function done() {if (xhr === request) xhr = null;}
      request.open('GET', 'http://127.0.0.1:19083/v1/stats', true); request.timeout = 1500;
      request.onload = function () {
        done(); if (stopped || document.hidden) return;
        try {if (request.status !== 200) throw Error('status'); show(JSON.parse(request.responseText));} catch (e) {unavailable();}
      };
      request.onerror = request.ontimeout = function () {done(); if (!stopped) unavailable();};
      request.onabort = done;
      try {request.send();} catch (e) {done(); unavailable();}
    }
    function tick(time) {
      if (stopped || document.hidden) return;
      if (started === null) {started = time; frames = 0;} else frames++;
      if (time - started >= 2000) {
        values.fps.textContent = (frames * 1000 / (time - started)).toFixed(1);
        started = time; frames = 0;
      }
      frame = root.requestAnimationFrame(tick);
    }
    function visibility() {
      if (frame !== null) root.cancelAnimationFrame(frame);
      frame = null; started = null; frames = 0;
      clearInterval(poll); poll = null;
      if (document.hidden) {values.fps.textContent = '—'; if (xhr) xhr.abort();}
      else {frame = root.requestAnimationFrame(tick); update(); poll = setInterval(update, 2000);}
    }
    unavailable(); document.addEventListener('visibilitychange', visibility); visibility();
    return function () {
      stopped = true; clearInterval(poll);
      document.removeEventListener('visibilitychange', visibility);
      if (frame !== null) root.cancelAnimationFrame(frame);
      if (xhr) xhr.abort();
    };
  }
  root.WiiStats = {mount: mount};
}(window));

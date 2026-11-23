(function (root) {
  'use strict';
  function mount(container, options) {
    var stopped = false, frame = null, poll = null, xhr = null, started = null, frames = 0;
    var covered = !!options.covered;
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
    function display(node, text) {
      if (node.textContent !== text) node.textContent = text;
    }
    function unavailable() {
      display(values.cpu, '—'); display(values.memory, '—'); display(values.temperature, '—');
      display(note, options.isTV ? 'Device metrics unavailable. Interface FPS is measured locally.' : 'Browser preview: only interface FPS is measured. Device metrics require the collector on the TV.');
    }
    function number(value) {return typeof value === 'number' && isFinite(value);}
    function inactive() {return stopped || document.hidden || covered;}
    function show(data) {
      if (!data || data.schema !== 1 || !number(data.sampledAt) || Math.abs(Date.now() - data.sampledAt) > 10000) {unavailable(); return;}
      display(values.cpu, number(data.cpuPercent) && data.cpuPercent >= 0 && data.cpuPercent <= 100 ? data.cpuPercent.toFixed(1) + '%' : '—');
      var m = data.memory;
      display(values.memory, m && number(m.usedKiB) && number(m.totalKiB) && m.usedKiB >= 0 && m.totalKiB > 0 && m.usedKiB <= m.totalKiB ? (m.usedKiB / 1024).toFixed(0) + ' / ' + (m.totalKiB / 1024).toFixed(0) + ' MiB' + (m.estimated ? ' (est.)' : '') : '—');
      display(values.temperature, number(data.temperatureC) && data.temperatureC >= -40 && data.temperatureC <= 150 && data.temperatureSensor ? data.temperatureC.toFixed(1) + ' °C' : '—');
      display(note, 'Updated every 2 seconds. Used memory excludes available memory. FPS measures WiiOS animation callbacks, not video or game frames.');
    }
    function update() {
      if (inactive() || !options.isTV || xhr) return;
      var request = new XMLHttpRequest(); xhr = request;
      function done() {if (xhr === request) xhr = null;}
      request.open('GET', 'http://127.0.0.1:19083/v1/stats', true); request.timeout = 1500;
      request.onload = function () {
        done(); if (inactive()) return;
        try {if (request.status !== 200) throw Error('status'); show(JSON.parse(request.responseText));} catch (e) {unavailable();}
      };
      request.onerror = request.ontimeout = function () {done(); if (!inactive()) unavailable();};
      request.onabort = done;
      try {request.send();} catch (e) {done(); unavailable();}
    }
    function tick(time) {
      if (inactive()) return;
      if (started === null) {started = time; frames = 0;} else frames++;
      if (time - started >= 2000) {
        display(values.fps, (frames * 1000 / (time - started)).toFixed(1));
        started = time; frames = 0;
      }
      frame = root.requestAnimationFrame(tick);
    }
    function visibility() {
      if (frame !== null) root.cancelAnimationFrame(frame);
      frame = null; started = null; frames = 0;
      clearInterval(poll); poll = null;
      if (inactive()) {
        if (document.hidden) display(values.fps, '—');
        if (xhr) xhr.abort();
      } else {
        frame = root.requestAnimationFrame(tick);
        if (options.isTV) {update(); poll = setInterval(update, 2000);}
      }
    }
    unavailable(); document.addEventListener('visibilitychange', visibility); visibility();
    function stop() {
      stopped = true; clearInterval(poll);
      document.removeEventListener('visibilitychange', visibility);
      if (frame !== null) root.cancelAnimationFrame(frame);
      if (xhr) xhr.abort();
    }
    stop.setCovered = function (value) {
      if (stopped || covered === value) return;
      covered = value; visibility();
    };
    return stop;
  }
  root.WiiStats = {mount: mount};
}(window));

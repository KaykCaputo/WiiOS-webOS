(function (root) {
  'use strict';
  var request = new XMLHttpRequest();
  request.open('GET', 'wiios-home-session.json', true);
  request.timeout = 2000;
  request.onload = function () {
    if (request.status !== 0 && request.status !== 200) return;
    var session;
    try { session = JSON.parse(request.responseText); } catch (ignore) { return; }
    if (!session || !/^[a-f0-9]{64}$/.test(session.token) || !/^[a-f0-9]{64}$/.test(session.transactionId) ||
        !/^com\.webos\.app\.(home|fullhome)$/.test(session.appId)) return;
    function heartbeat() {
      if (root.WIIOS_UI_READY !== true || document.hidden || !document.getElementById('stage') || document.readyState !== 'complete') return;
      var update = new XMLHttpRequest();
      update.open('POST', 'http://127.0.0.1:19084/heartbeat', true);
      update.timeout = 2000;
      update.setRequestHeader('X-WiiOS-Token', session.token);
      update.setRequestHeader('Content-Type', 'application/json');
      update.send(JSON.stringify({appId: session.appId, transactionId: session.transactionId, uiReady: true}));
    }
    root.setInterval(heartbeat, 5000);
    document.addEventListener('visibilitychange', heartbeat);
    heartbeat();
  };
  request.send();
}(window));

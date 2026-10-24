(function () {
  'use strict';
  var TV = window.WiiTV, Model = window.WiiChannels, Sound = window.WiiAudio;
  var preview = !TV.isTV, storage;
  try { storage = window.localStorage; } catch (ignore) { storage = {getItem: function () { return null; }, setItem: function () { throw new Error('Storage unavailable'); }}; }
  var initial = Model.load(storage, preview), channels = initial.channels;
  var page = 0, selected = 0, mode = 'menu', carrying = -1, focusVisible = false;
  var returnFocus = null, dialogCleanup = null, dialogBack, dialogConfirm, toastTimer, tooltipTimer, dialogVersion = 0;
  var installed = [], scanning = false, lastScan = '', clockTimer, launchBusy = false, launchToken = 0;
  var revision = 0, reduced = false, statsVisible = true, statsCleanup = null;
  var holdTimer = null, holdIndex = -1, holdTriggered = false, okHeld = false;

  var suppressOkUntilRelease = false, suppressPointerClickUntil = 0;
  var HOLD_DELAY = 650;
  function $(id) { return document.getElementById(id); }
  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function save() {
    revision++;
    try { storage.setItem(preview ? 'wiios.preview.v2' : 'wiios.channels.v2', JSON.stringify(channels)); }
    catch (error) { toast('Change applied for this session; storage is unavailable.'); }
  }
  function toast(message) { clearTimeout(toastTimer); $('toast').textContent = message; $('toast').hidden = false; toastTimer = setTimeout(function () { $('toast').hidden = true; }, 5000); }
  function resize() {
    var scale = Math.min(window.innerWidth / 1280, window.innerHeight / 720);
    $('stage').style.transform = 'scale(' + scale + ')';
    $('stage').style.left = ((window.innerWidth - 1280 * scale) / 2) + 'px';
    $('stage').style.top = ((window.innerHeight - 720 * scale) / 2) + 'px';
  }

  function resolveAppImage(channelId) {
    return window.WiiLibrary.image(channelId);
  }

  var imagePreferences = Object.create(null);
  try {
    var savedImages = JSON.parse(storage.getItem('wiios.art.choice.v1'));
    if (savedImages && typeof savedImages === 'object' && !Array.isArray(savedImages)) {
      Object.keys(savedImages).forEach(function (id) {
        if (/^[A-Za-z0-9_.-]{1,160}$/.test(id) && Number.isInteger(savedImages[id]) && savedImages[id] >= -1 && savedImages[id] < 32) {
          imagePreferences[id] = savedImages[id];
        }
      });
    }
  } catch (ignore) {}
  function selectedImage(id) {
    var value = imagePreferences[id];
    var art = resolveAppImage(id);
    if (value === -1 || (art && value >= 0 && value < art.choices.length)) return value;
    if (!art) return -1;
    for (var i = 0; i < art.choices.length; i++) {
      if (art.choices[i].recommended !== false) return i;
    }

    return art.choices.length ? 0 : -1;
  }
  function cycleChannelImage() {
    var channel = channels[selected];
    if (!channel.id) return;
    var art = resolveAppImage(channel.id), total = art ? art.choices.length : 0;
    if (!total) { toast('No other artwork available for this app.'); closeDialog(); return; }
    var next = selectedImage(channel.id) + 1;
    if (next >= total) next = -1;
    imagePreferences[channel.id] = next;
    try { storage.setItem('wiios.art.choice.v1', JSON.stringify(imagePreferences)); }
    catch (ignore) { toast('Image changed for this session; storage unavailable.'); }
    closeDialog(); refreshArtwork();
    toast(next < 0 ? 'Using generated channel artwork.' : 'App image ' + (next + 1) + ' of ' + total + '.');
  }
  function appGlyph(channel) {
    var map = {
      'com.webos.app.browser': {symbol:'◎', className:'glyph-browser'},
      'com.webos.app.photovideo': {symbol:'▣', className:'glyph-photos'},
      'com.webos.app.music': {symbol:'♪', className:'glyph-music'},
      'org.webosbrew.hbchannel': {symbol:'HB', className:'glyph-homebrew'},
      'com.webos.app.discovery': {symbol:'Bag', className:'glyph-store'},
      'com.webos.app.homeconnect': {symbol:'HD', className:'glyph-dashboard'},
      'vero': {symbol:'V', className:'glyph-vero'},
      'globoplaywebos': {symbol:'G', className:'glyph-globoplay'},
      'com.crunchyroll.webapp': {symbol:'C', className:'glyph-crunchyroll'},
      'netflix': {symbol:'N', className:'glyph-netflix'},
      'com.wbd.stream': {symbol:'MAX', className:'glyph-max'},
      'lgchannels.br': {symbol:'LG', className:'glyph-lgchannels'}
    };
    return map[channel.id] || {symbol:(channel.name || '?').slice(0,2).toUpperCase(), className:'glyph-generic'};
  }
  function artwork(channel, key, fallback, choice, attempts) {
    var image = resolveAppImage(channel.id);
    var generated = window.WiiArt && window.WiiArt.source(channel);

    var generatedStyle = ''; 
    if (typeof choice !== 'number') choice = selectedImage(channel.id);
    attempts = attempts || 0;
    if (image && !fallback && choice >= 0 && image.choices[choice]) {
      var picture = image.choices[choice];
      return '<span class="art art-app art-app-' + picture.kind + '" style="background-color:' + escapeHtml((picture.kind === 'icon' && picture.background) || image.background) + ';' + (picture.kind === 'icon' ? generatedStyle : '') + '">' +
        '<img class="app-image" data-choice="' + choice + '" data-attempts="' + attempts + '" src="' + escapeHtml(picture.src) + '" alt="" draggable="false">' +
        '<span class="art-title">' + escapeHtml(channel.name) + '</span></span>';
    }
    var theme = channel.theme, content = '', id = 'disc-shine-' + key;
    if (channel.id && /^com\.webos\.app\.hdmi/.test(channel.id)) {
      return '<span class="art art-disc art-hdmi"><svg viewBox="0 0 250 140" aria-hidden="true"><defs><linearGradient id="' + id + '" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#f6f6f6"/><stop offset=".28" stop-color="#b4b6b7"/><stop offset=".49" stop-color="#eee"/><stop offset=".7" stop-color="#afb1b1"/><stop offset="1" stop-color="#fff"/></linearGradient></defs><circle cx="125" cy="65" r="49" fill="url(#' + id + ')" stroke="#c2c4c5" stroke-width="2"/><circle cx="125" cy="65" r="46" fill="none" stroke="#fdfdfd" stroke-width="2"/><circle cx="125" cy="65" r="14" fill="#ededed" stroke="#fafafa" stroke-width="3"/><circle cx="125" cy="65" r="8" fill="#fff" stroke="#ccc" stroke-width="2"/></svg><span class="art-title">' + escapeHtml(channel.name) + '</span></span>';
    }
    if (generated && channel.id) {
      return '<span class="art art-generated" style="background-image:url(' + generated + ')">' +
        '<span class="art-title">' + escapeHtml(channel.name) + '</span></span>';
    }
    if (!fallback && channel.id && !image && !/^com\.webos\.app\.hdmi/.test(channel.id)) {
      var label = escapeHtml(channel.name), glyph = appGlyph(channel);
      var hues = {'com.crunchyroll.webapp':'#f47521','com.wbd.stream':'#181449','org.webosbrew.hbchannel':'#a71258','com.webos.app.discovery':'#d7156d','globoplaywebos':'#ec153a','lgchannels.br':'#c10b2c','com.webos.app.browser':'#40bdf2','com.webos.app.photovideo':'#7c20d5','com.webos.app.music':'#6751d8','vero':'#154792','netflix':'#181818'};
      return '<span class="art art-app art-app-fallback" style="background-color:' + (hues[channel.id] || '#3a8db0') + '"><span class="app-card app-card-fallback"><span class="app-glyph ' + glyph.className + '">' + escapeHtml(glyph.symbol) + '</span></span><span class="art-title">' + label + '</span></span>';
    }
    if (theme === 'disc') {
      content = '<defs><linearGradient id="' + id + '" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#f6f6f6"/><stop offset=".28" stop-color="#b4b6b7"/><stop offset=".49" stop-color="#eee"/><stop offset=".7" stop-color="#afb1b1"/><stop offset="1" stop-color="#fff"/></linearGradient></defs><circle cx="125" cy="65" r="49" fill="url(#' + id + ')" stroke="#c2c4c5" stroke-width="2"/><circle cx="125" cy="65" r="46" fill="none" stroke="#fdfdfd" stroke-width="2"/><circle cx="125" cy="65" r="14" fill="#ededed" stroke="#fafafa" stroke-width="3"/><circle cx="125" cy="65" r="8" fill="#fff" stroke="#ccc" stroke-width="2"/>';
    } else if (theme === 'photos') {
      content = '<path d="M0 35h250v105H0z" fill="#b89573"/><g transform="translate(8 67) rotate(-9 45 30)"><path fill="#fff" d="M0 0h90v65H0z"/><path fill="#78c7eb" d="M5 5h80v52H5z"/><path fill="#f8fcff" d="M5 47l24-23 21 19 18-27 17 27v14H5z"/></g><g transform="translate(156 61) rotate(6 45 30)"><path fill="#fff" d="M0 0h90v65H0z"/><path fill="#4f7c1b" d="M5 5h80v52H5z"/><circle cx="45" cy="29" r="23" fill="#ffce19"/><circle cx="45" cy="29" r="10" fill="#f0a30f"/></g><g transform="translate(77 42) rotate(8 45 30)"><path fill="#fff" d="M0 0h91v72H0z"/><path fill="#7b9d39" d="M5 5h81v60H5z"/><g fill="#ee5836"><circle cx="45" cy="20" r="12"/><circle cx="60" cy="32" r="12"/><circle cx="51" cy="46" r="12"/><circle cx="34" cy="44" r="12"/><circle cx="30" cy="28" r="12"/></g><circle cx="44" cy="33" r="9" fill="#f5b235"/></g>';
    } else if (theme === 'shop') {
      content = '<g fill="#e1f9e9" transform="translate(172 9) rotate(4)"><rect width="60" height="35" rx="2"/><rect y="40" width="60" height="35" rx="2"/></g><g stroke="#00b9ec" stroke-width="4"><path d="M113 27V13q0-20 14 0v14M139 29V15q0-20 14 0v14" fill="none"/><path d="M97 24l66 7v64l-66-16z" fill="#fff"/><path d="M89 31l66 7v64l-66-16z" fill="#fff"/><path d="M80 39l66 7v64L80 95z" fill="#00b9ec"/></g><text x="111" y="79" fill="white" text-anchor="middle" font-family="Arial" font-size="18">Wii</text>';
    } else if (theme === 'news') {
      content = '<g fill="none" stroke="#5a9c32" opacity=".25"><ellipse cx="125" cy="89" rx="83" ry="42"/><ellipse cx="125" cy="89" rx="44" ry="42"/><path d="M42 89h166M125 47v84M52 68h146M52 110h146M67 74l22-16 27 8-5 20 25 10-20 23-11-21-24-9z"/></g>';
    } else if (theme === 'music') {
      content = '<g fill="none" stroke="#c8f5ff" opacity=".8"><circle cx="125" cy="70" r="66" stroke-width="3"/><circle cx="125" cy="70" r="48" stroke-width="2"/><path d="M125 4v132M59 70h132M78 23l94 94M78 117l94-94" stroke-width="2"/><circle cx="125" cy="70" r="23"/></g>';
    }
    return '<span class="art art-' + theme + '">' + (content ? '<svg viewBox="0 0 250 140" aria-hidden="true">' + content + '</svg>' : '') + '<span class="art-title">' + escapeHtml(channel.name) + '</span></span>';
  }
  function render() {
    var markup = '', p, i, idx, channel;
    for (p = 0; p < 4; p++) {
      markup += '<div class="channel-page" data-page="' + p + '" style="left:' + (p * 1096) + 'px">';
      for (i = 0; i < 12; i++) {
        idx = p * 12 + i; channel = channels[idx];
        markup += '<button id="slot-' + idx + '" class="channel' + (!channel.id ? ' empty' : '') + '" data-slot="' + idx + '" aria-label="' + escapeHtml(channel.name) + '" style="left:' + ((i % 4) * 268) + 'px;top:' + (Math.floor(i / 4) * 159) + 'px" tabindex="-1">' + (channel.id ? artwork(channel, idx) : '') + '</button>';
      }
      markup += '</div>';
    }
    $('menu').innerHTML = markup;
    Array.prototype.forEach.call($('menu').querySelectorAll('[data-slot]'), function (button) {
      var index = Number(button.getAttribute('data-slot'));
      button.onclick = function () {
        if (holdTriggered || Date.now() < suppressPointerClickUntil) { holdTriggered = false; return; }
        if (mode !== 'menu') return;
        if (Math.floor(index / 12) !== page) { switchPage(Math.floor(index / 12)); return; }
        selected = index; openChannel();
      };
      button.onfocus = function () { if (mode === 'menu' && Math.floor(index / 12) === page) { selected = index; focusVisible = true; highlight(); } };
      button.onmouseenter = function () {
        if (mode !== 'menu' || Math.floor(index / 12) !== page) return;
        if (selected !== index || !focusVisible) Sound.effect('hover');
        selected = index; focusVisible = true; highlight();
        clearTimeout(tooltipTimer); tooltipTimer = setTimeout(function () {
          if (mode !== 'menu') return; $('channel-tooltip').textContent = channels[index].name; $('channel-tooltip').hidden = false;
        }, 650);
      };
      button.onmouseleave = function () { hideTooltip(); cancelHold(); };
      button.onpointerdown = function (event) {
        if (event.pointerType === 'mouse' && event.button !== 0) return;
        if (mode !== 'menu' || carrying >= 0) return;
        selected = index; page = Math.floor(index / 12);
        startHold(index);
      };
      button.onpointerup = cancelHold;
      button.onpointercancel = cancelHold;
      button.oncontextmenu = function (event) {
        event.preventDefault(); cancelHold(); selected = index; openChannelOptions();
      };
    });
    bindImageFallbacks($('menu'));
    updatePage();
  }
  function bindImageFallbacks(container) {
    Array.prototype.forEach.call(container.querySelectorAll('.app-image'), function (image) {
      image.onerror = function () {
        var parent = image.parentNode.parentNode;
        var index = parent.id === 'channel-banner' ? selected : Number(parent.getAttribute('data-slot'));
        var art = resolveAppImage(channels[index].id);
        var attempted = Number(image.getAttribute('data-attempts')) + 1;
        var next = art && art.choices.length ? (Number(image.getAttribute('data-choice')) + 1) % art.choices.length : -1;
        parent.innerHTML = artwork(channels[index], 'fallback-' + index,
          !art || attempted >= art.choices.length, next, attempted);
        bindImageFallbacks(parent);
      };
    });
  }
  function hideTooltip() { clearTimeout(tooltipTimer); $('channel-tooltip').hidden = true; }
  function highlight() {
    for (var i = 0; i < 48; i++) {
      var button = $('slot-' + i);
      button.classList.toggle('selected', i === selected && focusVisible);
      button.classList.toggle('moving', i === carrying);
    }
  }
  function updatePage() {
    hideTooltip(); $('menu').style.transform = 'translateX(' + (-page * 1096) + 'px)';
    $('prev').disabled = page === 0; $('next').disabled = page === 3;
    $('page-label').textContent = 'Page ' + (page + 1) + ' of 4';
    for (var p = 0; p < 4; p++) {
      $('menu').children[p].setAttribute('aria-hidden', String(p !== page));
      for (var i = 0; i < 12; i++) $('slot-' + (p * 12 + i)).tabIndex = p === page ? 0 : -1;
    }
    highlight();
  }
  function focusChannel() { focusVisible = true; $('slot-' + selected).focus(); highlight(); }
  function switchPage(target) {
    if (mode !== 'menu' || target < 0 || target > 3 || target === page) return;
    selected = target * 12 + selected % 12; page = target; updatePage(); focusChannel(); Sound.effect('page');
  }
  function move(dx, dy) {
    var col = selected % 4, row = Math.floor((selected % 12) / 4);
    if (dy === 1 && row === 2 && carrying < 0) { focusVisible = false; highlight(); (col < 2 ? $('settings') : $('apps')).focus(); return; }
    if (col + dx < 0 && page > 0) { selected += 3; switchPage(page - 1); return; }
    if (col + dx > 3 && page < 3) { selected -= 3; switchPage(page + 1); return; }
    var next = page * 12 + Math.max(0, Math.min(2, row + dy)) * 4 + Math.max(0, Math.min(3, col + dx));
    if (next !== selected) Sound.effect('hover'); selected = next; focusChannel();
  }
  function cancelHold() { if (holdTimer) clearTimeout(holdTimer); holdTimer = null; holdIndex = -1; }
  function startHold(index) {
    cancelHold(); holdTriggered = false; holdIndex = index;
    holdTimer = setTimeout(function () {
      holdTimer = null;
      if (mode !== 'menu' || carrying >= 0 || holdIndex !== index) return;
      holdTriggered = true; suppressOkUntilRelease = true; suppressPointerClickUntil = Date.now() + 350; selected = index; openChannelOptions();
    }, HOLD_DELAY);
  }
  function openChannelOptions() {
    if (mode !== 'menu' || carrying >= 0) return;
    hideTooltip(); Sound.effect('select');
    var occupied = !!channels[selected].id;
    dialog('Channel Options', occupied ? channels[selected].name : 'Empty Channel',
      option('hold-move', 'Move', occupied ? 'Choose another slot' : 'Empty Channel') +
      option('hold-delete', 'Remove Shortcut', occupied ? 'Keep the app installed' : 'Empty channel') +
      option('hold-uninstall', 'Uninstall App', occupied ? 'Remove from the TV' : 'Empty channel') +
      option('hold-artwork', 'Change Channel Image', 'Cycle app icons or use generated artwork') +
      option('hold-exit', 'Exit', 'Back to Wii Menu'), '', null);
    $('hold-move').disabled = !occupied;
    $('hold-delete').disabled = !occupied;
    $('hold-uninstall').disabled = !occupied || !TV.canUninstall(channels[selected].id);
    $('hold-artwork').disabled = !occupied || !resolveAppImage(channels[selected].id) || !resolveAppImage(channels[selected].id).choices.length;
    $('hold-move').onclick = beginMove;
    $('hold-delete').onclick = function () {
      dialog('Remove shortcut?', 'The app will remain installed on the TV.', '', 'Remove Shortcut', function () {
        channels[selected] = Model.empty(); save(); closeDialog(); render(); focusChannel();
      }, openChannelOptions);
    };
    $('hold-uninstall').onclick = uninstallSelected;
    $('hold-artwork').onclick = cycleChannelImage;
    $('hold-exit').onclick = closeDialog;
    if (!occupied) $('hold-exit').focus();
  }
  function uninstallSelected() {
    var channel = channels[selected], appId = channel.id, name = channel.name;
    if (!appId || !/^[A-Za-z0-9_.-]+$/.test(appId) || !TV.canUninstall(appId)) {
      toast('This channel cannot be uninstalled.'); return;
    }
    dialog('Uninstall ' + name + '?',
      'Permanently uninstall this app from your TV? This is different from Remove Shortcut and may delete app data.',
      '<p class="note">App ID: ' + escapeHtml(appId) + '. This action cannot be undone.</p>',
      'Uninstall', function () {
        $('confirm').disabled = true;
        $('modal-info').textContent = 'Requesting uninstallation from webOS…';
        TV.uninstall(appId, function (error, result) {
          $('confirm').disabled = false;
          if (error || !result || !result.completed) {
            $('modal-info').textContent = 'Uninstallation was not confirmed. ' +
              (error && error.errorText ? error.errorText : 'The TV did not confirm removal. Use the LG Home edit mode or Homebrew Channel if access was denied.');
            return;
          }
          channels.forEach(function (entry, i) { if (entry.id === appId) channels[i] = Model.empty(); });
          installed = installed.filter(function (entry) { return entry.id !== appId; });
          save(); closeDialog(); render(); focusChannel(); toast(name + ' uninstalled successfully.');
        });
      }, openChannelOptions);
  }
  function closeDialog() {
    if (dialogCleanup) { dialogCleanup(); dialogCleanup = null; }
    dialogVersion++; $('overlay').hidden = true; mode = $('channel-screen').hidden ? 'menu' : 'channel';
    dialogConfirm = null; dialogBack = null;
    if (returnFocus && document.documentElement.contains(returnFocus)) returnFocus.focus();
    else if (mode === 'menu') focusChannel(); else $('channel-start').focus();
  }
  function dialog(title, info, markup, confirmLabel, confirm, back) {
    if (dialogCleanup) { dialogCleanup(); dialogCleanup = null; }
    if (mode !== 'dialog') returnFocus = document.activeElement;
    dialogVersion++; hideTooltip(); mode = 'dialog';
    $('modal-title').textContent = title; $('modal-info').textContent = info; $('modal-content').innerHTML = markup || '';
    $('confirm').textContent = confirmLabel || 'OK'; $('confirm').hidden = !confirm; $('confirm').disabled = false;
    dialogConfirm = confirm; dialogBack = back || closeDialog; $('overlay').hidden = false;
    var first = $('modal-content').querySelector('button, input, select'); (first || $('cancel')).focus();
    return dialogVersion;
  }
  function option(id, text, note) { return '<button class="option" id="' + id + '">' + escapeHtml(text) + (note ? '<small>' + escapeHtml(note) + '</small>' : '') + '</button>'; }
  function backHome() {
    launchToken++; launchBusy = false; $('channel-start').disabled = false; $('channel-start').textContent = 'Start';
    $('channel-screen').hidden = true; $('home').removeAttribute('aria-hidden'); mode = 'menu'; Sound.resume(); Sound.effect('back'); focusChannel();
  }
  function openChannel() {
    hideTooltip();
    if (carrying >= 0) {
      var source = channels[carrying]; channels[carrying] = channels[selected]; channels[selected] = source;
      carrying = -1; save(); render(); focusChannel(); Sound.effect('select'); return;
    }
    if (!channels[selected].id) { library(); return; }
    Sound.effect('select'); $('channel-banner').innerHTML = artwork(channels[selected], 'banner');
    bindImageFallbacks($('channel-banner'));
    $('channel-screen').hidden = false; $('home').setAttribute('aria-hidden', 'true'); mode = 'channel';
    $('channel-start').disabled = false; $('channel-start').textContent = 'Start'; $('channel-start').focus();
  }
  function launch() {
    if (launchBusy) return;
    if (preview) { toast('Preview: ' + channels[selected].name + '. Real launching works only on the TV.'); return; }
    launchBusy = true; var token = ++launchToken, app = channels[selected];
    $('channel-start').disabled = true; $('channel-start').textContent = 'Opening…';
    function failed(error) {
      if (token !== launchToken) return;
      launchBusy = false; $('channel-start').disabled = false; $('channel-start').textContent = 'Start'; Sound.resume();
      dialog('Unable to open', app.name + ': ' + (error.errorText || 'TV rejected the request.') + (error.errorCode !== undefined ? ' (' + error.errorCode + ')' : ''), '<p class="note">App IDs vary by model or region. System apps may reject a direct launch.</p>', 'Edit Channel', function () { edit(); }, closeDialog);
    }
    TV.check(app.id, function (error, result) {
      if (token !== launchToken) return;
      if (error) { failed(error); return; }
      if (!result.exist) { failed({errorText: 'This app is not installed.'}); return; }
      Sound.effect('start');
      TV.launch(app.id, function (launchError) {
        if (token !== launchToken) return;
        if (launchError) { failed(launchError); return; }
        launchBusy = false; backHome(); Sound.pause();
      });
    });
  }
  function edit() {
    var channel = channels[selected], themeOptions = '';
    var labels = ['Disc', 'Mii', 'Photos', 'Shop', 'Weather', 'News', 'Internet', 'Music'];
    Model.themes.forEach(function (theme, i) { themeOptions += '<option value="' + theme + '"' + (theme === channel.theme ? ' selected' : '') + '>' + labels[i] + '</option>'; });
    var version = dialog('Edit Channel ' + (selected + 1), 'Assign an app to this menu slot.',
      '<label class="field">Name<input id="edit-name" maxlength="40" value="' + escapeHtml(channel.id ? channel.name : '') + '"></label>' +
      '<label class="field">App ID<input id="edit-id" maxlength="160" value="' + escapeHtml(channel.id) + '" spellcheck="false"></label>' +
      '<label class="field">Fallback artwork (when no app image is available)<select id="edit-theme">' + themeOptions + '</select></label>', 'Save', function () {
        var id = $('edit-id').value.trim(), name = $('edit-name').value.trim(), theme = $('edit-theme').value;
        if (!id || !/^[A-Za-z0-9_.-]+$/.test(id)) { toast('Enter a valid app ID, e.g. youtube.leanback.v4.'); return; }
        function commit() {
          channels[selected] = Model.clean({id: id, name: name || id, theme: theme}); save(); closeDialog();
          if (mode === 'channel') backHome(); render(); focusChannel();
        }
        if (preview) { commit(); return; }
        $('confirm').disabled = true; $('modal-info').textContent = 'Checking app on TV…';
        TV.check(id, function (error, result) {
          if (version !== dialogVersion) return; $('confirm').disabled = false;
          if (error || !result.exist) { $('modal-info').textContent = error ? error.errorText : 'This ID is not an installed app.'; return; }
          commit();
        });
      });
  }
  function beginMove() {
    if (!channels[selected].id) { toast('Select a populated channel to move.'); return; }
    closeDialog(); if (mode === 'channel') backHome(); carrying = selected; focusChannel();
    toast('Select destination with arrows and press OK. Back cancels.');
  }
  function updateStats() {
    if (statsCleanup) { statsCleanup(); statsCleanup = null; }
    var container = $('footer-stats'); container.innerHTML = ''; container.hidden = !statsVisible;
    if (statsVisible) statsCleanup = window.WiiStats.mount(container, {isTV: TV.isTV});
  }
  function settings() {
    var markup = option('edit-choice', 'Edit Channel', channels[selected].name) + option('move-choice', 'Move Channel') +
      option('image-choice', 'Change Channel Image', 'Cycle through images from this TV') +
      option('library-choice', 'App Library') + option('audio-choice', 'Music & Sounds') +
      option('motion-choice', 'Animations: ' + (reduced ? 'reduced' : 'enabled')) + option('remove-choice', 'Clear This Channel') +
      option('stats-choice', 'Show stats: ' + (statsVisible ? 'On' : 'Off'), 'CPU · RAM · temperature · FPS') + option('about-choice', 'About WiiOS', preview ? 'Browser Preview · 0.3.30' : 'webOS App · 0.3.30');
    dialog('Wii Options', 'Customize your menu channels.', markup, '', null);
    $('edit-choice').onclick = edit; $('move-choice').onclick = beginMove;
    $('image-choice').disabled = !channels[selected].id || !resolveAppImage(channels[selected].id) || !resolveAppImage(channels[selected].id).choices.length;
    $('image-choice').onclick = cycleChannelImage; $('library-choice').onclick = library; $('audio-choice').onclick = audioSettings;
    $('stats-choice').onclick = function () {
      statsVisible = !statsVisible;
      try { storage.setItem('wiios.stats.visible', statsVisible ? 'on' : 'off'); } catch (ignore) {}
      updateStats(); settings(); $('stats-choice').focus();
    };
    $('motion-choice').onclick = function () { reduced = !reduced; $('stage').classList.toggle('reduced-motion', reduced); try { storage.setItem('wiios.motion', reduced ? 'reduced' : 'full'); } catch (ignore) {} settings(); };
    $('remove-choice').onclick = function () {
      dialog('Clear Channel', 'Remove shortcut for ' + channels[selected].name + '? The app will remain installed on the TV.', '', 'Clear', function () {
        channels[selected] = Model.empty(); save(); closeDialog(); render(); focusChannel();
      }, settings);
    };
    $('about-choice').onclick = function () {
      dialog('WiiOS 0.3.30', preview ? 'Preview mode: listed apps are examples.' : 'Independent launcher for webOS 4.5.',
        '<p class="note">Arrows: navigate · OK: select · Back: return<br>Yellow/Blue or PageUp/PageDown: pages<br>Red/E: edit · Green/M: move · S: options</p>' +
        '<p class="note">Home replacement and startup are managed separately by your TV configuration.</p>' +
        '<p class="note">Interface recreated in CSS/SVG. App images are loaded from this TV. Audio files are bundled locally. Community project unaffiliated with Nintendo or LG.</p>', '', null, settings);
    };
  }
  function refreshArtwork() {
    channels.forEach(function (channel, index) {
      if (channel.id) $('slot-' + index).innerHTML = artwork(channel, index);
    });
    bindImageFallbacks($('menu'));
    if (!$('channel-screen').hidden) {
      $('channel-banner').innerHTML = artwork(channels[selected], 'banner');
      bindImageFallbacks($('channel-banner'));
    }
  }
  function scan(done) {
    if (scanning) { done('A scan is already running.'); return; }
    scanning = true;
    window.WiiLibrary.refresh(function (error, entries) {
      if (!error) {
        installed = entries.map(function (entry) {
          var known = Model.catalog.filter(function (candidate) {return candidate.id === entry.id;})[0];
          return Model.clean({id: entry.id, name: entry.name, theme: known ? known.theme : 'internet'});
        });
        scanning = false;
        lastScan = installed.length + ' apps found on this TV.';
        refreshArtwork(); done(null); return;
      }
      var candidates = Model.catalog.concat(channels), seen = {}, next = 0, active = 0, finished = 0, confirmed = [], failures = 0;
      candidates = candidates.filter(function (item) {if (!item.id || seen[item.id]) return false; seen[item.id] = true; return true;});
      function pump() {
        if (finished === candidates.length) {
          scanning = false;
          if (failures === candidates.length) {
            lastScan = 'App discovery unavailable. Install the WiiOS TV helper or add apps manually.';
            done(lastScan); return;
          }
          installed = confirmed;
          lastScan = installed.length + ' known apps confirmed. Install the WiiOS TV helper for all apps and their images.';
          done(null); return;
        }
        while (active < 3 && next < candidates.length) {
          (function (candidate) {
            active++;
            TV.check(candidate.id, function (failure, response) {
              active--; finished++;
              if (failure) failures++;
              else if (response && response.exist === true) confirmed.push(candidate);
              pump();
            });
          }(candidates[next++]));
        }
      }
      pump();
    });
  }
  function library() {
    var list = preview ? Model.catalog : installed;
    var markup = option('fill-choice', 'Add Missing Apps to Empty Channels', 'Preserves existing channel positions.') + option('scan-choice', preview ? 'Demo Catalog' : 'Refresh Library', preview ? 'Example IDs; no TV is connected.' : 'Loads installed apps and images from this TV.') + option('manual-choice', 'Enter Another App');
    list.forEach(function (app, i) { markup += option('app-' + i, app.name, app.id); });
    var version = dialog('App Library', 'Choose an app for channel ' + (selected + 1) + '. ' + (preview ? '' : lastScan), markup, '', null);
    $('manual-choice').onclick = edit;
    $('fill-choice').onclick = function () {
      var missing = preview ? Model.catalog : installed;
      missing.forEach(function (entry) {
        if (channels.some(function (channel) {return channel.id === entry.id;})) return;
        var empty = channels.findIndex(function (channel) {return !channel.id;});
        if (empty >= 0) channels[empty] = Model.clean(entry);
      });
      save(); closeDialog(); render(); focusChannel(); toast('Missing apps added to empty channels.');
    };
    $('scan-choice').onclick = function () {
      if (preview) { toast('On TV, the library shows confirmed app IDs.'); return; }
      $('scan-choice').disabled = true; $('modal-info').textContent = 'Scanning apps…';
      scan(function (error) {
        if (dialogVersion !== version) return;
        library(); if (error) toast('Scan failed: ' + error);
      });
    };
    list.forEach(function (app, i) { $('app-' + i).onclick = function () { channels[selected] = Model.clean(app); save(); closeDialog(); render(); focusChannel(); Sound.effect('select'); }; });
  }
  function audioSettings() {
    var labels = {menu: 'Wii Menu Music', hover: 'Focus / Hover', select: 'Select Channel', back: 'Back', page: 'Change Page', start: 'Launch Channel'};
    var markup = option('audio-toggle', 'Sound: ' + (Sound.preferences.enabled ? 'on' : 'off')) +
      '<label class="field">Music Volume<input id="music-volume" type="range" min="0" max="100" step="5" value="' + Math.round(Sound.preferences.music * 100) + '"></label>' +
      '<label class="field">Effects Volume<input id="effects-volume" type="range" min="0" max="100" step="5" value="' + Math.round(Sound.preferences.effects * 100) + '"></label>';
    Sound.names.forEach(function (key) {
      markup += '<label class="field">' + labels[key] + ' · ' + escapeHtml(Sound.status(key)) + (preview ? '<input type="file" id="audio-' + key + '" accept=".mp3,.wav,.ogg">' : '') + '</label>';
    });
    markup += '<p class="note">' + (preview ? 'Selected files apply to this session. Put them in assets/audio and rebuild to use them on TV.' : 'Audio files are bundled from assets/audio.') + '</p>';
    dialog('Music & Sounds', 'Provide audio assets to enable Wii-style sounds.', markup, '', null);
    $('audio-toggle').onclick = function () { Sound.set('enabled', !Sound.preferences.enabled); audioSettings(); };
    $('music-volume').oninput = function () { Sound.set('music', this.value / 100); };
    $('effects-volume').oninput = function () { Sound.set('effects', this.value / 100); Sound.effect('hover'); };
    if (preview) Sound.names.forEach(function (key) { $('audio-' + key).onchange = function () {
      Sound.importFile(key, this.files[0], function (error) { toast(error || 'Audio loaded for this session.'); if (!error) Sound.effect(key); });
    }; });
  }
  function clock() {
    var date = new Date(), hours = ('0' + date.getHours()).slice(-2), minutes = ('0' + date.getMinutes()).slice(-2), digits = hours + minutes;
    var segments = ['1111110', '0110000', '1101101', '1111001', '0110011', '1011011', '1011111', '1110000', '1111111', '1111011'];
    var shapes = ['7,1 33,1 38,5 33,9 7,9 2,5', '35,11 40,6 40,29 36,33 32,29 32,15', '36,35 40,39 40,62 35,67 32,62 32,39', '7,63 31,63 36,68 31,72 7,72 2,68', '1,39 5,35 9,39 9,62 5,67 1,62', '1,6 5,11 9,15 9,29 5,33 1,29', '8,32 32,32 36,36 32,40 8,40 4,36'];
    var svg = '<svg viewBox="0 0 225 76" xmlns="http://www.w3.org/2000/svg"><g fill="#999c9c">';
    for (var i = 0; i < 4; i++) {
      svg += '<g transform="translate(' + (i * 48 + (i > 1 ? 22 : 0)) + ',0)">';
      for (var s = 0; s < 7; s++) if (segments[Number(digits[i])][s] === '1') svg += '<polygon points="' + shapes[s] + '"/>';
      svg += '</g>';
    }
    svg += '<circle cx="104" cy="24" r="4"/><circle cx="104" cy="50" r="4"/></g></svg>';
    $('clock').innerHTML = svg; $('clock').setAttribute('aria-label', hours + ':' + minutes);
    $('date').textContent = ('0' + date.getDate()).slice(-2) + '.' + ('0' + (date.getMonth() + 1)).slice(-2) + '. (' + ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][date.getDay()] + ')';
  }
  function dialogKeys(event, code) {
    var active = document.activeElement;
    var nodes = Array.prototype.filter.call($('overlay').querySelectorAll('button, input, select'), function (node) { return !node.disabled && !node.hidden && node.offsetHeight > 0; });
    var index = nodes.indexOf(active), direction = 0;
    if (code === 27 || code === 461 || (code === 8 && active.tagName !== 'INPUT')) { event.preventDefault(); Sound.effect('back'); dialogBack(); return; }
    if (code === 9) direction = event.shiftKey ? -1 : 1;
    else if (code === 38) direction = -1;
    else if (code === 40) direction = 1;
    else if (code === 37 || code === 39) {
      if (active.tagName === 'INPUT') return;
      if (active.tagName === 'SELECT') { event.preventDefault(); active.selectedIndex = Math.max(0, Math.min(active.options.length - 1, active.selectedIndex + (code === 37 ? -1 : 1))); return; }
      direction = code === 37 ? -1 : 1;
    } else if (code === 13 && (active.tagName === 'SELECT' || (active.tagName === 'INPUT' && active.type !== 'file'))) direction = 1;
    if (direction && nodes.length) { event.preventDefault(); nodes[(index + direction + nodes.length) % nodes.length].focus(); Sound.effect('hover'); }
  }
  document.addEventListener('keydown', function (event) {
    var code = event.keyCode || event.which; Sound.unlock(); hideTooltip();
    if (mode === 'dialog') {
      if (code === 13 && (suppressOkUntilRelease || okHeld)) { event.preventDefault(); event.stopPropagation(); return; }
      dialogKeys(event, code); return;
    }
    if (mode === 'menu' && code === 13 && document.activeElement && document.activeElement.hasAttribute('data-slot')) {
      if (!okHeld) { okHeld = true; startHold(selected); }
      event.preventDefault(); return;
    }
    if (mode === 'channel') {
      if (code === 27 || code === 461 || code === 8) { event.preventDefault(); backHome(); }
      else if (code === 37 || code === 39 || code === 9) { event.preventDefault(); (document.activeElement === $('channel-start') ? $('channel-back') : $('channel-start')).focus(); }
      else if (code === 13) { event.preventDefault(); if (!event.repeat) document.activeElement.click(); }
      return;
    }
    var footer = ['settings', 'audio-settings', 'apps'], footerIndex = footer.indexOf(document.activeElement.id);
    if (code >= 37 && code <= 40) {
      event.preventDefault();
      if (footerIndex >= 0) {
        if (code === 38) focusChannel();
        else if (code === 37 || code === 39) $(footer[Math.max(0, Math.min(2, footerIndex + (code === 37 ? -1 : 1)))]).focus();
      } else if (document.activeElement === $('prev') || document.activeElement === $('next')) focusChannel();
      else move(code === 37 ? -1 : code === 39 ? 1 : 0, code === 38 ? -1 : code === 40 ? 1 : 0);
    } else if (code === 13) { event.preventDefault(); if (!event.repeat) { if (footerIndex >= 0 || document.activeElement === $('prev') || document.activeElement === $('next')) document.activeElement.click(); else openChannel(); } }
    else if (code === 33 || code === 405 || code === 427) { event.preventDefault(); switchPage(page - 1); }
    else if (code === 34 || code === 406 || code === 428) { event.preventDefault(); switchPage(page + 1); }
    else if (code === 69 || code === 403) { event.preventDefault(); edit(); }
    else if (code === 77 || code === 404) { event.preventDefault(); beginMove(); }
    else if (code === 83) { event.preventDefault(); settings(); }
    else if (code === 27 || code === 461 || code === 8) {
      event.preventDefault();
      if (carrying >= 0) { carrying = -1; highlight(); toast('Move canceled.'); }
      else if (page > 0) switchPage(0);
      else dialog('Exit WiiOS?', 'Return to the TV interface?', '', 'Exit', function () { if (preview) { closeDialog(); toast('Close this browser tab to exit.'); } else { Sound.pause(); window.close(); } });
    }
  });
  document.addEventListener('keyup', function (event) {
    if ((event.keyCode || event.which) !== 13) return;
    if (suppressOkUntilRelease) {
      suppressOkUntilRelease = false; okHeld = false; holdTriggered = false;
      cancelHold(); event.preventDefault(); event.stopPropagation(); return;
    }
    if (!okHeld) return;
    okHeld = false; cancelHold(); event.preventDefault();
    if (holdTriggered) { holdTriggered = false; return; }
    if (mode === 'menu' && document.activeElement && document.activeElement.hasAttribute('data-slot')) openChannel();
  });
  window.addEventListener('blur', function () { cancelHold(); okHeld = false; suppressOkUntilRelease = false; });

  $('overlay').addEventListener('click', function (event) {
    if (suppressOkUntilRelease || (event.detail > 0 && Date.now() < suppressPointerClickUntil)) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener('mousedown', function () { Sound.unlock(); });
  $('prev').onclick = function () { switchPage(page - 1); }; $('next').onclick = function () { switchPage(page + 1); };
  $('settings').onclick = settings; $('apps').onclick = library; $('audio-settings').onclick = audioSettings;
  $('channel-back').onclick = backHome; $('channel-start').onclick = launch;
  $('cancel').onclick = function () { Sound.effect('back'); if (dialogBack) dialogBack(); };
  $('confirm').onclick = function () { if (dialogConfirm) { Sound.effect('select'); dialogConfirm(); } };
  window.addEventListener('resize', resize);
  document.addEventListener('visibilitychange', function () {
    $('stage').classList.toggle('backgrounded', document.hidden); clearInterval(clockTimer);
    if (!document.hidden) { clock(); clockTimer = setInterval(clock, 10000); }
  });
  document.addEventListener('webOSRelaunch', function () { if (mode === 'channel') backHome(); });
  try { reduced = storage.getItem('wiios.motion') === 'reduced'; } catch (ignore) {}
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) reduced = true;
  $('stage').classList.toggle('reduced-motion', reduced);
  try { statsVisible = storage.getItem('wiios.stats.visible') !== 'off'; } catch (ignore) {}
  updateStats();
  resize(); render(); clock(); clockTimer = setInterval(clock, 10000);
  var lastRefresh = 0;
  function refreshLibrary() {
    if (preview || scanning || Date.now() - lastRefresh < 10000) return;
    lastRefresh = Date.now();
    var scanRevision = revision;
    scan(function (error) {
      if (!error && initial.fresh && revision === scanRevision) {
        channels = Model.normalize(installed); initial.fresh = false; save(); render();
      }
    });
  }
  if (!preview) {
    refreshLibrary();
    document.addEventListener('visibilitychange', function () {if (!document.hidden) refreshLibrary();});
    document.addEventListener('webOSRelaunch', refreshLibrary);
  }
}());

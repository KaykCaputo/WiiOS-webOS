(function () {
  'use strict';
  var TV = window.WiiTV, Model = window.WiiChannels, Sound = window.WiiAudio;
  var thumbnails = window.WiiThumbnails;
  var measure = window.WiiPerformance ? window.WiiPerformance.mark : function () {};
  var preview = !TV.isTV, storage;
  try { storage = window.localStorage; } catch (ignore) { storage = {getItem: function () { return null; }, setItem: function () { throw new Error('Storage unavailable'); }}; }
  var initial = Model.load(storage, preview), channels = initial.channels;
  var page = 0, selected = 0, mode = 'menu', carrying = -1, focusVisible = false;
  var returnFocus = null, dialogCleanup = null, dialogControls = [], dialogBack, dialogConfirm, toastTimer, tooltipTimer, dialogVersion = 0;
  var installed = [], scannedEntries = null, scanning = false, lastScan = '', clockTimer, launchBusy = false, launchToken = 0;
  var catalogThemes = Object.create(null);
  Model.catalog.forEach(function (entry) {catalogThemes[entry.id] = entry.theme;});
  var revision = 0, reduced = false, statsVisible = true, statsCleanup = null;
  var holdTimer = null, holdIndex = -1, holdTriggered = false, okHeld = false;

  var suppressOkUntilRelease = false, suppressPointerClickUntil = 0;
  var HOLD_DELAY = 650;
  var slots = [], surfaces = [], slotArtwork = [], highlighted = -1, movingSlot = -1, pageTimer = null, returnTimer = null;
  var shownPage = -1, slideStart = 0, slideEnd = 0, stripRenderer = false;
  try { stripRenderer = storage.getItem('wiios.renderer') === 'strip'; } catch (ignore) {}
  var focusFrame = null, warmTimer = null, warmPage = 1;
  var pointerX = null, pointerY = null;
  var thumbnailTimer = null, thumbnailBusy = false, thumbnailReady = null, thumbnailDraw = null, artScale = 1;
  var lastGridInput = 0, libraryTimer = null, lastRefresh = 0;
  var artworkTimer = null, pendingArtwork = false, pendingIcons = false, fetchingIcons = false;
  var lastClock = '', lastDate = '';
  var lastWidth = 0, lastHeight = 0;
  var footerControls = ['settings', 'audio-settings', 'apps'];
  function $(id) { return document.getElementById(id); }
  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function save() {
    revision++;
    try { storage.setItem(preview ? 'wiios.preview.v2' : 'wiios.channels.v2', JSON.stringify(channels)); }
    catch (error) { toast('Change applied for this session; storage is unavailable.'); }
  }
  function toast(message) { clearTimeout(toastTimer); $('toast').textContent = message; $('toast').hidden = false; toastTimer = setTimeout(function () { $('toast').hidden = true; }, 5000); }
  function resize() {
    var width = window.innerWidth, height = window.innerHeight;
    if (width === lastWidth && height === lastHeight) return;
    lastWidth = width; lastHeight = height;
    var scale = Math.min(width / 1280, height / 720), stage = $('stage');
    var oldArtScale = artScale;
    artScale = scale * (window.devicePixelRatio || 1);
    stage.style.transform = 'scale(' + scale + ')';
    stage.style.left = ((width - 1280 * scale) / 2) + 'px';
    stage.style.top = ((height - 720 * scale) / 2) + 'px';
    if (thumbnails && artScale > oldArtScale) surfaces.forEach(function (surface) {
      releaseThumbnail(surface); attachThumbnail(surface);
    });
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
  function artwork(channel, fallback, choice, attempts, grid) {
    var image = resolveAppImage(channel.id);
    var generated;
    if (typeof choice !== 'number') choice = selectedImage(channel.id);
    attempts = attempts || 0;
    if (image && !fallback && choice >= 0 && image.choices[choice]) {
      var picture = image.choices[choice];
      return '<span class="art art-app art-app-' + picture.kind + '" style="background-color:' + escapeHtml((picture.kind === 'icon' && picture.background) || image.background) + ';">' +
        '<img class="app-image" data-choice="' + choice + '" data-attempts="' + attempts + '"' +
        (grid && thumbnails ? ' data-grid-src="' : ' src="') + escapeHtml(picture.src) + '" alt="" draggable="false">' +
        '<span class="art-title">' + escapeHtml(channel.name) + '</span></span>';
    }
    var theme = channel.theme, content = '', hdmi = /^com\.webos\.app\.hdmi/.test(channel.id);
    var disc = '<img class="disc-icon" src="assets/disc.svg" alt="" draggable="false">';
    if (hdmi) {
      return '<span class="art art-disc art-hdmi">' + disc + '<span class="art-title">' + escapeHtml(channel.name) + '</span></span>';
    }
    generated = window.WiiArt && window.WiiArt.source(channel);
    if (generated && channel.id) {
      return '<span class="art art-generated" style="background-image:url(' + generated + ')">' +
        '<span class="art-title">' + escapeHtml(channel.name) + '</span></span>';
    }
    if (!fallback && channel.id && !image) {
      var label = escapeHtml(channel.name), glyph = appGlyph(channel);
      var hues = {'com.crunchyroll.webapp':'#f47521','com.wbd.stream':'#181449','org.webosbrew.hbchannel':'#a71258','com.webos.app.discovery':'#d7156d','globoplaywebos':'#ec153a','lgchannels.br':'#c10b2c','com.webos.app.browser':'#40bdf2','com.webos.app.photovideo':'#7c20d5','com.webos.app.music':'#6751d8','vero':'#154792','netflix':'#181818'};
      return '<span class="art art-app art-app-fallback" style="background-color:' + (hues[channel.id] || '#3a8db0') + '"><span class="app-card app-card-fallback"><span class="app-glyph ' + glyph.className + '">' + escapeHtml(glyph.symbol) + '</span></span><span class="art-title">' + label + '</span></span>';
    }
    if (theme === 'photos') {
      content = '<path d="M0 35h250v105H0z" fill="#b89573"/><g transform="translate(8 67) rotate(-9 45 30)"><path fill="#fff" d="M0 0h90v65H0z"/><path fill="#78c7eb" d="M5 5h80v52H5z"/><path fill="#f8fcff" d="M5 47l24-23 21 19 18-27 17 27v14H5z"/></g><g transform="translate(156 61) rotate(6 45 30)"><path fill="#fff" d="M0 0h90v65H0z"/><path fill="#4f7c1b" d="M5 5h80v52H5z"/><circle cx="45" cy="29" r="23" fill="#ffce19"/><circle cx="45" cy="29" r="10" fill="#f0a30f"/></g><g transform="translate(77 42) rotate(8 45 30)"><path fill="#fff" d="M0 0h91v72H0z"/><path fill="#7b9d39" d="M5 5h81v60H5z"/><g fill="#ee5836"><circle cx="45" cy="20" r="12"/><circle cx="60" cy="32" r="12"/><circle cx="51" cy="46" r="12"/><circle cx="34" cy="44" r="12"/><circle cx="30" cy="28" r="12"/></g><circle cx="44" cy="33" r="9" fill="#f5b235"/></g>';
    } else if (theme === 'shop') {
      content = '<g fill="#e1f9e9" transform="translate(172 9) rotate(4)"><rect width="60" height="35" rx="2"/><rect y="40" width="60" height="35" rx="2"/></g><g stroke="#00b9ec" stroke-width="4"><path d="M113 27V13q0-20 14 0v14M139 29V15q0-20 14 0v14" fill="none"/><path d="M97 24l66 7v64l-66-16z" fill="#fff"/><path d="M89 31l66 7v64l-66-16z" fill="#fff"/><path d="M80 39l66 7v64L80 95z" fill="#00b9ec"/></g><text x="111" y="79" fill="white" text-anchor="middle" font-family="Arial" font-size="18">Wii</text>';
    } else if (theme === 'news') {
      content = '<g fill="none" stroke="#5a9c32" opacity=".25"><ellipse cx="125" cy="89" rx="83" ry="42"/><ellipse cx="125" cy="89" rx="44" ry="42"/><path d="M42 89h166M125 47v84M52 68h146M52 110h146M67 74l22-16 27 8-5 20 25 10-20 23-11-21-24-9z"/></g>';
    } else if (theme === 'music') {
      content = '<g fill="none" stroke="#c8f5ff" opacity=".8"><circle cx="125" cy="70" r="66" stroke-width="3"/><circle cx="125" cy="70" r="48" stroke-width="2"/><path d="M125 4v132M59 70h132M78 23l94 94M78 117l94-94" stroke-width="2"/><circle cx="125" cy="70" r="23"/></g>';
    }
    if (content) content = '<svg viewBox="0 0 250 140" aria-hidden="true">' + content + '</svg>';
    if (theme === 'disc') content = disc;
    return '<span class="art art-' + theme + '">' + content + '<span class="art-title">' + escapeHtml(channel.name) + '</span></span>';
  }
  function render() {
    if (slots.length) {
      for (var index = 0; index < slots.length; index++) {
        var slot = slots[index], entry = channels[index], empty = !entry.id;
        if (slot.getAttribute('aria-label') !== entry.name) slot.setAttribute('aria-label', entry.name);
        if (slot.classList.contains('empty') !== empty) slot.classList.toggle('empty', empty);
        if (slotArtwork[index]) paintSlot(index);
      }
      if (shownPage !== page) updatePage();
      else { hideTooltip(); highlight(); }
      return;
    }
    var markup = '', p, i, idx, channel;
    for (p = 0; p < 4; p++) {
      markup += '<div class="channel-page off-page" aria-hidden="true" data-page="' + p + '" style="left:' + (p * 1096) + 'px">';
      for (i = 0; i < 12; i++) {
        idx = p * 12 + i; channel = channels[idx];
        markup += '<button id="slot-' + idx + '" class="channel' + (!channel.id ? ' empty' : '') + '" data-slot="' + idx + '" aria-label="' + escapeHtml(channel.name) + '" style="left:' + ((i % 4) * 268) + 'px;top:' + (Math.floor(i / 4) * 159) + 'px" tabindex="-1">' + '<span class="channel-surface"></span></button>';
      }
      markup += '</div>';
    }
    $('channel-track').innerHTML = markup;
    slots = []; surfaces = []; slotArtwork = []; highlighted = -1; movingSlot = -1; shownPage = -1;
    Array.prototype.forEach.call($('menu').querySelectorAll('[data-slot]'), function (button) {
      var index = Number(button.getAttribute('data-slot'));
      slots[index] = button; surfaces[index] = button.firstChild;
      button.onclick = function () {
        if (holdTriggered || Date.now() < suppressPointerClickUntil) { holdTriggered = false; return; }
        if (mode !== 'menu') return;
        if (Math.floor(index / 12) !== page) { switchPage(Math.floor(index / 12)); return; }
        selected = index; openChannel();
      };
      button.onfocus = function () {
        if (mode === 'menu' && Math.floor(index / 12) === page && (selected !== index || !focusVisible)) {
          selected = index; focusVisible = true; highlight();
        }
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
    updatePage();
  }
  function fallbackImage(event) {
    var image = event.target;
    if (image.tagName !== 'IMG' || !image.classList.contains('app-image')) return;
    if (thumbnails && thumbnails.restore(image)) return;
    var parent = image.parentNode && image.parentNode.parentNode;
    if (!parent || !document.documentElement.contains(parent)) return;
    var index = parent.id === 'channel-banner' ? selected : Number(parent.parentNode.getAttribute('data-slot'));
    var art = resolveAppImage(channels[index].id);
    var attempted = Number(image.getAttribute('data-attempts')) + 1;
    var next = art && art.choices.length ? (Number(image.getAttribute('data-choice')) + 1) % art.choices.length : -1;
    var grid = parent.id !== 'channel-banner';
    if (grid) releaseThumbnail(parent);
    parent.innerHTML = artwork(channels[index],
      !art || attempted >= art.choices.length, next, attempted, grid);
    if (grid) attachThumbnail(parent);
  }
  function hideTooltip() {
    clearTimeout(tooltipTimer);
    tooltipTimer = null;
    var tooltip = $('channel-tooltip');
    if (!tooltip.hidden) tooltip.hidden = true;
  }
  function movePointer(event) {
    if (event.screenX === pointerX && event.screenY === pointerY) {measure('stationaryPointer'); return;}
    pointerX = event.screenX; pointerY = event.screenY;
    if (mode !== 'menu' || !event.target.closest) return;
    var button = event.target.closest('.channel');
    if (!button) return;
    var index = Number(button.getAttribute('data-slot'));
    if (Math.floor(index / 12) !== page) return;
    if (selected !== index || !focusVisible) {
      measure('pointerFocus');
      hideTooltip(); noteGridInput(); Sound.effect('hover');
      selected = index; focusVisible = true; queueHighlight();
    }
    if (tooltipTimer !== null || !$('channel-tooltip').hidden) return;
    tooltipTimer = setTimeout(function () {
      tooltipTimer = null;
      if (mode !== 'menu' || selected !== index) return;
      $('channel-tooltip').textContent = channels[index].name; $('channel-tooltip').hidden = false;
    }, 650);
  }
  function highlight() {
    if (focusFrame !== null) { window.cancelAnimationFrame(focusFrame); focusFrame = null; }
    if (shownPage !== page) updatePage();
    var next = focusVisible ? selected : -1;
    if (highlighted !== next) {
      measure('paintedFocus');
      if (slots[highlighted]) slots[highlighted].classList.remove('selected');
      if (slots[next]) slots[next].classList.add('selected');
      highlighted = next;
      syncChannelFocus();
    }
    if (movingSlot !== carrying) {
      if (slots[movingSlot]) slots[movingSlot].classList.remove('moving');
      if (slots[carrying]) slots[carrying].classList.add('moving');
      movingSlot = carrying;
    }
  }
  function queueHighlight() {
    if (!TV.isTV || reduced || document.hidden || !window.requestAnimationFrame) { highlight(); return; }
    if (focusFrame !== null || (shownPage === page && highlighted === (focusVisible ? selected : -1) && movingSlot === carrying)) return;
    focusFrame = window.requestAnimationFrame(function () { focusFrame = null; highlight(); });
  }
  function syncChannelFocus() {
    var menu = $('menu');
    if (document.activeElement !== menu) return;
    if (focusVisible) menu.setAttribute('aria-activedescendant', slots[selected].id);
    else menu.removeAttribute('aria-activedescendant');
  }
  function channelHasFocus() {
    var active = document.activeElement;
    return active && (active.id === 'menu' || active.hasAttribute('data-slot'));
  }
  function slotMarkup(index) {
    var channel = channels[index], image = resolveAppImage(channel.id);
    var preference = imagePreferences[channel.id], previous = slotArtwork[index];
    if (previous && previous.channel === channel && previous.image === image && previous.preference === preference) return null;
    var markup = channel.id ? artwork(channel, false, undefined, 0, true) : '';
    slotArtwork[index] = {channel: channel, image: image, preference: preference, markup: markup};
    return previous && previous.markup === markup ? null : markup;
  }
  function paintSlot(index) {
    var markup = slotMarkup(index);
    if (markup === null) return;
    releaseThumbnail(surfaces[index]);
    surfaces[index].innerHTML = markup;
    attachThumbnail(surfaces[index]);
  }
  function mountPageArtwork() {
    var pending = [], markup = '';
    for (var p = Math.max(0, slideStart - 1); p <= Math.min(3, slideEnd + 1); p++) {
      for (var index = p * 12; index < p * 12 + 12; index++) {
        if (slotArtwork[index] || !artworkInRange(p, index, slideStart, slideEnd)) continue;
        var art = slotMarkup(index);
        if (!art) continue;
        pending.push(index);
        markup += '<div>' + art + '</div>';
      }
    }
    if (!pending.length) return;
    measure('artworkBatch');
    var batch = document.createElement('div');
    batch.innerHTML = markup;
    for (var i = 0; i < pending.length; i++) {
      surfaces[pending[i]].appendChild(batch.children[i].firstChild);
      attachThumbnail(surfaces[pending[i]]);
    }
  }
  function artworkInRange(index, slot, start, end) {
    return (index >= start && index <= end) || (index === start - 1 && slot % 4 === 3) ||
      (index === end + 1 && slot % 4 === 0);
  }
  function releaseThumbnail(surface) {
    if (thumbnails) thumbnails.release(surface.querySelector('.app-image'));
  }
  function attachThumbnail(surface) {
    if (thumbnails) thumbnails.attach(surface.querySelector('.app-image'), artScale, queueThumbnails);
  }
  function queueThumbnails() {
    if (!thumbnails || thumbnailTimer !== null || (thumbnailBusy && !thumbnailDraw) ||
        document.hidden || mode !== 'menu' || pageTimer !== null) return;
    thumbnailTimer = setTimeout(processThumbnail, Math.max(40, 400 - (Date.now() - lastGridInput)));
  }
  function processThumbnail() {
    thumbnailTimer = null;
    if (document.hidden || mode !== 'menu' || pageTimer !== null) return;
    if (Date.now() - lastGridInput < 400) {queueThumbnails(); return;}
    if (thumbnailDraw) {
      var draw = thumbnailDraw; thumbnailDraw = null; draw(); return;
    }
    if (thumbnailReady) {thumbnailReady(); thumbnailReady = null;}
    thumbnailBusy = true;
    if (!thumbnails.prepare(function (draw) {
      thumbnailDraw = draw; queueThumbnails();
    }, function (apply) {
      thumbnailBusy = false; thumbnailReady = apply; queueThumbnails();
    })) thumbnailBusy = false;
  }
  function queuePageWarmup() {
    if (warmTimer !== null || document.hidden || mode !== 'menu' || pageTimer !== null || warmPage === page) return;
    warmTimer = setTimeout(warmNeighbor, Math.max(50, 400 - (Date.now() - lastGridInput)));
  }
  function warmNeighbor() {
    warmTimer = null;
    if (document.hidden || mode !== 'menu' || pageTimer !== null || shownPage !== page) return;
    if (Date.now() - lastGridInput < 400) { queuePageWarmup(); return; }
    var added = 0, outerPage = warmPage + (warmPage - page), targets = [warmPage, outerPage];
    for (var p = 0; p < targets.length; p++) {
      var target = targets[p];
      if (target < 0 || target > 3) continue;
      for (var index = target * 12; index < target * 12 + 12; index++) {
        if (slotArtwork[index] || !artworkInRange(target, index, warmPage, warmPage)) continue;
        if (added === 2) { queuePageWarmup(); return; }
        paintSlot(index);
        var image = surfaces[index].firstChild && surfaces[index].firstChild.firstChild;
        if (image && typeof image.decode === 'function') image.decode().catch(function () {});
        added++;
      }
    }
  }
  function trimPages() {
    pageTimer = null;
    slideStart = slideEnd = page;
    var pages = $('channel-track').children;
    var offset = pageOffset();
    for (var p = 0; p < 4; p++) {
      if (Math.abs(p - page) > 1) {
        if (pages[p].style.visibility !== 'hidden') pages[p].style.visibility = 'hidden';
        if (!stripRenderer) {
          pages[p].classList.add('parked');
          if (pages[p].style.transform !== offset) pages[p].style.transform = offset;
        }
      }
      for (var i = p * 12; i < p * 12 + 12; i++) {
        if (!slotArtwork[i] || artworkInRange(p, i, page, page) || artworkInRange(p, i, warmPage, warmPage)) continue;
        releaseThumbnail(surfaces[i]);
        if (surfaces[i].firstChild) surfaces[i].textContent = '';
        slotArtwork[i] = null;
      }
    }
    queuePageWarmup();
    queueThumbnails();
  }
  function noteGridInput() {
    lastGridInput = Date.now();
    if (window.WiiArt && window.WiiArt.deferSave) window.WiiArt.deferSave(lastGridInput + 400);
  }
  function setPageFocus(index, visible) {
    var element = $('channel-track').children[index];
    element.setAttribute('aria-hidden', String(!visible));
    element.classList.toggle('off-page', !visible);
    for (var i = index * 12; i < index * 12 + 12; i++) slots[i].tabIndex = visible ? 0 : -1;
  }
  function pageOffset() { return 'translateX(' + (-page * 1096) + 'px)'; }
  function updatePage() {
    hideTooltip();
    clearTimeout(pageTimer);
    clearTimeout(warmTimer);
    warmTimer = null;
    var track = $('channel-track'), pages = track.children;
    var previous = shownPage;
    if (shownPage !== page) {
      measure('paintedPage');
      if (shownPage >= 0) setPageFocus(shownPage, false);
      setPageFocus(page, true);
      shownPage = page;
    }
    if (previous >= 0) warmPage = page > previous ? page - 1 : page + 1;
    if (reduced || document.hidden || previous < 0) slideStart = slideEnd = page;
    else { slideStart = Math.min(slideStart, page); slideEnd = Math.max(slideEnd, page); }
    mountPageArtwork();
    var offset = pageOffset();
    if (stripRenderer && track.style.transform !== offset) track.style.transform = offset;
    for (var p = 0; p < pages.length; p++) {
      var sheet = pages[p], visible = p >= slideStart - 1 && p <= slideEnd + 1;
      if (!visible) {
        if (sheet.style.visibility !== 'hidden') sheet.style.visibility = 'hidden';
        continue;
      }
      if (sheet.style.visibility === 'hidden') sheet.style.visibility = '';
      if (!stripRenderer) {
        if (sheet.classList.contains('parked')) sheet.classList.remove('parked');
        if (sheet.style.transform !== offset) sheet.style.transform = offset;
      }
    }
    $('prev').disabled = page === 0; $('next').disabled = page === 3;
    $('page-label').textContent = 'Page ' + (page + 1) + ' of 4';
    if (reduced || document.hidden || previous < 0) trimPages(); else pageTimer = setTimeout(trimPages, 400);
    queueArtwork(false, true);
  }
  function coverMenu(covered) { $('stage').classList.toggle('menu-covered', covered); }
  function focusChannel(directional) {
    focusVisible = true;
    if (directional && TV.isTV) {
      var menu = $('menu');
      if (document.activeElement !== menu) {
        menu.setAttribute('aria-activedescendant', slots[selected].id);
        menu.focus({preventScroll: true});
      }
      queueHighlight();
      return;
    }
    if (shownPage !== page) updatePage();
    var slot = slots[selected];
    if (document.activeElement !== slot) slot.focus({preventScroll: true});
    highlight();
  }
  function switchPage(target) {
    if (mode !== 'menu' || target < 0 || target > 3 || target === page) return;
    measure('pageInput');
    noteGridInput();
    selected = target * 12 + selected % 12; page = target; focusChannel(true); Sound.effect('page');
  }
  function move(dx, dy) {
    measure('directionInput');
    noteGridInput();
    var col = selected % 4, row = Math.floor((selected % 12) / 4);
    if (dy === 1 && row === 2 && carrying < 0) { focusVisible = false; highlight(); (col < 2 ? $('settings') : $('apps')).focus(); return; }
    if (col + dx < 0 && page > 0) { selected += 3; switchPage(page - 1); return; }
    if (col + dx > 3 && page < 3) { selected -= 3; switchPage(page + 1); return; }
    var next = page * 12 + Math.max(0, Math.min(2, row + dy)) * 4 + Math.max(0, Math.min(3, col + dx));
    if (next !== selected) Sound.effect('hover'); selected = next; focusChannel(true);
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
          scannedEntries = null;
          save(); closeDialog(); render(); focusChannel(); toast(name + ' uninstalled successfully.');
        });
      }, openChannelOptions);
  }
  function closeDialog() {
    if (dialogCleanup) { dialogCleanup(); dialogCleanup = null; }
    dialogVersion++; $('overlay').hidden = true; mode = $('channel-screen').hidden ? 'menu' : 'channel';
    dialogConfirm = null; dialogBack = null; dialogControls = []; coverMenu(mode !== 'menu');
    if (returnFocus && document.documentElement.contains(returnFocus)) returnFocus.focus();
    else if (mode === 'menu') focusChannel(); else $('channel-start').focus();
    if (mode === 'menu') { queueArtwork(false, true); queuePageWarmup(); queueThumbnails(); }
  }
  function dialog(title, info, markup, confirmLabel, confirm, back) {
    if (dialogCleanup) { dialogCleanup(); dialogCleanup = null; }
    if (mode !== 'dialog') returnFocus = document.activeElement;
    dialogVersion++; hideTooltip(); mode = 'dialog'; coverMenu(true);
    $('modal-title').textContent = title; $('modal-info').textContent = info; $('modal-content').innerHTML = markup || '';
    $('confirm').textContent = confirmLabel || 'OK'; $('confirm').hidden = !confirm; $('confirm').disabled = false;
    dialogConfirm = confirm; dialogBack = back || closeDialog; $('overlay').hidden = false;
    dialogControls = Array.prototype.slice.call($('overlay').querySelectorAll('button, input, select'));
    var first = $('modal-content').querySelector('button, input, select'); (first || $('cancel')).focus();
    return dialogVersion;
  }
  function option(id, text, note) { return '<button class="option" id="' + id + '">' + escapeHtml(text) + (note ? '<small>' + escapeHtml(note) + '</small>' : '') + '</button>'; }
  function backHome() {
    launchToken++; launchBusy = false; $('channel-start').disabled = false; $('channel-start').textContent = 'Start';
    $('channel-screen').hidden = true; $('channel-banner').textContent = '';
    if (statsCleanup) statsCleanup.setCovered(false);
    $('home').removeAttribute('aria-hidden'); mode = 'menu'; coverMenu(false);
    clearTimeout(returnTimer);
    $('home').classList.toggle('returning', !reduced && !document.hidden);
    returnTimer = setTimeout(function () { $('home').classList.remove('returning'); }, 240);
    Sound.resume(); Sound.effect('back'); focusChannel();
    queueArtwork(false, true);
    queuePageWarmup();
    queueThumbnails();
  }
  function openChannel() {
    hideTooltip();
    if (shownPage !== page) highlight();
    if (carrying >= 0) {
      var source = channels[carrying]; channels[carrying] = channels[selected]; channels[selected] = source;
      carrying = -1; save(); render(); focusChannel(); Sound.effect('select'); return;
    }
    if (!channels[selected].id) { library(); return; }
    Sound.effect('select'); $('channel-banner').innerHTML = artwork(channels[selected]);
    $('channel-screen').style.transformOrigin = (108 + (selected % 4) * 268 + 126) + 'px ' + (50 + Math.floor((selected % 12) / 4) * 159 + 72) + 'px';
    coverMenu(true); $('channel-screen').hidden = false; $('home').setAttribute('aria-hidden', 'true'); mode = 'channel';
    if (statsCleanup) statsCleanup.setCovered(true);
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
    function start() {
      Sound.effect('start');
      TV.launch(app.id, function (launchError) {
        if (token !== launchToken) return;
        if (launchError) { failed(launchError); return; }
        launchBusy = false; backHome(); Sound.pause();
      });
    }
    if (window.WiiLibrary.listedByChooser(app.id)) {start(); return;}
    TV.check(app.id, function (error, result) {
      if (token !== launchToken) return;
      if (error) { failed(error); return; }
      if (!result.exist) { failed({errorText: 'This app is not installed.'}); return; }
      start();
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
    if (statsVisible) statsCleanup = window.WiiStats.mount(container, {isTV: TV.isTV, covered: !$('channel-screen').hidden});
  }
  function settings() {
    var uiVersion = typeof window.WIIOS_VERSION === 'string' ? window.WIIOS_VERSION : 'development';
    var markup = option('edit-choice', 'Edit Channel', channels[selected].name) + option('move-choice', 'Move Channel') +
      option('image-choice', 'Change Channel Image', 'Cycle through images from this TV') +
      option('library-choice', 'App Library') + option('ssap-choice', 'TV Pairing for App Catalog', window.WiiSSAP && window.WiiSSAP.configured() ? 'Connected to ' + window.WiiSSAP.address() : 'Optional pairing when Luna is restricted') + option('audio-choice', 'Music & Sounds') +
      option('motion-choice', 'Animations: ' + (reduced ? 'reduced' : 'enabled')) + option('remove-choice', 'Clear This Channel') +
      option('stats-choice', 'Show stats: ' + (statsVisible ? 'On' : 'Off'), 'CPU · RAM · temperature · FPS') + option('about-choice', 'About WiiOS', preview ? 'Browser Preview · ' + uiVersion : 'webOS App · ' + uiVersion);
    if (TV.isTV) {
      markup = option('home-chooser-choice', 'Use WiiOS as Home', 'Open Home Chooser to confirm') + markup;
    }
    dialog('Wii Options', 'Customize your menu channels.', markup, '', null);
    if ($('home-chooser-choice')) $('home-chooser-choice').onclick = openHomeChooser;
    $('edit-choice').onclick = edit; $('move-choice').onclick = beginMove;
    $('image-choice').disabled = !channels[selected].id || !resolveAppImage(channels[selected].id) || !resolveAppImage(channels[selected].id).choices.length;
    $('image-choice').onclick = cycleChannelImage; $('library-choice').onclick = library; $('ssap-choice').onclick = ssapSettings; $('audio-choice').onclick = audioSettings;
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
      dialog('WiiOS ' + uiVersion, preview ? 'Preview mode: listed apps are examples.' : 'Independent launcher for LG webOS.',
        '<p class="note">Arrows: navigate · OK: select · Back: return<br>Yellow/Blue or PageUp/PageDown: pages<br>Red/E: edit · Green/M: move · S: options</p>' +
        '<p class="note">Home replacement and startup are managed separately by your TV configuration.</p>' +
        '<p class="note">Interface recreated in CSS/SVG. App images are loaded from this TV. Audio files are bundled locally. Community project unaffiliated with Nintendo or LG.</p>', '', null, settings);
    };
  }
  function openHomeChooser() {
    var button = $('home-chooser-choice'), version = dialogVersion;
    button.disabled = true;
    TV.request('launch', {id: 'org.webosbrew.homechooser', params: {request: 'com.wiios.launcher'}}, function (error) {
      if (version !== dialogVersion) return;
      button.disabled = false;
      button.focus();
      if (error) toast('Open Home Chooser from the TV app list. Install it from Homebrew Channel if it is missing.');
    });
  }
  function ssapSettings() {
    if (!window.WiiSSAP) {toast('This firmware does not support SSAP pairing.'); return;}
    var current = window.WiiSSAP.address();
    var markup = '<label for="ssap-address">TV IPv4 address (local network only)</label>' +
      '<input id="ssap-address" type="text" autocomplete="off" maxlength="15" value="' + escapeHtml(current) + '" placeholder="192.168.1.10">' +
      '<label><input id="ssap-secure" type="checkbox" checked> Secure WebSocket (WSS port 3001)</label>' +
      '<p class="note">WSS is preferred. WS sends pairing traffic without transport encryption and should only be used on a trusted local network when WSS is unavailable. The client key is kept in local WiiOS application storage until Remove Pairing is selected.</p>' +
      option('ssap-remove', 'Remove Pairing', 'Delete the stored connection and client key');
    dialog('TV Catalog Pairing', 'Optional app discovery when the local helper and Luna are unavailable.', markup, 'Pair', function () {
      var address = $('ssap-address').value.trim();
      if (!window.WiiSSAP.configure(address, $('ssap-secure').checked)) {toast('Use a private IPv4 address on your local network.'); return;}
      $('confirm').disabled = true;
      window.WiiSSAP.list(function (error) {
        if (error) {window.WiiSSAP.disconnect(); toast('TV pairing failed or was denied.'); $('confirm').disabled = false; return;}
        toast('TV paired. Refresh the App Library.'); settings();
      });
    }, settings);
    $('ssap-remove').onclick = function () {window.WiiSSAP.disconnect(); settings(); toast('TV pairing removed.');};
  }
  function refreshArtwork() {
    slotArtwork.forEach(function (current, index) {
      if (current) paintSlot(index);
    });
    if (!$('channel-screen').hidden) {
      $('channel-banner').innerHTML = artwork(channels[selected]);
    }
  }
  function queueArtwork(repaint, fetchIcons) {
    pendingArtwork = pendingArtwork || repaint;
    pendingIcons = pendingIcons || !!(fetchIcons && window.WiiChooser && window.WiiChooser.enabled());
    if (artworkTimer !== null || document.hidden || mode !== 'menu' ||
        (!pendingArtwork && (!pendingIcons || fetchingIcons))) return;
    artworkTimer = setTimeout(flushArtwork, Math.max(0, 400 - (Date.now() - lastGridInput)));
  }
  function flushArtwork() {
    artworkTimer = null;
    if (document.hidden || mode !== 'menu' || Date.now() - lastGridInput < 400) {
      queueArtwork(false, false); return;
    }
    if (pendingArtwork) {pendingArtwork = false; refreshArtwork();}
    if (!pendingIcons || fetchingIcons) return;
    pendingIcons = false;
    if (window.WiiLibrary.diagnostics().source !== 'home-chooser') return;
    fetchingIcons = true;
    window.WiiChooser.icons(channels.slice(page * 12, page * 12 + 12).map(function (channel) {
      return channel.id;
    }), function (changed) {
      fetchingIcons = false; queueArtwork(changed, false);
    });
  }
  function scan(done) {
    if (scanning) { done('A scan is already running.'); return; }
    scanning = true;
    var artVersion = window.WiiLibrary.artworkVersion();
    window.WiiLibrary.refresh(function (error, entries) {
      if (!error) {
        if (entries !== scannedEntries) {
          installed = entries.map(function (entry) {
            return Model.clean({id: entry.id, name: entry.name, theme: catalogThemes[entry.id] || 'internet'});
          });
          scannedEntries = entries;
        }
        scanning = false;
        lastScan = installed.length + ' apps found on this TV.';
        queueArtwork(window.WiiLibrary.artworkVersion() !== artVersion, true);
        done(null); return;
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
          scannedEntries = null;
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
  function clockFace(digits) {
    var segments = ['1111110', '0110000', '1101101', '1111001', '0110011', '1011011', '1011111', '1110000', '1111111', '1111011'];
    var shapes = ['7,1 33,1 38,5 33,9 7,9 2,5', '35,11 40,6 40,29 36,33 32,29 32,15', '36,35 40,39 40,62 35,67 32,62 32,39', '7,63 31,63 36,68 31,72 7,72 2,68', '1,39 5,35 9,39 9,62 5,67 1,62', '1,6 5,11 9,15 9,29 5,33 1,29', '8,32 32,32 36,36 32,40 8,40 4,36'];
    var svg = '<svg viewBox="0 0 225 76" xmlns="http://www.w3.org/2000/svg"><g fill="#999c9c">';
    for (var i = 0; i < 4; i++) {
      svg += '<g transform="translate(' + (i * 48 + (i > 1 ? 22 : 0)) + ',0)">';
      for (var s = 0; s < 7; s++) if (segments[Number(digits[i])][s] === '1') svg += '<polygon points="' + shapes[s] + '"/>';
      svg += '</g>';
    }
    return svg + '<circle cx="104" cy="24" r="4"/><circle cx="104" cy="50" r="4"/></g></svg>';
  }
  function clock() {
    var date = new Date(), hours = ('0' + date.getHours()).slice(-2), minutes = ('0' + date.getMinutes()).slice(-2), digits = hours + minutes;
    if (digits !== lastClock) {
      $('clock').innerHTML = clockFace(digits); $('clock').setAttribute('aria-label', hours + ':' + minutes); lastClock = digits;
    }
    var dateLabel = ('0' + date.getDate()).slice(-2) + '.' + ('0' + (date.getMonth() + 1)).slice(-2) + '. (' + ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][date.getDay()] + ')';
    if (dateLabel !== lastDate) { $('date').textContent = dateLabel; lastDate = dateLabel; }
  }
  function dialogKeys(event, code) {
    var active = document.activeElement;
    var direction = 0;
    if (code === 27 || code === 461 || (code === 8 && active.tagName !== 'INPUT')) { event.preventDefault(); Sound.effect('back'); dialogBack(); return; }
    if (code === 9) direction = event.shiftKey ? -1 : 1;
    else if (code === 38) direction = -1;
    else if (code === 40) direction = 1;
    else if (code === 37 || code === 39) {
      if (active.tagName === 'INPUT') return;
      if (active.tagName === 'SELECT') { event.preventDefault(); active.selectedIndex = Math.max(0, Math.min(active.options.length - 1, active.selectedIndex + (code === 37 ? -1 : 1))); return; }
      direction = code === 37 ? -1 : 1;
    } else if (code === 13 && (active.tagName === 'SELECT' || (active.tagName === 'INPUT' && active.type !== 'file'))) direction = 1;
    if (!direction || !dialogControls.length) return;
    var count = dialogControls.length, index = dialogControls.indexOf(active);
    if (index < 0 && direction < 0) index = 0;
    for (var i = 0; i < count; i++) {
      index = (index + direction + count) % count;
      var next = dialogControls[index];
      if (next.disabled || next.hidden || next.type === 'hidden') continue;
      event.preventDefault(); next.focus(); Sound.effect('hover'); return;
    }
  }
  document.addEventListener('keydown', function (event) {
    var code = event.keyCode || event.which; Sound.unlock(); hideTooltip();
    if (mode === 'dialog') {
      if (code === 13 && (suppressOkUntilRelease || okHeld)) { event.preventDefault(); event.stopPropagation(); return; }
      dialogKeys(event, code); return;
    }
    if (mode === 'menu' && code === 9 && document.activeElement.id === 'menu') {
      focusChannel();
      return;
    }
    if (mode === 'menu' && code === 13 && channelHasFocus()) {
      if (!okHeld) { okHeld = true; startHold(selected); }
      event.preventDefault(); return;
    }
    if (mode === 'channel') {
      if (code === 27 || code === 461 || code === 8) { event.preventDefault(); backHome(); }
      else if (code === 37 || code === 39 || code === 9) { event.preventDefault(); (document.activeElement === $('channel-start') ? $('channel-back') : $('channel-start')).focus(); }
      else if (code === 13) { event.preventDefault(); if (!event.repeat) document.activeElement.click(); }
      return;
    }
    var activeId = document.activeElement.id, footerIndex = footerControls.indexOf(activeId);
    if (code >= 37 && code <= 40) {
      event.preventDefault();
      if (footerIndex >= 0) {
        if (code === 38) focusChannel(true);
        else if (code === 37 || code === 39) $(footerControls[Math.max(0, Math.min(2, footerIndex + (code === 37 ? -1 : 1)))]).focus();
      } else if (activeId === 'prev' || activeId === 'next') focusChannel(true);
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
      else if (!window.WiiChooser || !window.WiiChooser.isSelectedHome()) dialog('Exit WiiOS?', 'Return to the TV interface?', '', 'Exit', function () { if (preview) { closeDialog(); toast('Close this browser tab to exit.'); } else { Sound.pause(); window.close(); } });
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
    if (mode === 'menu' && channelHasFocus()) openChannel();
  });
  window.addEventListener('blur', function () { cancelHold(); okHeld = false; suppressOkUntilRelease = false; });

  $('overlay').addEventListener('click', function (event) {
    if (suppressOkUntilRelease || (event.detail > 0 && Date.now() < suppressPointerClickUntil)) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  $('menu').addEventListener('blur', function (event) {
    if (event.target === this) this.removeAttribute('aria-activedescendant');
  });
  $('menu').addEventListener('focus', syncChannelFocus);
  document.addEventListener('mousemove', movePointer);
  document.addEventListener('mousedown', function () { Sound.unlock(); });
  document.addEventListener('error', fallbackImage, true);
  if (thumbnails) document.addEventListener('load', function (event) {
    if (event.target.tagName === 'IMG') thumbnails.loaded(event.target);
  }, true);
  $('prev').onclick = function () { switchPage(page - 1); }; $('next').onclick = function () { switchPage(page + 1); };
  $('settings').onclick = settings; $('apps').onclick = library; $('audio-settings').onclick = audioSettings;
  $('channel-back').onclick = backHome; $('channel-start').onclick = launch;
  $('cancel').onclick = function () { Sound.effect('back'); if (dialogBack) dialogBack(); };
  $('confirm').onclick = function () { if (dialogConfirm) { Sound.effect('select'); dialogConfirm(); } };
  window.addEventListener('resize', resize);
  document.addEventListener('visibilitychange', function () {
    $('stage').classList.toggle('backgrounded', document.hidden); clearInterval(clockTimer);
    if (document.hidden) { cancelHold(); hideTooltip(); clearTimeout(pageTimer); clearTimeout(warmTimer); warmTimer = null; trimPages(); highlight(); }
    if (!document.hidden) { clock(); clockTimer = setInterval(clock, 10000); queueArtwork(false, true); queuePageWarmup(); queueThumbnails(); }
  });
  document.addEventListener('webOSRelaunch', function () { if (mode === 'channel') backHome(); });
  try { reduced = storage.getItem('wiios.motion') === 'reduced'; } catch (ignore) {}
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) reduced = true;
  $('stage').classList.toggle('reduced-motion', reduced);
  $('stage').classList.toggle('strip-renderer', stripRenderer);
  try { statsVisible = storage.getItem('wiios.stats.visible') !== 'off'; } catch (ignore) {}
  updateStats();
  resize(); render(); clock(); clockTimer = setInterval(clock, 10000);
  window.WIIOS_UI_READY = true;
  function refreshLibrary() {
    libraryTimer = null;
    if (document.hidden || scanning || Date.now() - lastRefresh < 10000) return;
    var remaining = 400 - (Date.now() - lastGridInput);
    if (remaining > 0 && window.WiiLibrary.entries().length) {
      libraryTimer = setTimeout(refreshLibrary, remaining);
      return;
    }
    lastRefresh = Date.now();
    var scanRevision = revision;
    scan(function (error) {
      if (!error && initial.fresh && revision === scanRevision) {
        channels = Model.normalize(installed); initial.fresh = false; save(); render();
      }
    });
  }
  function queueLibraryRefresh() {
    if (libraryTimer !== null || document.hidden || scanning || Date.now() - lastRefresh < 10000) return;
    if (window.WiiLibrary.entries().length) libraryTimer = setTimeout(refreshLibrary, 400);
    else refreshLibrary();
  }
  if (!preview) {
    if (window.WiiChooser) {
      window.WiiChooser.probe();
      document.addEventListener('webOSRelaunch', function () { window.WiiChooser.probe(null, true); });
    }
    queueLibraryRefresh();
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { clearTimeout(libraryTimer); libraryTimer = null; }
      else queueLibraryRefresh();
    });
    document.addEventListener('webOSRelaunch', queueLibraryRefresh);
  }
}());

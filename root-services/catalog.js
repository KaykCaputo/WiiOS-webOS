'use strict';
var fs = require('fs'), path = require('path'), crypto = require('crypto'), cp = require('child_process'), http = require('http'), os = require('os'), url = require('url');
var ROOTS = ['/usr/palm/applications', '/media/cryptofs/apps/usr/palm/applications',
  '/media/developer/apps/usr/palm/applications', '/media/developer/apps/usr/palm/application',
  '/media/system/apps/usr/palm/applications', '/mnt/otncabi/usr/palm/applications'];
var TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'};
var zlib = require('zlib');
function pngIconBackground(file) {
  try {
    var png = fs.readFileSync(file);
    if (png.length < 45 || png.length > 2 * 1024 * 1024 || png.slice(0, 8).toString('hex') !== '89504e470d0a1a0a') return '';
    var pos = 8, width = 0, height = 0, depth = 0, mode = -1, interlace = 1, chunks = [], palette = null, transparency = null;
    while (pos + 12 <= png.length) {
      var size = png.readUInt32BE(pos), type = png.toString('ascii', pos + 4, pos + 8);
      if (size > png.length - pos - 12) return '';
      var payload = png.slice(pos + 8, pos + 8 + size);
      if (type === 'IHDR') {
        if (size !== 13) return '';
        width = payload.readUInt32BE(0); height = payload.readUInt32BE(4);
        depth = payload[8]; mode = payload[9]; interlace = payload[12];
      } else if (type === 'PLTE') palette = payload;
      else if (type === 'tRNS') transparency = payload;
      else if (type === 'IDAT') chunks.push(payload);
      else if (type === 'IEND') break;
      pos += size + 12;
    }
    var channels = ({0:1, 2:3, 3:1, 4:2, 6:4})[mode];
    if (!channels || depth !== 8 || interlace !== 0 || width < 1 || height < 1 ||
        width > 768 || height > 768 || !chunks.length) return '';
    var stride = width * channels;
    if ((stride + 1) * height > 5 * 1024 * 1024) return '';
    var raw = zlib.inflateSync(Buffer.concat(chunks));
    if (raw.length !== (stride + 1) * height) return '';
    var prev = new Buffer(stride), row = new Buffer(stride); prev.fill(0);
    var bins = Object.create(null), best = null, transparent = false;
    var rowStep = Math.max(1, Math.floor(height / 48)), colStep = Math.max(1, Math.floor(width / 48));
    var offset = 0, y, x, i;
    for (y = 0; y < height; y++) {
      var filter = raw[offset++]; if (filter > 4) return '';
      for (i = 0; i < stride; i++) {
        var left = i >= channels ? row[i - channels] : 0, up = prev[i], upperLeft = i >= channels ? prev[i - channels] : 0;
        var correction = 0;
        if (filter === 1) correction = left;
        else if (filter === 2) correction = up;
        else if (filter === 3) correction = Math.floor((left + up) / 2);
        else if (filter === 4) {
          var predictor = left + up - upperLeft;
          var da = Math.abs(predictor - left), db = Math.abs(predictor - up), dc = Math.abs(predictor - upperLeft);
          correction = da <= db && da <= dc ? left : db <= dc ? up : upperLeft;
        }
        row[i] = (raw[offset++] + correction) & 255;
      }
      if (y % rowStep === 0) for (x = 0; x < width; x += colStep) {
        var k = x * channels, r, g, b, a = 255;
        if (mode === 6) {r = row[k]; g = row[k + 1]; b = row[k + 2]; a = row[k + 3];}
        else if (mode === 2) {r = row[k]; g = row[k + 1]; b = row[k + 2];}
        else if (mode === 4) {r = g = b = row[k]; a = row[k + 1];}
        else if (mode === 0) {r = g = b = row[k];}
        else {
          var index = row[k];
          if (!palette || index * 3 + 2 >= palette.length) continue;
          r = palette[index * 3]; g = palette[index * 3 + 1]; b = palette[index * 3 + 2];
          if (transparency && index < transparency.length) a = transparency[index];
        }
        if (a < 240) transparent = true;
        if (a < 48) continue;
        var key = (r >> 4) + ':' + (g >> 4) + ':' + (b >> 4);
        var bin = bins[key];
        if (!bin) bin = bins[key] = {count:0, r:0, g:0, b:0};
        bin.count++; bin.r += r; bin.g += g; bin.b += b;
        if (!best || bin.count > best.count) best = bin;
      }
      var swap = prev; prev = row; row = swap;
    }
    if (!best || !best.count) return '';
    var r = Math.round(best.r / best.count), g = Math.round(best.g / best.count), b = Math.round(best.b / best.count);

    if (transparent) {
      var lum = r * .2126 + g * .7152 + b * .0722;
      if (Math.max(r,g,b) - Math.min(r,g,b) < 32) {
        if (lum > 150) {r = g = b = 58;}
        else {r = g = b = 210;}
      } else {
        if (lum < 45) {
          r = Math.min(255, Math.round(r * .6 + 120));
          g = Math.min(255, Math.round(g * .6 + 120));
          b = Math.min(255, Math.round(b * .6 + 120));
        } else {
          r = Math.round(r * .52); g = Math.round(g * .52); b = Math.round(b * .52);
        }
      }
    }
    var hex = function(n) {var s = n.toString(16); return s.length < 2 ? '0' + s : s;};
    return '#' + hex(r) + hex(g) + hex(b);
  } catch (e) {return '';}
}

var HELPER_FINGERPRINT = crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex');
function catalog(options) {
  options = options || {};
  var roots = options.roots || ROOTS, execute = options.execute || cp.execFile;
  var addresses = options.localAddresses || localAddresses();
  var resourcePort = String(options.resourcePort || 3000);
  var cached = null, updated = 0, waiting = null, images = Object.create(null);
  function localAddresses() {
    var result = {'127.0.0.1': true, 'localhost': true};
    try {
      var devices = os.networkInterfaces();
      Object.keys(devices).forEach(function (device) {
        (devices[device] || []).forEach(function (entry) {
          if ((entry.family === 'IPv4' || entry.family === 4) && /^\d{1,3}(?:\.\d{1,3}){3}$/.test(entry.address)) result[entry.address] = true;
        });
      });
    } catch (e) {}
    return result;
  }

  function localResource(value) {
    if (typeof value !== 'string' || value.length > 2048 || !/^http:\/\//i.test(value)) return '';
    var parsed;
    try {parsed = url.parse(value);} catch (e) {return '';}
    if (parsed.protocol !== 'http:' || parsed.auth || parsed.hash || parsed.search ||
        parsed.port !== resourcePort || !addresses[parsed.hostname]) return '';
    var pathname = parsed.pathname || '';
    if (!/^\/resources\/[A-Za-z0-9_%./-]{2,2000}$/.test(pathname)) return '';
    try {
      var decoded = decodeURIComponent(pathname);
      if (decoded.split('/').indexOf('..') !== -1 || decoded.indexOf('\\') !== -1 || /[\x00-\x1f]/.test(decoded)) return '';
    } catch (e) {return '';}
    return value;
  }
  function genericFilename(value) {
    return /(?:^|[\/_.-])(?:default|generic|placeholder|noicon|no-icon|unknown|fallback)(?:[\/_.-]|$)/i.test(value);
  }
  function photographName(value) {
    return /(?:^|[\/_.-])(?:promo|poster|hero|photo|screenshot|screensaver|wallpaper|sofa|couch|livingroom|living-room)(?:[\/_.-]|$)/i.test(value);
  }

  function signature(file, stat) {
    var fd, bytes = new Buffer(Math.min(stat.size, 65536));
    try {
      fd = fs.openSync(file, 'r');
      var count = fs.readSync(fd, bytes, 0, bytes.length, 0);
      return crypto.createHash('sha256').update(String(stat.size) + ':').update(bytes.slice(0, count)).digest('hex');
    } catch (e) {return '';}
    finally {if (fd !== undefined) try {fs.closeSync(fd);} catch (e) {}}
  }
  function score(value, kind, source) {
    if (genericFilename(value)) return -1;

    var isPhoto = photographName(value);
    if (kind === 'banner') {
      if (isPhoto) return 25;

      var jpeg = /\.jpe?g$/i.test(value);
      return (source === 'launch' ? 105 : source === 'metadata' ? 97 : 82) - (jpeg ? 22 : 0);
    }
    var icon = source === 'launch' ? 113 : source === 'metadata' ? 108 : 94;
    if (/(?:^|[\/_.-])(?:logo|largeicon)(?:[\/_.-]|$)/i.test(value)) icon += 9;
    return icon;
  }

  function image(id, value, kind, known) {
    if (typeof value !== 'string' || !value || value.length > 2048) return null;
    if (value.indexOf('file://') === 0) {
      try { value = decodeURIComponent(value.slice(7)); } catch (e) { return null; }
    }
    var resource = localResource(value);
    if (resource) {
      var remoteToken = crypto.createHash('sha256').update('resource:' + resource).digest('hex');
      known[remoteToken] = {remote: resource};
      return {src: 'http://127.0.0.1:19083/v1/images/' + remoteToken, kind: kind};
    }
    if (/^[a-z]+:/i.test(value) || value.split('/').indexOf('..') !== -1 || genericFilename(value)) return null;
    var candidates = value.charAt(0) === '/' ? [value] : roots.map(function (base) {return path.join(base, id, value);});
    for (var i = 0; i < candidates.length; i++) {
      try {
        var target = fs.realpathSync(candidates[i]);
        var allowed = roots.some(function (base) {
          try {return target.indexOf(fs.realpathSync(path.join(base, id)) + '/') === 0;} catch (e) {return false;}
        });
        var type = TYPES[path.extname(target).toLowerCase()];
        if (!allowed || !type) continue;
        var stat = fs.statSync(target);
        if (!stat.isFile() || stat.size < 1 || stat.size > 8 * 1024 * 1024) continue;
        var token = crypto.createHash('sha256').update(target + ':' + stat.size + ':' + stat.mtime.getTime()).digest('hex');
        known[token] = {path: target, type: type, signature: signature(target, stat)};
        return {src: 'http://127.0.0.1:19083/v1/images/' + token, kind: kind};
      } catch (e) {}
    }
    return null;
  }

  function installedArtwork(id, known) {
    var choices = [], info = null, base = null, seen = Object.create(null);
    for (var i = 0; i < roots.length; i++) {
      try {
        var test = path.join(roots[i], id);
        var real = fs.realpathSync(test);
        if (real.indexOf(fs.realpathSync(roots[i]) + '/') !== 0 || !fs.statSync(real).isDirectory()) continue;
        base = real;
        var file = path.join(base, 'appinfo.json');
        try {
          var stat = fs.statSync(file);
          if (stat.isFile() && stat.size > 0 && stat.size < 128 * 1024) info = JSON.parse(fs.readFileSync(file, 'utf8'));
        } catch (ignored) {}
        break;
      } catch (e) {base = null;}
    }
    function append(filename, kind, source) {
      if (typeof filename !== 'string') return;
      var rank = score(filename, kind, source);
      if (rank < 0) return;
      var result = image(id, filename, kind, known);
      if (result && !seen[result.src]) {result._priority = rank; choices.push(result); seen[result.src] = true;}
    }
    if (info && typeof info === 'object') {
      [['bgImage', 'banner'], ['mediumLargeIcon', 'icon'], ['largeIcon', 'icon'],
        ['mediumIcon', 'icon'], ['icon', 'icon'], ['miniicon', 'icon'],
        ['tileIcon', 'icon'], ['favicon', 'icon'], ['splashIcon', 'icon'], ['imageForRecents', 'banner']].forEach(function (field) {
        append(info[field[0]], field[1], 'metadata');
      });
    }
    if (base) {

      ['', 'assets', 'images', 'img', 'res', 'resources'].forEach(function (folder) {
        var directory = path.join(base, folder), names;
        try {names = fs.readdirSync(directory).slice(0, 160);} catch (e) {return;}
        names.sort(function (a, b) {
          function priority(value) {return /banner|bgimage/i.test(value) ? 0 :
            /largeicon|logo|icon|tile/i.test(value) ? 1 : 2;}
          return priority(a) - priority(b) || a.localeCompare(b);
        });
        names.slice(0, 32).forEach(function (filename) {
          if (choices.length >= 8 || !/\.(png|jpe?g|webp)$/i.test(filename) ||
              !/banner|bgimage|largeicon|logo|icon|tile/i.test(filename)) return;
          var relative = folder ? folder + '/' + filename : filename;
          append(relative, /banner|bgimage/i.test(filename) ? 'banner' : 'icon', 'scan');
        });
      });
    }
    return {choices: choices, bgColor: info && typeof info.bgColor === 'string' && /^#[0-9a-f]{6}$/i.test(info.bgColor) ? info.bgColor : ''};
  }
  function list(done) {
    if (cached && Date.now() - updated < 10000) {done(null, cached); return;}
    if (waiting) {waiting.push(done); return;}
    waiting = [done];
    execute('/usr/bin/luna-send', ['-n', '1', '-w', '3000', 'luna://com.webos.applicationManager/listLaunchPoints', '{}'],
      {timeout: 4500, maxBuffer: 2 * 1024 * 1024}, function (error, stdout) {
        var result;
        try {
          if (error) throw error;
          var data = JSON.parse(stdout);
          if (data.returnValue !== true || !Array.isArray(data.launchPoints)) throw new Error('Application list unavailable');
          var known = Object.create(null), seen = Object.create(null);
          var points = data.launchPoints.slice(0, 512).filter(function (point) {
            if (!point || typeof point.id !== 'string' || !/^[A-Za-z0-9_.-]{1,160}$/.test(point.id) || seen[point.id] || point.visible === false) return false;
            if (['com.wiios.launcher', 'com.webos.app.home', 'com.webos.app.fullhome'].indexOf(point.id) !== -1) return false;
            seen[point.id] = true; return true;
          }).map(function (point) {
            var choices = [], used = Object.create(null);
            [['mediumLargeIcon', 'icon'], ['largeIcon', 'icon'], ['icon', 'icon'],
              ['bgImage', 'banner'], ['mediumIcon', 'icon'], ['favicon', 'icon'], ['imageForRecents', 'banner']].forEach(function (field) {
              var value = point[field[0]], rank = typeof value === 'string' ? score(value, field[1], 'launch') : -1;
              if (rank < 0) return;
              var candidate = image(point.id, value, field[1], known);
              if (candidate && !used[candidate.src]) {candidate._priority = rank; choices.push(candidate); used[candidate.src] = true;}
            });

            if (Array.isArray(point.bgImages)) point.bgImages.slice(0, 3).forEach(function (value) {
              var rank = score(value, 'banner', 'launch');
              if (rank < 0) return;
              var candidate = image(point.id, value, 'banner', known);
              if (candidate && !used[candidate.src]) {candidate._priority = rank; choices.push(candidate); used[candidate.src] = true;}
            });
            var extra = installedArtwork(point.id, known);
            extra.choices.forEach(function (candidate) {
              if (!used[candidate.src]) {choices.push(candidate); used[candidate.src] = true;}
            });
            choices.sort(function (a, b) {return b._priority - a._priority;});
            return {id: point.id, title: String(point.title || point.id).slice(0, 80),
              bgColor: /^#[0-9a-f]{6}$/i.test(point.bgColor) ? point.bgColor : extra.bgColor || '#eef0f2',
              _candidates: choices};
          });

          var repeats = Object.create(null), users = Object.create(null);
          points.forEach(function (point) {
            point._candidates.forEach(function (candidate) {
              var token = candidate.src.split('/').pop(), sig = known[token] && known[token].signature;
              if (!sig) return;
              if (!users[sig]) users[sig] = Object.create(null);
              users[sig][point.id] = true;
            });
          });
          Object.keys(users).forEach(function (sig) {repeats[sig] = Object.keys(users[sig]).length;});
          points.forEach(function (point) {
            point.images = point._candidates.filter(function (candidate) {
              var token = candidate.src.split('/').pop(), item = known[token];
              if (item && item.signature && repeats[item.signature] >= 3) return false;

              if (candidate.kind === 'banner' && candidate._priority <= 25 &&
                  point._candidates.some(function (other) {return other.kind === 'icon';})) return false;
              return true;
            }).slice(0, 8).map(function (candidate) {var token = candidate.src.split('/').pop(), item = known[token];
                var icon = candidate.kind === 'icon' && item && item.path && item.type === 'image/png' ? pngIconBackground(item.path) : '';
                return {src: candidate.src, kind: candidate.kind, recommended: candidate._priority > 25, background: icon};});
            delete point._candidates;
          });
          result = {returnValue: true, launchPoints: points, source: 'local', helperFingerprint: HELPER_FINGERPRINT};
          images = known; cached = result; updated = Date.now();
        } catch (e) {error = e;}
        var callbacks = waiting; waiting = null;
        callbacks.forEach(function (callback) {callback(error, result);});
      });
  }
  function imageType(data) {
    return data.slice(0, 8).toString('hex') === '89504e470d0a1a0a' ? 'image/png' :
      data.slice(0, 3).toString('hex') === 'ffd8ff' ? 'image/jpeg' :
      data.slice(0, 4).toString() === 'RIFF' && data.slice(8, 12).toString() === 'WEBP' ? 'image/webp' : '';
  }
  function serveResource(remote, res) {

    var complete = false, req;
    function fail() {
      if (complete) return;
      complete = true;
      res.writeHead(404); res.end();
    }
    try {
      var target = url.parse(remote);
      req = http.get({hostname: target.hostname, port: target.port, path: target.path,
        agent: false, timeout: 3500}, function (upstream) {
        if (upstream.statusCode !== 200) {upstream.resume(); fail(); return;}
        var length = 0, chunks = [];
        upstream.on('data', function (chunk) {
          length += chunk.length;
          if (length > 8 * 1024 * 1024) {upstream.destroy(); fail(); return;}
          chunks.push(chunk);
        });
        upstream.on('error', fail);
        upstream.on('end', function () {
          if (complete) return;
          var data = Buffer.concat(chunks), type = imageType(data);
          if (!type) {fail(); return;}
          complete = true;
          res.setHeader('Content-Type', type);
          res.setHeader('Cache-Control', 'private, max-age=300');
          res.end(data);
        });
      });
      req.setTimeout(3500, function () {req.destroy();});
      req.on('error', fail);
    } catch (e) {fail();}
  }
  function serve(url, res) {
    var match = /^\/v1\/images\/([a-f0-9]{64})$/.exec(url), entry = match && images[match[1]];
    if (!entry) {res.writeHead(404); res.end(); return;}
    if (entry.remote) {serveResource(entry.remote, res); return;}
    try {
      if (fs.realpathSync(entry.path) !== entry.path) throw new Error('Changed path');
      var stat = fs.statSync(entry.path);
      if (!stat.isFile() || stat.size < 1 || stat.size > 8 * 1024 * 1024) throw new Error('Invalid image');
      var data = fs.readFileSync(entry.path);
      var type = data.slice(0, 8).toString('hex') === '89504e470d0a1a0a' ? 'image/png' :
        data.slice(0, 3).toString('hex') === 'ffd8ff' ? 'image/jpeg' :
        data.slice(0, 4).toString() === 'RIFF' && data.slice(8, 12).toString() === 'WEBP' ? 'image/webp' : '';
      if (type !== entry.type) throw new Error('Invalid image data');
      res.setHeader('Content-Type', type);
      res.setHeader('Cache-Control', 'private, max-age=60');
      res.end(data);
    } catch (e) {res.writeHead(404); res.end();}
  }
  return {list: list, serve: serve, fingerprint: HELPER_FINGERPRINT};
}
module.exports = catalog;

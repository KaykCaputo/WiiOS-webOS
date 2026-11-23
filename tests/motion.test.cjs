'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
function app(options = {}) {
  const dom = new JSDOM(read('index.html'), {url:'http://wiios.test',runScripts:'outside-only',pretendToBeVisual:true});
  const w = dom.window, intervals = [], timeouts = [];
  const frames = new Map();
  let frameId = 0;
  if (options.manualFrames) {
    w.requestAnimationFrame = fn => {frames.set(++frameId, fn);return frameId;};
    w.cancelAnimationFrame = id => frames.delete(id);
  }
  const originalInterval = w.setInterval;
  w.setInterval = (fn, ms) => {intervals.push({fn,ms});return originalInterval(fn,ms);};
  const originalTimeout = w.setTimeout;
  w.setTimeout = (fn,ms) => {timeouts.push({fn,ms});return originalTimeout(fn,ms);};
  w.localStorage.setItem('wiios.stats.visible','off');
  if (options.stripRenderer) w.localStorage.setItem('wiios.renderer','strip');
  const channels = Array.from({length:48},(_,i)=>({id:'app.'+i,name:'App '+i,theme:'internet'}));
  w.localStorage.setItem(options.tv ? 'wiios.channels.v2' : 'wiios.preview.v2',JSON.stringify(channels));
  w.WiiTV = {isTV:!!options.tv,canUninstall:()=>false,request:options.request};
  w.WIIOS_HOME_CHOOSER = !!options.homeChooser;
  w.WiiAudio = {effect:options.effect || (()=>{}),unlock(){},resume(){},pause(){}};
  const points = channels.map((c,i)=>({id:c.id,title:c.name,images:[{src:'http://127.0.0.1:19083/v1/images/'+i.toString(16).padStart(64,'0'),kind:'icon'}]}));
  w.XMLHttpRequest = function(){this.open=()=>{};this.send=()=>{
    if (options.onCatalogScan) options.onCatalogScan();
    this.status=200;this.responseText=JSON.stringify({returnValue:true,source:'local',launchPoints:points});this.onload();
  };};
  for (const file of ['channels.js','library.js','artwork.js','stats.js']) w.eval(read(file));
  if(options.images) w.WiiLibrary.accept({source:'local',launchPoints:points});
  let generated=0;
  const originalSource=w.WiiArt.source;
  w.WiiArt.source=channel=>{generated++;return originalSource(channel);};
  w.eval(read('app.js'));
  function key(code){w.document.dispatchEvent(new w.KeyboardEvent('keydown',{keyCode:code,bubbles:true,cancelable:true}));w.document.dispatchEvent(new w.KeyboardEvent('keyup',{keyCode:code,bubbles:true,cancelable:true}));}
  return {w,d:w.document,key,intervals,timeouts,frames,
    paint(){const pending=Array.from(frames.values());frames.clear();pending.forEach(fn=>fn(0));},
    generated:()=>generated,close:()=>w.close(),wait:ms=>new Promise(resolve=>setTimeout(resolve,ms))};
}
test('Home Chooser setup is opt-in and opens the owner confirmation',()=>{
  const calls=[];
  const standard=app({tv:true});
  const chooser=app({tv:true,homeChooser:true,request:(method,params,done)=>{
    calls.push([method,JSON.stringify(params)]);
    done({errorCode:'NOT_FOUND'});
  }});
  try {
    standard.d.getElementById('settings').click();
    assert.equal(standard.d.getElementById('home-chooser-choice'),null);
    chooser.d.getElementById('settings').click();
    assert.equal(calls.length,0);
    chooser.d.getElementById('home-chooser-choice').click();
    assert.deepEqual(calls,[['launch','{"id":"org.webosbrew.homechooser","params":{"request":"com.wiios.launcher"}}']]);
    assert.match(chooser.d.getElementById('toast').textContent,/Homebrew Channel/);
    assert.equal(chooser.d.getElementById('home-chooser-choice').disabled,false);
  } finally {standard.close();chooser.close();}
});
test('loads artwork near the current page and releases distant pages after rapid navigation',async()=>{
  const a=app();
  try {
    assert.equal(a.d.querySelectorAll('.channel').length,48);
    assert.equal(a.d.querySelectorAll('#menu .art').length,15);
    a.key(34);a.key(34);a.key(34);
    await a.wait(430);
    assert.ok(a.d.querySelectorAll('#menu .art').length <= 27);
    assert.equal(a.d.querySelector('#slot-0 .art'),null);
    assert.equal(a.d.querySelector('#slot-12 .art'),null);
    assert.ok(a.d.querySelector('#slot-34 .art'));
    assert.ok(a.d.querySelector('#slot-35 .art'));
    assert.ok(a.d.querySelector('#slot-36 .art'));
    assert.equal(a.d.activeElement.id,'slot-36');
    a.key(461);
    assert.ok(a.d.querySelector('#slot-0 .art'));
    assert.ok(a.d.querySelector('#slot-13 .art'));
    assert.equal(a.d.activeElement.id,'slot-0');
    a.key(34);a.key(33);
    const track=a.d.getElementById('channel-track');
    assert.equal(track.children[0].style.transform,'translateX(0px)');
    assert.ok(Array.from(track.children).every(page=>page.style.visibility===''));
    await a.wait(430);
    assert.equal(track.children[3].style.visibility,'hidden');
    assert.ok(track.children[3].classList.contains('parked'));
  } finally {a.close();}
});
test('identical catalog refresh keeps decoded images and never generates unused fallback art',()=>{
  const a=app({images:true,tv:true});
  try {
    const image=a.d.querySelector('#slot-0 .app-image');
    assert.ok(image);assert.equal(a.generated(),0);
    a.d.getElementById('apps').click();a.d.getElementById('scan-choice').click();
    assert.equal(a.d.querySelector('#slot-0 .app-image'),image);
    a.d.getElementById('cancel').click();
    a.key(39);a.key(37);
    assert.equal(a.d.querySelector('#slot-0 .app-image'),image);
  } finally {a.close();}
});
test('page changes prepare only new artwork and keep page and hover sounds',()=>{
  const effects=[];
  const a=app({effect:key=>effects.push(key)});
  try {
    const before=a.generated();
    const nearby=a.d.querySelector('#slot-12 .art');
    const html=Object.getOwnPropertyDescriptor(a.w.Element.prototype,'innerHTML');
    let parses=0;
    Object.defineProperty(a.w.Element.prototype,'innerHTML',{
      get:html.get,
      set(markup){if(markup.includes('class="art ')) parses++;html.set.call(this,markup);}
    });
    a.key(34);
    assert.equal(a.generated()-before,12);
    assert.equal(parses,1);
    assert.ok(a.d.querySelector('#slot-0 .art'));
    assert.equal(a.d.querySelector('#slot-12 .art'),nearby);
    a.key(33);
    a.key(39);
    assert.equal(a.generated()-before,12);
    assert.deepEqual(effects,['page','page','hover']);
    assert.equal(a.d.getElementById('slot-1').tabIndex,0);
    assert.equal(a.d.getElementById('slot-12').tabIndex,-1);
    assert.equal(a.d.activeElement.id,'slot-1');
  } finally {a.close();}
});
test('generated banners are read from storage on the next launch', async()=>{
  const a=app();
  try {
    const channel={id:'app.0',name:'App 0'};
    const before=a.w.WiiArt.source(channel);
    await a.wait(20);
    assert.ok(a.w.localStorage.getItem('wiios.generated.artwork.v1'));
    a.w.encodeURIComponent=()=>{throw Error('Artwork was generated again');};
    a.w.eval(read('artwork.js'));
    assert.equal(a.w.WiiArt.source(channel),before);
  } finally {a.close();}
});
test('turning to a warmed page reuses the prepared artwork and peeking column',()=>{
  const a=app({images:true});
  try {
    const nativeNow=a.w.Date.now;
    const time=nativeNow()+1000;
    a.w.Date.now=()=>time;
    for(let i=0;i<6;i++) a.timeouts.filter(timer=>timer.fn.name==='warmNeighbor').at(-1).fn();
    const tile=a.d.querySelector('#slot-23 .app-image');
    const peek=a.d.querySelector('#slot-24 .app-image');
    assert.ok(tile);
    assert.ok(peek);
    const mutations=new a.w.MutationObserver(()=>{});
    const menu=a.d.getElementById('menu');
    mutations.observe(menu,{subtree:true,childList:true});
    a.key(34);
    assert.equal(mutations.takeRecords().length,0);
    mutations.disconnect();
    assert.equal(a.d.querySelector('#slot-23 .app-image'),tile);
    assert.equal(a.d.querySelector('#slot-24 .app-image'),peek);
  } finally {a.close();}
});
test('navigation mutates only the old and new focus classes',()=>{
  const a=app();
  try {
    a.key(39);
    const mutations=new a.w.MutationObserver(()=>{});
    mutations.observe(a.d.getElementById('menu'),{subtree:true,attributes:true,attributeFilter:['class']});
    a.key(39);
    const records=mutations.takeRecords();mutations.disconnect();
    assert.ok(records.length<=2);
    assert.equal(a.d.querySelectorAll('.channel.selected').length,1);
    assert.equal(a.d.activeElement.id,'slot-2');
  } finally {a.close();}
});
test('TV navigation keeps one DOM focus while the selected channel moves',()=>{
  const effects=[];
  const a=app({tv:true,images:true,manualFrames:true,effect:key=>effects.push(key)});
  try {
    const nativeFocus=a.w.HTMLElement.prototype.focus;
    const focusCalls=[];
    a.w.HTMLElement.prototype.focus=function(...args){focusCalls.push(this.id);return nativeFocus.apply(this,args);};
    a.key(39);a.key(39);a.key(40);a.key(34);
    const menu=a.d.getElementById('menu');
    assert.deepEqual(focusCalls,['menu']);
    assert.equal(a.d.activeElement,menu);
    assert.equal(a.frames.size,1);
    a.paint();
    assert.equal(menu.getAttribute('aria-activedescendant'),'slot-18');
    assert.equal(a.d.querySelector('.channel.selected').id,'slot-18');
    const track=a.d.getElementById('channel-track');
    assert.equal(menu.style.transform,'');
    assert.equal(track.style.transform,'');
    for(const page of Array.from(track.children).slice(0,3)) assert.equal(page.style.transform,'translateX(-1096px)');
    assert.equal(track.children[3].style.transform,'translateX(0px)');
    assert.ok(track.children[3].classList.contains('parked'));
    assert.deepEqual(effects,['hover','hover','hover','page']);
    a.key(39);
    a.key(13);
    assert.equal(a.d.getElementById('channel-screen').hidden,false);
    assert.equal(a.d.querySelector('#channel-banner .art-title').textContent,'App 19');
    a.key(461);
    assert.equal(a.d.activeElement.id,'slot-19');
    assert.equal(menu.hasAttribute('aria-activedescendant'),false);
  } finally {a.close();}
});
test('rapid page reversals share a visual update and play each page sound',()=>{
  const effects=[];
  const a=app({tv:true,images:true,manualFrames:true,effect:key=>effects.push(key)});
  try {
    const track=a.d.getElementById('channel-track');
    a.key(34);a.key(34);a.key(33);
    assert.equal(track.children[0].style.transform,'translateX(0px)');
    assert.equal(a.frames.size,1);
    assert.deepEqual(effects,['page','page','page']);
    a.paint();
    assert.equal(track.children[0].style.transform,'translateX(-1096px)');
    assert.equal(a.d.querySelector('.channel.selected').id,'slot-12');
  } finally {a.close();}
});
test('the strip renderer remains available for frame pacing comparisons',()=>{
  const a=app({stripRenderer:true});
  try {
    const track=a.d.getElementById('channel-track');
    a.key(34);
    assert.ok(a.d.getElementById('stage').classList.contains('strip-renderer'));
    assert.equal(track.style.transform,'translateX(-1096px)');
    assert.ok(Array.from(track.children).every(page=>page.style.transform===''));
  } finally {a.close();}
});
test('frame pacing diagnostics run only during an explicit sample',()=>{
  const a=app({manualFrames:true});
  try {
    a.w.eval(read('performance.js'));
    const measure=a.w.WiiPerformance;
    assert.equal(a.frames.size,0);
    assert.equal(measure.start(),true);
    assert.equal(measure.start(),false);
    for(const time of [0,16,32,84]) {
      const callback=a.frames.values().next().value;
      a.frames.clear();
      callback(time);
    }
    measure.mark('directionInput');
    const report=measure.stop();
    assert.equal(report.intervals,3);
    assert.equal(report.p50Ms,16);
    assert.equal(report.p95Ms,52);
    assert.equal(report.over33Ms,1);
    assert.equal(report.events.directionInput,1);
    assert.equal(a.frames.size,0);
    assert.equal(measure.stop(),null);
  } finally {a.close();}
});
test('a stationary pointer does not override directional selection during a page slide',()=>{
  const effects=[];
  const a=app({tv:true,images:true,manualFrames:true,effect:key=>effects.push(key)});
  function move(slot, x) {
    a.d.getElementById('slot-'+slot).dispatchEvent(new a.w.MouseEvent('mousemove',{bubbles:true,screenX:x,screenY:120}));
  }
  try {
    move(1,400);
    a.paint();
    a.key(34);
    a.paint();
    move(12,400);
    a.paint();
    assert.equal(a.d.querySelector('.channel.selected').id,'slot-13');
    assert.deepEqual(effects,['hover','page']);
    move(12,401);
    a.paint();
    assert.equal(a.d.querySelector('.channel.selected').id,'slot-12');
    assert.deepEqual(effects,['hover','page','hover']);
    a.d.getElementById('slot-12').click();
    assert.equal(a.d.querySelector('#channel-banner .art-title').textContent,'App 12');
  } finally {a.close();}
});
test('automatic catalog refresh waits for navigation to go quiet when artwork is cached',()=>{
  let scans=0;
  const a=app({tv:true,images:true,onCatalogScan:()=>scans++});
  try {
    let now=a.w.Date.now();
    a.w.Date.now=()=>now;
    const scheduled=a.timeouts.at(-1);
    assert.equal(scheduled.ms,400);
    a.key(39);
    scheduled.fn();
    assert.equal(scans,0);
    now+=401;
    a.timeouts.at(-1).fn();
    assert.equal(scans,1);
  } finally {a.close();}
});
test('dialog navigation skips disabled controls without reading layout',()=>{
  const a=app();
  try {
    a.d.getElementById('settings').click();
    const edit=a.d.getElementById('edit-choice');
    const move=a.d.getElementById('move-choice');
    const image=a.d.getElementById('image-choice');
    move.disabled=true;
    Object.defineProperty(a.w.HTMLElement.prototype,'offsetHeight',{get(){throw Error('Unexpected layout read');}});
    edit.focus();
    a.key(40);
    assert.equal(a.d.activeElement.id,'library-choice');
    move.disabled=false;
    a.key(38);
    assert.equal(a.d.activeElement,move);
    assert.equal(image.disabled,true);
  } finally {a.close();}
});
test('editing a channel preserves the grid and other decoded artwork',()=>{
  const a=app({images:true,tv:true});
  try {
    const slots=Array.from(a.d.querySelectorAll('.channel'));
    const neighbor=a.d.querySelector('#slot-1 .app-image');
    a.d.getElementById('settings').click();
    a.d.getElementById('remove-choice').click();
    a.d.getElementById('confirm').click();
    assert.deepEqual(Array.from(a.d.querySelectorAll('.channel')),slots);
    assert.equal(a.d.querySelector('#slot-1 .app-image'),neighbor);
    assert.ok(slots[0].classList.contains('empty'));
  } finally {a.close();}
});
test('a broken app image still falls back with a single delegated listener',()=>{
  const a=app({images:true,tv:true});
  try {
    a.d.querySelector('#slot-0 .app-image').dispatchEvent(new a.w.Event('error'));
    assert.ok(a.d.querySelector('#slot-0 .art-generated'));
  } finally {a.close();}
});
test('clock retains its SVG within the same minute',()=>{
  const a=app();
  try {
    const svg=a.d.querySelector('#clock svg');
    a.intervals.find(i=>i.ms===10000).fn();
    assert.equal(a.d.querySelector('#clock svg'),svg);
  } finally {a.close();}
});
test('open/back remains responsive and reduced motion persists',()=>{
  const a=app();
  try {
    for(let i=0;i<3;i++) {
      a.d.getElementById('slot-0').click();
      assert.equal(a.d.getElementById('channel-screen').hidden,false);
      assert.ok(a.d.getElementById('stage').classList.contains('menu-covered'));
      a.key(461);
      assert.equal(a.d.getElementById('channel-screen').hidden,true);
      assert.equal(a.d.getElementById('channel-banner').childElementCount,0);
      assert.equal(a.d.activeElement.id,'slot-0');
    }
    a.d.getElementById('settings').click();a.d.getElementById('motion-choice').click();
    assert.equal(a.w.localStorage.getItem('wiios.motion'),'reduced');
    a.d.getElementById('cancel').click();a.d.getElementById('slot-0').click();a.key(461);
    assert.equal(a.d.getElementById('home').classList.contains('returning'),false);
    assert.ok(a.d.getElementById('stage').classList.contains('reduced-motion'));
  } finally {a.close();}
});
test('stats cancel polling and animation callbacks while hidden or covered, then resume once',()=>{
  const dom=new JSDOM('<div id="stats"></div>',{runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window, timers=new Set(), frames=new Set();let seq=0, hidden=false;
  Object.defineProperty(w.document,'hidden',{get:()=>hidden});
  w.setInterval=()=>{timers.add(++seq);return seq;};w.clearInterval=id=>timers.delete(id);
  w.requestAnimationFrame=()=>{frames.add(++seq);return seq;};w.cancelAnimationFrame=id=>frames.delete(id);
  w.XMLHttpRequest=function(){this.open=()=>{};this.send=()=>{};this.abort=()=>this.onabort();};
  w.eval(read('stats.js'));
  const stop=w.WiiStats.mount(w.document.getElementById('stats'),{isTV:true});
  try {
    assert.equal(timers.size,1);assert.equal(frames.size,1);
    hidden=true;w.document.dispatchEvent(new w.Event('visibilitychange'));
    assert.equal(timers.size,0);assert.equal(frames.size,0);
    hidden=false;w.document.dispatchEvent(new w.Event('visibilitychange'));
    assert.equal(timers.size,1);assert.equal(frames.size,1);
    stop.setCovered(true);
    assert.equal(timers.size,0);assert.equal(frames.size,0);
    stop.setCovered(false);stop.setCovered(false);
    assert.equal(timers.size,1);assert.equal(frames.size,1);
    stop();assert.equal(timers.size,0);assert.equal(frames.size,0);
  } finally {w.close();}
});
test('stats show the missing helper and back off while local FPS keeps running',()=>{
  const dom=new JSDOM('<div id="stats"></div>',{runScripts:'outside-only',pretendToBeVisual:true});
  try {
    const w=dom.window, container=w.document.getElementById('stats');
    let now=10000, polls=0, tick, poll;
    w.Date.now=()=>now;
    w.requestAnimationFrame=fn=>{tick=fn;return 1;};
    w.setInterval=fn=>{poll=fn;return 1;};
    w.XMLHttpRequest=function(){this.open=()=>{};this.send=()=>{polls++;this.onerror();};};
    w.eval(read('stats.js'));
    const stop=w.WiiStats.mount(container,{isTV:true});
    assert.equal(container.querySelector('.stats-status').textContent,'Metrics helper unavailable');
    assert.equal(container.querySelector('.stats-status').hidden,false);
    now+=1000;poll();
    assert.equal(polls,1);
    now+=1000;poll();
    assert.equal(polls,2);
    tick(0);tick(2000);
    assert.equal(container.querySelector('.stat-fps dd').textContent,'0.5');
    stop();
  } finally {dom.window.close();}
});

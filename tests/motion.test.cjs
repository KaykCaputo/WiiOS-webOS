'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
function app(options = {}) {
  const dom = new JSDOM(read('index.html'), {url:'http://wiios.test',runScripts:'outside-only',pretendToBeVisual:true});
  const w = dom.window, intervals = [], timeouts = [];
  const originalInterval = w.setInterval;
  w.setInterval = (fn, ms) => {intervals.push({fn,ms});return originalInterval(fn,ms);};
  const originalTimeout = w.setTimeout;
  w.setTimeout = (fn,ms) => {timeouts.push({fn,ms});return originalTimeout(fn,ms);};
  w.localStorage.setItem('wiios.stats.visible','off');
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
  return {w,d:w.document,key,intervals,timeouts,generated:()=>generated,close:()=>w.close(),wait:ms=>new Promise(resolve=>setTimeout(resolve,ms))};
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
    assert.equal(a.d.querySelectorAll('#menu .art').length,15);
    assert.equal(a.d.getElementById('slot-0').childElementCount,0);
    assert.equal(a.d.getElementById('slot-34').childElementCount,0);
    assert.ok(a.d.getElementById('slot-35').firstChild);
    assert.ok(a.d.getElementById('slot-36').firstChild);
    assert.equal(a.d.activeElement.id,'slot-36');
    a.key(33);a.key(33);a.key(33);
    assert.ok(a.d.getElementById('slot-0').firstChild);
    assert.equal(a.d.activeElement.id,'slot-0');
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
  const a=app({tv:true,images:true,effect:key=>effects.push(key)});
  try {
    const nativeFocus=a.w.HTMLElement.prototype.focus;
    const focusCalls=[];
    a.w.HTMLElement.prototype.focus=function(...args){focusCalls.push(this.id);return nativeFocus.apply(this,args);};
    a.key(39);a.key(39);a.key(40);a.key(34);
    const menu=a.d.getElementById('menu');
    assert.deepEqual(focusCalls,['menu']);
    assert.equal(a.d.activeElement,menu);
    assert.equal(menu.getAttribute('aria-activedescendant'),'slot-18');
    assert.equal(a.d.querySelector('.channel.selected').id,'slot-18');
    assert.equal(menu.style.transform,'');
    for(const page of menu.children) assert.equal(page.style.transform,'translateX(-1096px)');
    assert.deepEqual(effects,['hover','hover','hover','page']);
    a.key(13);
    assert.equal(a.d.getElementById('channel-screen').hidden,false);
    a.key(461);
    assert.equal(a.d.activeElement.id,'slot-18');
    assert.equal(menu.hasAttribute('aria-activedescendant'),false);
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

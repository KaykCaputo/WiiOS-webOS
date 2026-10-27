'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
function app(options = {}) {
  const dom = new JSDOM(read('index.html'), {url:'http://wiios.test',runScripts:'outside-only',pretendToBeVisual:true});
  const w = dom.window, intervals = [];
  const originalInterval = w.setInterval;
  w.setInterval = (fn, ms) => {intervals.push({fn,ms});return originalInterval(fn,ms);};
  w.localStorage.setItem('wiios.stats.visible','off');
  const channels = Array.from({length:48},(_,i)=>({id:'app.'+i,name:'App '+i,theme:'internet'}));
  w.localStorage.setItem(options.tv ? 'wiios.channels.v2' : 'wiios.preview.v2',JSON.stringify(channels));
  w.WiiTV = {isTV:!!options.tv,canUninstall:()=>false};
  w.WiiAudio = {effect(){},unlock(){},resume(){},pause(){}};
  const points = channels.map((c,i)=>({id:c.id,title:c.name,images:[{src:'http://127.0.0.1:19083/v1/images/'+i.toString(16).padStart(64,'0'),kind:'icon'}]}));
  w.XMLHttpRequest = function(){this.open=()=>{};this.send=()=>{this.status=200;this.responseText=JSON.stringify({returnValue:true,source:'local',launchPoints:points});this.onload();};};
  for (const file of ['channels.js','library.js','artwork.js','stats.js']) w.eval(read(file));
  if(options.images) w.WiiLibrary.accept({source:'local',launchPoints:points});
  let generated=0;
  const originalSource=w.WiiArt.source;
  w.WiiArt.source=channel=>{generated++;return originalSource(channel);};
  w.eval(read('app.js'));
  function key(code){w.document.dispatchEvent(new w.KeyboardEvent('keydown',{keyCode:code,bubbles:true,cancelable:true}));w.document.dispatchEvent(new w.KeyboardEvent('keyup',{keyCode:code,bubbles:true,cancelable:true}));}
  return {w,d:w.document,key,intervals,generated:()=>generated,close:()=>w.close(),wait:ms=>new Promise(resolve=>setTimeout(resolve,ms))};
}
test('loads artwork near the current page and releases distant pages after rapid navigation',async()=>{
  const a=app();
  try {
    assert.equal(a.d.querySelectorAll('.channel').length,48);
    assert.equal(a.d.querySelectorAll('#menu .art').length,24);
    a.key(34);a.key(34);a.key(34);
    await a.wait(430);
    assert.equal(a.d.querySelectorAll('#menu .art').length,24);
    assert.equal(a.d.getElementById('slot-0').childElementCount,0);
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
      assert.equal(a.d.activeElement.id,'slot-0');
    }
    a.d.getElementById('settings').click();a.d.getElementById('motion-choice').click();
    assert.equal(a.w.localStorage.getItem('wiios.motion'),'reduced');
    a.d.getElementById('cancel').click();a.d.getElementById('slot-0').click();a.key(461);
    assert.equal(a.d.getElementById('home').classList.contains('returning'),false);
    assert.ok(a.d.getElementById('stage').classList.contains('reduced-motion'));
  } finally {a.close();}
});
test('stats cancel polling and animation callbacks while hidden, then resume once',()=>{
  const dom=new JSDOM('<div id="stats"></div>',{runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window, timers=new Set(), frames=new Set();let seq=0, hidden=false;
  Object.defineProperty(w.document,'hidden',{get:()=>hidden});
  w.setInterval=()=>{timers.add(++seq);return seq;};w.clearInterval=id=>timers.delete(id);
  w.requestAnimationFrame=()=>{frames.add(++seq);return seq;};w.cancelAnimationFrame=id=>frames.delete(id);
  w.eval(read('stats.js'));
  const stop=w.WiiStats.mount(w.document.getElementById('stats'),{isTV:false});
  try {
    assert.equal(timers.size,1);assert.equal(frames.size,1);
    hidden=true;w.document.dispatchEvent(new w.Event('visibilitychange'));
    assert.equal(timers.size,0);assert.equal(frames.size,0);
    hidden=false;w.document.dispatchEvent(new w.Event('visibilitychange'));
    assert.equal(timers.size,1);assert.equal(frames.size,1);
    stop();assert.equal(timers.size,0);assert.equal(frames.size,0);
  } finally {w.close();}
});

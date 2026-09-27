const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/player.js'), 'utf8');

async function player({playError, fetchError} = {}) {
  const elements = new Map();
  const timers = new Map();
  const classes = new Set();
  let id = 0;
  let timestamp = 0;
  const requests = [];
  const state = {station_id:'one',status:'live',demo:true,now:{title:'Signal 1',artist:'Synthetic demo',media_type:'Song'}};
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      value: selector === '#volume' ? '70' : '', events:{}, src:'', loads:0, plays:0, pauses:0,
      addEventListener(name, callback) { this.events[name] = callback; },
      removeAttribute(name) { delete this[name]; },
      hasAttribute(name) { return Boolean(this[name]); },
      load() { this.loads++; }, pause() { this.pauses++; },
      async play() { this.plays++; if (playError) throw playError; },
    });
    return elements.get(selector);
  }
  const document = {querySelector:element,body:{classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)}},hidden:false,
    events:{},addEventListener(name,callback){this.events[name]=callback;}};
  const window = {events:{},addEventListener(name,callback){this.events[name]=callback;}};
  const context = vm.createContext({document,window,localStorage:{getItem:()=>null,setItem:()=>{}},
    Date:{now:()=>++timestamp},AbortSignal:{timeout:()=>({})},
    setTimeout:(callback)=>{timers.set(++id,callback);return id;},clearTimeout:key=>timers.delete(key),
    fetch:async(url)=>{requests.push(url);if(fetchError)throw Error('offline');return {ok:true,json:async()=>state};},
  });
  vm.runInContext(source, context);
  const flush = () => new Promise(resolve=>setImmediate(resolve));
  await flush();
  return {element,document,window,requests,timers,classes,state,flush,
    async click(){element('#tune').events.click();await flush();},
    async poll(){await vm.runInContext('update()',context);await flush();}};
}

test('Tune In joins the shared stream; pause releases buffer; next play opens a fresh connection', async()=>{
  const p=await player();
  assert.equal(p.element('#tune').disabled,false);
  await p.click();
  const original=p.element('#audio').src;
  assert.match(original,/^\/stream\?connection=/);
  assert.equal(p.element('#tune').textContent,'Pause');
  await p.click();
  assert.equal(p.element('#audio').src,undefined);
  assert.equal(p.element('#tune').textContent,'Tune In');
  await p.click();
  assert.notEqual(p.element('#audio').src,original);
  assert.deepEqual(p.requests,['/api/now']);
});
test('Volume only changes this listener and never requests station mutations',async()=>{
  const p=await player();await p.click();
  const original=p.element('#audio').src;
  p.element('#volume').value='25';p.element('#volume').events.input();
  assert.equal(p.element('#audio').volume,.25);
  assert.equal(p.element('#audio').src,original);
  assert.deepEqual(p.requests,['/api/now']);
});
test('Metadata refreshes while paused without starting audio',async()=>{
  const p=await player();p.state.now.title='Advertisement';await p.poll();
  assert.equal(p.element('#title').textContent,'Advertisement');
  assert.equal(p.element('#audio').plays,0);
  assert.equal(p.element('#demo').hidden,false);
});
test('Offline startup is explicit and does not offer a dead play control',async()=>{
  const p=await player({fetchError:true});
  assert.equal(p.element('#on-air').textContent,'OFFLINE');
  assert.equal(p.element('#tune').disabled,true);
  assert.equal(p.element('#title').textContent,'Signal unavailable');
});
test('Autoplay denial asks for another click without a retry loop',async()=>{
  const error=new Error('gesture needed');error.name='NotAllowedError';
  const p=await player({playError:error});await p.click();
  assert.equal(p.element('#tune').textContent,'Tune In');
  assert.match(p.element('#play-status').textContent,/needs a click/);
  assert.equal(p.element('#audio').src,undefined);
  assert.equal(p.timers.size,1); // Only metadata polling remains.
});
test('Source failure clears playback and recovery rejoins live',async()=>{
  const p=await player();await p.click();
  const original=p.element('#audio').src;
  p.state.status='offline';await p.poll();
  assert.equal(p.element('#audio').src,undefined);
  assert.equal(p.classes.has('listening'),false);
  p.state.status='live';p.state.station_id='two';await p.poll();
  assert.notEqual(p.element('#audio').src,original);
  assert.match(p.element('#audio').src,/^\/stream/);
});
test('Returning to a suspended tab opens a fresh live connection',async()=>{
  const p=await player();await p.click();const original=p.element('#audio').src;
  p.document.events.visibilitychange();await p.flush();
  assert.notEqual(p.element('#audio').src,original);
});

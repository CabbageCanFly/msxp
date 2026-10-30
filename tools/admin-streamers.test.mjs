import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const source=await readFile(new URL('../src/exp_tracker/web/admin-streamers.js',import.meta.url),'utf8');
const {streamerUI}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.handlers={};this.value='';this.dataset={};this.hidden=false;this.checked=false;this.classList={toggle(){}};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  addEventListener(type,fn){this.handlers[type]=fn;}
  async trigger(type){return this.handlers[type]?.({preventDefault(){}});}
  reset(){} focus(){this.focused=true;}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function setup(t, responder=async()=>({managed:true,streamers:[]})){
  const nodes=new Map(),calls=[];
  const old={document:globalThis.document,setInterval:globalThis.setInterval,clearInterval:globalThis.clearInterval};
  globalThis.document={hidden:false,createElement:tag=>new Element(tag),getElementById:id=>{
    if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);
  }};
  globalThis.setInterval=()=>1;globalThis.clearInterval=()=>{};
  const ui=streamerUI({api:async(path,data)=>{calls.push([path,data]);return responder(path,data);}});
  t.after(()=>{ui.close();Object.assign(globalThis,old);});
  return {nodes,calls,ui};
}
test('adding an unknown streamer assumes capture authorization',async t=>{
  const {nodes,calls}=setup(t,async(path,data)=>path==='/api/preview'?{preview_id:'p',before:null,after:data}:path==='/api/save'?{saved:true}:{managed:true,streamers:[]});
  await flush();await nodes.get('streamer-add').trigger('click');
  nodes.get('streamer-login').value='NewCaster';
  nodes.get('streamer-tracking_enabled').checked=true;document.getElementById('streamer-reason').value='Approved test stream';
  await nodes.get('streamer-form').trigger('submit');
  const data=calls.find(([path])=>path==='/api/preview')[1];
  assert.equal(data.channel,'NewCaster');assert.equal(data.automatic_characters,true);
  assert.equal(data.interval,20);assert.equal(data.authorized,true);assert.equal(data.tracking_enabled,true);
  assert.ok(!('character' in data));assert.equal(calls.filter(([p])=>p==='/api/save').length,0);
  await nodes.get('streamer-confirm').trigger('click');
  assert.deepEqual(calls.find(([path])=>path==='/api/save')[1],{preview_id:'p'});
});
test('new streamers assume authorization but start paused until explicitly reviewed',async t=>{
  const {nodes}=setup(t);await flush();await nodes.get('streamer-add').trigger('click');
  assert.equal(nodes.get('streamer-authorized').checked,true);
  assert.equal(nodes.get('streamer-authorization').hidden,true);
  assert.equal(nodes.get('streamer-tracking_enabled').checked,false);
  assert.equal(nodes.get('streamer-public_visible').checked,true);
  assert.equal(nodes.get('streamer-automatic_characters').checked,true);
});
test('editing invalidates an in-flight preview so an old response cannot be confirmed',async t=>{
  let resolvePreview;
  const {nodes,calls}=setup(t,async path=>path==='/api/preview'?new Promise(resolve=>{resolvePreview=resolve;}):{managed:true,streamers:[]});
  await flush();await nodes.get('streamer-add').trigger('click');
  const pending=nodes.get('streamer-form').trigger('submit');await flush();
  await nodes.get('streamer-form').trigger('input');resolvePreview({preview_id:'old'});await pending;
  await nodes.get('streamer-confirm').trigger('click');
  assert.equal(calls.filter(([path])=>path==='/api/save').length,0);
  assert.equal(nodes.get('streamer-review').hidden,true);
});
test('runtime errors are shown and configuring does not couple visibility to tracking',async t=>{
  const {nodes}=setup(t,async()=>({managed:true,streamers:[{channel:'caster',tracking_enabled:true,public_visible:false,
    automatic_characters:false,authorized:true,interval:20,quality:'720p60',character:{label:'Mage'},
    runtime:{state:'error',heartbeat_at:new Date().toISOString(),error:'Ownership conflict'}}]}));
  await flush();const card=nodes.get('streamer-list').children[0];
  assert.match(card.children[1].textContent,/Tracking requested.*Hidden/);
  assert.equal(card.children[2].textContent,'Ownership conflict');
  await card.children.at(-1).trigger('click');
  assert.equal(nodes.get('streamer-public_visible').checked,false);
  assert.equal(nodes.get('streamer-tracking_enabled').checked,true);
  assert.equal(nodes.get('streamer-login').readOnly,true);
  assert.equal(nodes.get('streamer-authorization').hidden,false);
});
test('unbootstrapped databases display setup guidance and refuse add through the UI',async t=>{
  const {nodes}=setup(t,async()=>({managed:false,streamers:[],notice:'Bootstrap required'}));
  await flush();assert.equal(nodes.get('streamer-add').disabled,true);
  assert.equal(nodes.get('streamer-status').textContent,'Bootstrap required');
});

test('paused settings explicitly select a fixed character without enabling discovery',async t=>{
  const {nodes,calls}=setup(t,async(path,data)=>path==='/api/preview'?{preview_id:'fixed',before:{},after:data}:
    {managed:true,streamers:[{channel:'caster',tracking_enabled:false,automatic_characters:false,
      character:{id:1,label:'CharA'},characters:[{id:1,label:'CharA'},{id:2,label:'CharB'}]}]});
  await flush();const card=nodes.get('streamer-list').children[0];
  assert.match(card.children[0].textContent,/Selected character: CharA/);
  await card.children.at(-1).trigger('click');
  const select=nodes.get('streamer-selected-character');
  assert.equal(select.disabled,false);assert.equal(select.children[2].textContent,'Track CharB');
  select.value='2';nodes.get('streamer-tracking_enabled').checked=true;
  await nodes.get('streamer-form').trigger('submit');
  const data=calls.find(([path])=>path==='/api/preview')[1];
  assert.equal(data.selected_character_id,2);assert.equal(data.tracking_enabled,true);assert.equal(data.automatic_characters,false);
});

test('active tracking cannot submit a manual selection and waiting state is explained',async t=>{
  const {nodes,calls}=setup(t,async(path,data)=>path==='/api/preview'?{preview_id:'p',after:data}:
    {managed:true,streamers:[{channel:'caster',tracking_enabled:true,automatic_characters:false,
      runtime:{state:'waiting_for_character',heartbeat_at:new Date().toISOString()},characters:[]}]});
  await flush();const card=nodes.get('streamer-list').children[0];
  assert.match(card.children[2].textContent,/Waiting for character selection/);
  await card.children.at(-1).trigger('click');
  assert.equal(nodes.get('streamer-selected-character').disabled,true);
  nodes.get('streamer-selected-character').value='2';
  await nodes.get('streamer-form').trigger('submit');
  assert.equal('selected_character_id' in calls.find(([path])=>path==='/api/preview')[1],false);
});

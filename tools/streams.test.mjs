import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";
const source=readFileSync(new URL('../src/exp_tracker/web/streams.js',import.meta.url),'utf8');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
}
function page(){
  const elements={},timers=[];
  const context=vm.createContext({Intl,BigInt,AbortController,performance:{now:()=>0},
    document:{hidden:false,getElementById:id=>elements[id]??=new Element(),createElement:tag=>new Element(tag)},
    fetch:()=>new Promise(()=>{}),setTimeout:(callback,delay)=>{timers.push({callback,delay});return timers.length;},clearTimeout:()=>{},setInterval:()=>{}});
  vm.runInContext(source,context);
  return {elements,timers,context,render:data=>{context.fixture=data;vm.runInContext('directory=fixture;receivedAt=0;renderDirectory()',context);}};
}
function text(node){return [node.textContent,...node.children.map(text)].filter(Boolean).join(' ');}
function card(changes={}){return {channel:'alpha',character:{label:'Explicit character'},source_status:'diagnostic_pair',run_status:'completed',
  age_seconds:1,stale_after_seconds:45,stale:false,percentage_age_seconds:2,
  percentage:{percentage:'33.05',evidence:'grammar_recovered'},full_exp:{exp:'123456',percentage:'33.05',evidence:'strict_full',timestamp:'2026-01-01T00:00:00Z'},
  movement:{difference_bp:5,difference_percentage_points:'0.05',change:'positive'},...changes};}

test('directory retains distinct real data, explicit assignment and unverified evidence labels',()=>{
  const p=page();p.render({streams:[card(),card({channel:'beta',character:null,percentage:null,full_exp:null,age_seconds:null,run_status:'waiting',movement:null})]});
  assert.equal(p.elements.streams.children.length,2);
  assert.equal(p.elements.streams.children[0].children[0].children[0].href,'/dashboard/alpha');
  assert.equal(p.elements.streams.children[1].children[0].children[0].href,'/dashboard/beta');
  assert.match(text(p.elements.streams.children[0]),/33.05%.*grammar-recovered proposal/);
  assert.match(text(p.elements.streams.children[1]),/Character not selected.*No capture attempts yet.*Percentage unavailable.*Full EXP unavailable/);
  assert.ok(!text(p.elements.streams.children[1]).includes('123,456'));
});
test('clock advances through cache failures; no assumed online status or freshness',async()=>{
  const p=page();p.render({streams:[card({run_status:'unfinished'})]});
  p.context.performance.now=()=>60000;vm.runInContext('renderDirectory()',p.context);
  assert.match(text(p.elements.streams.children[0]),/activity unknown.*61s.*STALE/);
  p.context.fetch=async()=>({ok:false});await vm.runInContext('pollDirectory()',p.context);
  assert.match(p.elements['directory-notice'].textContent,/disconnected.*cached UNVERIFIED/);
  assert.equal(p.elements.streams.children.length,1);
  p.render({streams:[card({run_status:'active'})]});
  assert.match(text(p.elements.streams.children[0]),/previously active.*current activity unknown/);
});
test('empty, interrupted and stale values stay explicit; labels are literal text',async()=>{
  const p=page();p.render({streams:[]});assert.equal(p.elements['directory-empty'].hidden,false);
  p.render({streams:[card({character:{label:'<img onerror=bad>'},run_status:'interrupted',stale:true})]});
  assert.match(text(p.elements.streams.children[0]),/<img onerror=bad>.*interrupted/);
  assert.ok(!source.includes('innerHTML'));
  const urls=[];p.context.fetch=async(url,options)=>{urls.push(url);assert.equal(options.cache,'no-store');return {ok:true,json:async()=>({streams:[]})};};
  await vm.runInContext('pollDirectory()',p.context);
  assert.deepEqual(urls,['/dev/api/streams']);assert.equal(p.timers.at(-1).delay,2000);
});

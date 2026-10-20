import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const url=source=>'data:text/javascript;base64,'+Buffer.from(source).toString('base64');
const time=await readFile(new URL('../src/exp_tracker/web/admin-time.js',import.meta.url),'utf8');
const source=await readFile(new URL('../src/exp_tracker/web/admin-invalidations.js',import.meta.url),'utf8');
const {invalidationUI}=await import(url(source.replace("'./admin-time.js'",JSON.stringify(url(time)))));

class Element {
  constructor(tag='div') {this.tag=tag;this.children=[];this.value='';this.textContent='';this.dataset={};}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children=nodes;}
  addEventListener() {}
  reset() {}
}
function render(expiredCount,readings) {
  const nodes=new Map();
  globalThis.document={createElement:tag=>new Element(tag),getElementById:id=>{
    if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);
  }};
  const ui=invalidationUI({api:()=>{throw Error('Rendering must not write');},onSaved:()=>{}});
  ui.update({channel:'alpha',character:{id:1,label:'Mage'},characters:[],
    invalidated:{readings},invalidation_history:{batches:[{id:1,action:'invalidate',count:2,remaining:2,
      expired_count:expiredCount,committed_at:'2026-01-01T00:00:00Z'}]}},[]);
  return nodes;
}
function all(node) {return [node,...node.children.flatMap(all)];}
const reading=(identity,expired)=>({identity,expired,timestamp:'2026-01-01T00:00:00Z',original:null});

test('mixed expired batches explain expiry and retain individual Restore only for retained sources',()=>{
  const nodes=render(1,[reading('old',true),reading('retained',false)]);
  const history=all(nodes.get('invalidation-history'));
  assert.equal(history.filter(n=>n.tag==='button').length,0);
  assert.match(history.map(n=>n.textContent).join(' '),/expired.*Whole-batch restore is unavailable.*individual Restore/);
  assert.deepEqual(all(nodes.get('invalidated-list')).filter(n=>n.tag==='button').map(n=>n.textContent),['Restore']);
});
test('fully expired batches offer no Restore action',()=>{
  const nodes=render(2,[reading('old1',true),reading('old2',true)]);
  for(const id of ['invalidation-history','invalidated-list'])assert.equal(all(nodes.get(id)).filter(n=>n.tag==='button').length,0);
});
test('retained batches keep the whole-batch Restore action',()=>{
  const nodes=render(0,[reading('a',false),reading('b',false)]);
  assert.deepEqual(all(nodes.get('invalidation-history')).filter(n=>n.tag==='button').map(n=>n.textContent),['Restore batch (2)']);
});

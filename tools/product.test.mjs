import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../src/exp_tracker/web/product.js',import.meta.url),'utf8');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.style={};}
  append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;}
  setAttribute(k,v){this.attributes[k]=String(v);}addEventListener(k,v){(this.listeners??={})[k]=v;}
  getBoundingClientRect(){return this.bounds??{left:100,top:200,bottom:220,width:100,height:20};}
}
function page(view='overlay',fetcher=()=>new Promise(()=>{})){
  const elements={},timers=[],events={};
  const buttons=[5,10,15,30,60].map(minutes=>{const button=new Element();button.dataset.window=String(minutes);return button;});
  const context=vm.createContext({Intl,Date,BigInt,AbortController,performance:{now:()=>0},
    location:{pathname:view==='overlay'?'/live/overlay/alpha':'/stream/alpha',origin:'http://127.0.0.1:8765'},innerWidth:390,innerHeight:700,
    navigator:{},addEventListener:(name,fn)=>{events[name]=fn;},document:{body:Object.assign(new Element('body'),{dataset:{view}}),hidden:false,addEventListener:(name,fn)=>{events[name]=fn;},getElementById:id=>elements[id]??=new Element(),
      querySelectorAll:selector=>selector==='[data-window]'?buttons:[],createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>new Element(tag)},
    fetch:fetcher,setInterval:()=>{},setTimeout:(fn,delay)=>{timers.push(delay);return timers.length;},clearTimeout:()=>{}});
  vm.runInContext(source,context);
  return {context,elements,timers,buttons,events,run:expression=>vm.runInContext(expression,context),render:player=>{context.fixture={player};vm.runInContext('data=fixture;receivedAt=0;renderPlayer()',context);}};
}
function player(changes={}){return {channel:'alpha',character:{label:'Main'},source_kind:'twitch',reading:{exp:'71441',percentage:'5.90',bp:590,evidence:'strict_full',timestamp:'2026-01-01T00:00:00Z',level:{value:60,status:'agreement'}},
  age_seconds:1,stale:false,stale_after_seconds:45,activity:{state:'waiting'},segment:{readings:3,difference_percentage_points:'0.05',span_seconds:{approximate:30}},
  estimates:{exp_per_hour:{value:{approximate:2000},requirement:{version:'test'},hypotheses:{}},percentage_per_hour:{value:{approximate:12}},eta:{seconds:{approximate:900}}},...changes};}
test('overlay updates percentage-only without borrowing absolute EXP; recovered values stay marked',()=>{
  const p=page();p.render(player());assert.equal(p.elements.exp.textContent,'71.4K');assert.match(p.elements.exp.title,/71,441/);assert.equal(p.elements.progress.value,5.9);
  p.render(player({reading:{exp:null,percentage:'6.00',bp:600,evidence:'strict_percentage_only',level:{value:60,status:'single_reader'}}}));
  assert.equal(p.elements.exp.textContent,'—');assert.equal(p.elements.progress.value,6);assert.equal(p.elements.level.textContent,'Lv. 60');
  p.render(player({reading:{exp:'71441',percentage:'5.90',bp:590,evidence:'grammar_recovered',level:{value:null,status:'conflict',visual:54,neural:64}}}));
  assert.match(p.elements.exp.textContent,/^~/);assert.equal(p.elements.level.textContent,'Lv. —');assert.match(p.elements.level.title,/54 \/ 64/);
});
test('cached failures and advancing ages preserve values but suppress rates and ETA',()=>{
  const p=page();p.render(player());assert.equal(p.elements.rate.textContent,'~2K');assert.equal(p.elements.eta.textContent,'~15m');
  p.context.performance.now=()=>50000;p.run('renderPlayer()');assert.equal(p.elements.rate.textContent,'—');assert.equal(p.elements.exp.textContent,'71.4K');assert.equal(p.elements.status.textContent,'Updates delayed');
  p.context.performance.now=()=>0;p.run('failed=true;renderPlayer()');assert.equal(p.elements.eta.textContent,'—');assert.equal(p.elements.card.dataset.stale,'true');
});

test('unreadable HUD retains dated rate without assuming zero gain, expires and never ranks it',()=>{
  const p=page(),base=player();
  base.latest_attempt_status='malformed_or_unavailable';
  base.responsive_pace={active:false,tentative:false,age_seconds:60,end:'2026-01-01T00:00:00Z',readings:11,
    span_seconds:{approximate:200},coverage_seconds:{approximate:200},estimates:base.estimates,
    presentation:{can_age:false,state:'historical',history_after_seconds:300,expire_after_seconds:1800,running:true}};
  p.render(base);assert.equal(p.elements.rate.textContent,'~2K');assert.equal(p.elements.eta.textContent,'—');
  assert.match(p.run('earlyText(data.player)'),/last observed 1m ago/);
  p.run('failed=true;renderPlayer()');assert.equal(p.elements.rate.textContent,'~2K');
  p.run('failed=false');
  const board=page('board');board.context.sample=base;
  assert.equal(board.run('metricValue(sample,"exp_hour")'),null);
  p.context.performance.now=()=>240000;p.run('renderPlayer()');
  assert.equal(p.elements.rate.textContent,'~2K');assert.match(p.run('earlyText(data.player)'),/last observed 5m ago/);
  assert.equal(p.elements.eta.textContent,'—');
  p.context.performance.now=()=>1740000;p.run('renderPlayer()');
  assert.equal(p.elements.rate.textContent,'—');assert.match(p.run('earlyText(data.player)'),/Pace paused/);
  p.context.performance.now=()=>0;base.responsive_pace.presentation={state:'historical',can_age:false};
  base.activity={state:'capture_finished'};p.render(base);
  assert.equal(p.elements.rate.textContent,'~2K');assert.equal(p.elements.status.textContent,'Capture finished');
});

test('official live/offline and unknown status stay separate from capture and expire',()=>{
  const p=page();
  p.render(player({reading:null,latest_attempt_status:'capture_failed',twitch:{status:'live'}}));
  assert.equal(p.elements.status.textContent,'Twitch live · Capture unavailable');
  p.render(player({reading:null,latest_attempt_status:'capture_failed',twitch:{status:'offline'}}));
  assert.equal(p.elements.status.textContent,'Twitch offline · Capture unavailable');
  p.render(player({reading:null,latest_attempt_status:'capture_failed',twitch:{status:'unknown'}}));
  assert.equal(p.elements.status.textContent,'Live status unknown · Capture unavailable');
  p.render(player({twitch:{status:'offline',capture_disagreement:true}}));
  assert.equal(p.elements.status.textContent,'Twitch offline · Recent capture differs');
  p.render(player({twitch:{status:'live'},stale:true,age_seconds:60,latest_attempt_status:'malformed_or_unavailable',
    latest_attempt_at:'2026-01-01T00:01:00Z',latest_attempt_age_seconds:1}));
  assert.equal(p.elements.status.textContent,'Twitch live · HUD unreadable');
  p.render(player({reading:null,latest_attempt_status:'capture_failed',twitch:{status:'live',valid_until:'2026-01-01T00:01:00Z'}}));
  p.run('data.served_at="2026-01-01T00:00:00Z"');p.context.performance.now=()=>61000;p.run('renderPlayer()');
  assert.equal(p.elements.status.textContent,'Live status unknown · Capture unavailable');
});
test('unavailable rates are not ranked as zero and equal eligible values share rank',()=>{
  const p=page('board'),eligible={eligible:true,estimates:player().estimates,difference_percentage_points:'0.20'};
  p.context.fixtures=[player({channel:'b',windows:{5:eligible}}),player({channel:'a',windows:{5:eligible}}),player({channel:'c',estimates:{}})];
  const rows=JSON.parse(p.run('JSON.stringify(ranked(fixtures,"exp_hour").map(r=>({channel:r.player.channel,value:r.value,rank:r.rank})))'));
  assert.deepEqual(rows.map(r=>r.rank),[1,1,null]);assert.deepEqual(rows.map(r=>r.channel),['a','b','c']);
  p.render(player({activity:{state:'coordinator_stopped'}}));assert.equal(p.elements.status.textContent,'Capture paused');
  assert.ok(!source.includes('innerHTML'));
});

test('window buttons use only eligible window metrics; overlay keeps its existing segment estimates',()=>{
  const p=page('player'),base=player();
  base.windows={5:{eligible:true,estimates:base.estimates,difference_percentage_points:'0.20',readings:21,coverage_seconds:{approximate:300}},
    10:{eligible:false,state:'building_history',estimates:{}}};
  p.render(base);assert.equal(p.elements.movement.textContent,'+0.20%');assert.equal(p.elements.rate.textContent,'~2,000');
  p.buttons[1].listeners.click();assert.equal(p.elements.movement.textContent,'—');assert.equal(p.elements.rate.textContent,'—');
  assert.match(p.elements['segment-note'].textContent,/Building 10m history/);
  assert.equal(p.buttons[1].attributes['aria-pressed'],'true');
  const overlay=page();overlay.render({...base,windows:{}});assert.equal(overlay.elements.rate.textContent,'~2K');
  p.context.fixtures=[base,{...base,channel:'b',windows:{}}];
  assert.deepEqual(JSON.parse(p.run('JSON.stringify(ranked(fixtures,"movement").map(r=>r.rank))')),[null,null]);
});

test('recent graph excludes distant runs, spans actual points, and retains gaps on a longer selection',()=>{
  const p=page('player');p.render(player());
  const point=(timestamp,bp=100)=>({event_id:timestamp,timestamp,interval_seconds:15,level:{value:64},reading:{bp,percentage:(bp/100).toFixed(2),evidence:'strict_percentage_only'}});
  p.context.points=[point('2026-01-01T00:00:00Z'),point('2026-01-01T00:06:00Z'),point('2026-01-01T00:06:15Z',101)];
  p.run('chartMode="percentage";data.history=points;drawHistory()');
  assert.equal(p.elements['history-chart'].dataset.start,'2026-01-01T00:06:00.000Z');
  // The fixture's level-64 points are gaps on the level-60 player, not readings.
  assert.match(p.elements['history-note'].textContent,/0 readings.*2 unavailable.*15s displayed/);
  p.buttons[1].listeners.click();assert.equal(p.elements['history-chart'].dataset.start,'2026-01-01T00:00:00.000Z');
  assert.ok(p.elements['history-chart'].children.some(n=>n.attributes.class==='gap'));
  assert.ok(!p.elements['history-chart'].children.some(n=>n.tag==='polyline'));
  p.elements['history-chart'].clientWidth=340;p.run('drawHistory()');
  assert.equal(p.elements['history-chart'].attributes.viewBox,'0 0 340 230');
  assert.equal(p.elements['history-chart'].children.filter(n=>n.tag==='text' && n.attributes.y==='218').length,3);
});

test('pooled pace discloses sampled seconds and separate sequences, not the whole extent',()=>{
  const p=page('player'),base=player();
  base.responsive_pace={active:true,tentative:false,age_seconds:1,start:'2026-01-01T00:00:00Z',end:'2026-01-01T00:04:00Z',
    readings:11,span_seconds:{approximate:240},coverage_seconds:{approximate:179.75},interruptions:1,estimates:base.estimates};
  p.render(base);
  assert.match(p.elements['early-value'].textContent,/recent trend.*11 readings \/ 180s sampled.*2 sequences/);
  assert.match(p.elements.rate.title,/180s sampled/);
  assert.doesNotMatch(p.elements['early-value'].textContent,/240s/);
  base.responsive_pace.tentative=true;base.responsive_pace.readings=2;base.responsive_pace.interruptions=0;
  base.responsive_pace.coverage_seconds.approximate=15;
  p.render(base);assert.match(p.elements['early-value'].textContent,/first estimate.*2 readings \/ 15s sampled.*1 sequence$/);
});

test('percentage chart counts numerical points separately from missing and unknown-level attempts',()=>{
  const p=page('player');p.render(player());
  p.context.points=[
    {event_id:'a',timestamp:'2026-01-01T00:00:00Z',level:{value:60},reading:{bp:590,percentage:'5.90',evidence:'strict_full'}},
    {event_id:'b',timestamp:'2026-01-01T00:00:15Z',level:{value:null},reading:null},
    {event_id:'c',timestamp:'2026-01-01T00:00:30Z',level:{value:null},reading:{bp:591,percentage:'5.91',evidence:'strict_full'}},
    {event_id:'d',timestamp:'2026-01-01T00:00:45Z',level:{value:60},reading:{bp:592,percentage:'5.92',evidence:'strict_full'}}];
  p.run('chartMode="percentage";data.history=points;drawHistory()');
  assert.match(p.elements['history-note'].textContent,/2 readings.*2 unavailable.*45s displayed/);
  const shapes=p.elements['history-chart'].children;
  assert.equal(shapes.filter(n=>n.tag==='circle').length,2);
  assert.equal(shapes.filter(n=>n.tag==='path').length,2);
  assert.equal(shapes.filter(n=>n.tag==='line').length,0);
});

test('endpoint pace discloses elapsed gaps and conditional recovery is never strict OCR',()=>{
  const p=page('player'),base=player();
  base.responsive_pace={active:true,tentative:false,age_seconds:1,start:'2026-01-01T00:00:00Z',end:'2026-01-01T00:02:20Z',
    readings:6,span_seconds:{approximate:140},coverage_seconds:{approximate:140},interruptions:0,missing_attempts:2,
    interval_counts:{direct:3,endpoint_supported:2},estimates:base.estimates};
  base.reading={...base.reading,evidence:'conditional_symbol',grammar_policy:'conditional_percent_v1'};
  p.render(base);
  assert.match(p.elements['early-value'].textContent,/6 readings \/ 140s elapsed · 2 missing readings/);
  assert.match(p.elements['early-value'].title,/3 direct and 2 endpoint-supported intervals; gap time is included/);
  assert.match(p.elements.exp.textContent,/^~/);
  assert.match(p.elements.exp.title,/conditional X-to-% recovery/);
  assert.equal(p.run('metricValue(data.player,"exp_hour")'),null);
});

test('pace ranking changes with the selected window and never substitutes a short segment rate',()=>{
  const p=page('board'),window=rate=>({eligible:true,estimates:{exp_per_hour:{value:{approximate:rate}}}});
  p.context.fixtures=[player({channel:'a',windows:{5:window(100),30:window(300)}}),player({channel:'b',windows:{5:window(200)}})];
  assert.deepEqual(JSON.parse(p.run('JSON.stringify(ranked(fixtures,"exp_hour").map(r=>r.player.channel))')),['b','a']);
  p.run('windowMinutes=30');
  assert.deepEqual(JSON.parse(p.run('JSON.stringify(ranked(fixtures,"exp_hour").map(r=>[r.player.channel,r.rank]))')),[['a',1],['b',null]]);
});

test('observed windows show real partial endpoints without ranking them or relabeling recent pace',()=>{
  const p=page('player'),base=player();
  const observed={available:true,difference_percentage_points:'0.55',span_seconds:{approximate:208},
    readings:15,interruptions:1,unavailable_attempts:1,missing_attempts:0,age_seconds:1,paused:false};
  base.windows=Object.fromEntries([5,10,15,30].map((m,i)=>[m,{eligible:false,observed:{...observed,difference_percentage_points:`${i}.55`}}]));
  base.responsive_pace={active:true,tentative:false,readings:6,span_seconds:{approximate:75},age_seconds:1,estimates:base.estimates};
  p.render(base);
  for(let i=0;i<4;i++){
    p.buttons[i].listeners.click();
    assert.equal(p.elements.movement.textContent,`+${i}.55%`);
    assert.match(p.elements['segment-note'].textContent,/3m 28s.*15 readings.*2 sequences.*partial history/);
    assert.equal(p.elements['window-rate'].textContent,'Not complete yet');
    assert.equal(p.elements.rate.textContent,'~2,000');
  }
  p.context.fixtures=[base];assert.deepEqual(JSON.parse(p.run('JSON.stringify(ranked(fixtures,"movement").map(r=>r.rank))')),[null]);
  p.render({...base,stale:true});
  assert.equal(p.elements.movement.textContent,'+3.55%');assert.equal(p.elements.movement.dataset.paused,'true');
  assert.match(p.elements['segment-note'].textContent,/last updated/);
  assert.equal(p.elements['window-rate'].textContent,'Paused');
  p.run('failed=true;renderPlayer()');assert.match(p.elements['segment-note'].textContent,/last updated/);
});

test('withheld full EXP retains percentage and provisional level across product views',()=>{
  const p=page();p.render(player({reading:{exp:null,percentage:'45.09',bp:4509,evidence:'strict_full',
    exp_validity:{status:'invalid'},level:{value:65,status:'provisional_neural',visual:63,neural:65}}}));
  assert.equal(p.elements.exp.textContent,'—');assert.equal(p.elements.progress.value,45.09);
  assert.match(p.elements.exp.title,/withheld/);assert.equal(p.elements.level.textContent,'Lv. 65');
});

test('percentage-derived EXP is explicitly approximate and leaves direct OCR integer display intact',()=>{
  const p=page(),r={exp:null,percentage:'67.72',bp:6772,evidence:'strict_percentage_only',level:{value:65,status:'provisional_neural'},
    estimated_exp:{value:{approximate:1069917.0836},level_evidence:{value:65},requirement:{version:'synthetic'},
      hypotheses:{nearest_half_up:{min:1069839,max:1069996,count:158},truncate:{min:1069918,max:1070075,count:158}}}};
  p.render(player({reading:r}));assert.equal(p.elements.exp.textContent,'~1.07M');assert.match(p.elements.exp.title,/not read directly by OCR/);
  p.render(player({reading:{...r,exp:'1069917',estimated_exp:null,evidence:'strict_full'}}));
  assert.equal(p.elements.exp.textContent,'1.07M');assert.match(p.elements.exp.title,/original strict OCR/);
  p.render(player({reading:{...r,estimated_exp:null,level:{value:null,status:'conflict'}}}));assert.equal(p.elements.exp.textContent,'—');
});

test('polling continues in background, refreshes on return, and never overlaps an active request',async()=>{
  let calls=0,hang=false,release;
  const p=page('player',async()=>{calls++;return hang?new Promise(ok=>{release=ok;}):{ok:true,json:async()=>({player:player()})};});
  await new Promise(setImmediate);assert.equal(calls,1);
  p.context.document.hidden=true;await p.run('poll()');assert.equal(calls,2);
  hang=true;const pending=p.run('poll()');assert.equal(calls,3);
  p.context.document.hidden=false;p.events.visibilitychange();p.events.pageshow();assert.equal(calls,3);
  release({ok:false});await pending;assert.equal(p.elements.status.textContent,'Updates delayed');
  hang=false;p.events.pageshow();await new Promise(setImmediate);assert.equal(calls,4);
  assert.equal(p.elements.status.textContent,'Tracking');assert.equal(p.timers.at(-1),2000);
});

test('owned activity and completion stay distinct from cached API failures and stale values',()=>{
  const p=page();
  for(const [activity,text] of [[{state:'running'},'Updating'],[{state:'waiting'},'Tracking'],
    [{state:'stopped',completion:'completed'},'Capture finished'],[{state:'stopped',completion:'interrupted'},'Capture interrupted']]){
    p.render(player({activity}));assert.equal(p.elements.status.textContent,text);
  }
  p.render(player({activity:{state:'running'},stale:true}));assert.equal(p.elements.status.textContent,'Updates delayed');
});

test('pending percentage holds prior values, removes pace, and expires despite a slow configured cadence',()=>{
  const p=page(),base=player({stale_after_seconds:900,estimates:{},segment:null,
    percentage_state:{status:'pending_exp_decrease',public_eligible:false,pending_since:'2026-01-01T00:00:30Z',confirmation_deadline:'2026-01-01T00:01:30Z'}});
  p.render(base);assert.equal(p.elements.percentage.textContent,'5.90%');assert.equal(p.elements.status.textContent,'Verifying EXP change');
  assert.equal(p.elements.rate.textContent,'—');p.context.performance.now=()=>91000;p.run('renderPlayer()');
  assert.equal(p.elements.status.textContent,'Updates delayed');assert.equal(p.elements.percentage.textContent,'5.90%');
});

test('last-known level is labeled separately and never supplies missing EXP or pace',()=>{
  for(const view of ['player','overlay']) {
    const p=page(view),saved={value:65,timestamp:'2026-01-01T00:00:00Z',age_seconds:40,last_known:true,
      evidence:{value:65,status:'provisional_neural',reason:'repeated_neural_with_strict_arithmetic'}};
    p.render(player({display_level:saved,estimates:{},reading:{exp:null,percentage:'90.78',bp:9078,level:{value:null,status:'conflict'}}}));
    assert.equal(p.elements.level.textContent,'Lv. 65');assert.match(p.elements.level.title,/Last-known.*40s ago/);
    assert.equal(p.elements.exp.textContent,'—');assert.equal(p.elements.rate.textContent,'—');
    if(view==='player')assert.equal(p.elements['level-note'],undefined);
  }
});

test('early segment pace is visible before a complete window and becomes paused on stale or failed API',()=>{
  const p=page('player'),base=player();
  base.early_pace={active:true,segment:{...base.segment,start:'start',end:'end'},estimates:base.estimates};
  p.render(base);assert.match(p.elements['early-value'].textContent,/~2K EXP\/hour.*early estimate.*3 readings \/ 30s/);
  assert.equal(p.elements.rate.textContent,'—');assert.match(p.elements['segment-note'].textContent,/Building 5m/);
  p.context.performance.now=()=>50000;p.run('renderPlayer()');assert.equal(p.elements['early-value'].textContent,'Estimate paused');
  assert.match(p.elements['early-value'].title,/Historical value/);
  p.context.performance.now=()=>0;p.run('failed=true;renderPlayer()');assert.equal(p.elements['early-value'].textContent,'Estimate paused');
});

test('responsive pace has one current rate, retains an explicitly aged rate after gaps, and never ranks it',()=>{
  const p=page('player'),base=player();
  base.responsive_pace={active:true,tentative:true,age_seconds:0,readings:2,span_seconds:{approximate:15},estimates:{...base.estimates,eta:null}};
  p.render(base);assert.equal(p.elements.rate.textContent,'~2,000');assert.match(p.elements['early-value'].textContent,/first estimate.*2 readings \/ 15s/);
  assert.equal(p.elements['window-rate'].textContent,'Building history');
  p.render({...base,responsive_pace:{...base.responsive_pace,active:false,age_seconds:35}});
  assert.equal(p.elements.rate.textContent,'~2,000');assert.match(p.elements['early-value'].textContent,/last observed 35s ago/);
  assert.equal(p.elements.rate.dataset.paused,'true');assert.equal(p.elements['eta-stat'].hidden,false);
  p.context.fixtures=[base];assert.deepEqual(JSON.parse(p.run('JSON.stringify(ranked(fixtures,"exp_hour").map(r=>r.rank))')),[null]);
});

test('selected SQLite window controls gain, rate and tentative ETA while four cards stay present',()=>{
  const p=page('player'),base=player();
  base.responsive_pace={active:true,age_seconds:0,readings:2,span_seconds:{approximate:20},estimates:base.estimates};
  base.recent_windows=Object.fromEntries([5,10,15,30,60].map((minutes,i)=>[minutes,{status:'ready',available:true,
    pace:{...base.responsive_pace,tentative:i===0,estimates:{...base.estimates,exp_per_hour:{...base.estimates.exp_per_hour,value:{approximate:(i+1)*1000}}}},
    observed:{available:true,difference_percentage_points:'0.10',span_seconds:{approximate:20},coverage_seconds:{approximate:20},
      readings:2,age_seconds:0,interruptions:0,unavailable_attempts:0,missing_attempts:0,estimated_exp:{value:{approximate:(i+1)*100},requirement:{version:'test'}}}}]));
  p.render(base);
  for(let i=0;i<5;i++){
    p.buttons[i].listeners.click();
    assert.equal(p.elements.rate.textContent,'~'+((i+1)*1000).toLocaleString('en-US'));
    assert.equal(p.elements.movement.textContent,`+${(i+1)*100} EXP`);
    assert.equal(p.elements['eta-stat'].hidden,false);
    assert.equal(p.elements.eta.textContent,'~15m');
    assert.equal(p.elements['window-rate'].textContent,'Not complete yet');
  }
  p.buttons[0].listeners.click();assert.match(p.elements['eta-note'].textContent,/Early estimate.*2 readings/);
  base.recent_windows[5].pace.active=false;p.render(base);
  assert.equal(p.elements.eta.textContent,'—');assert.equal(p.elements['eta-stat'].hidden,false);
  assert.match(p.elements['eta-note'].textContent,/Waiting for fresh/);
  assert.equal(p.elements['level-note'],undefined);
  base.recent_windows[5]={status:'history_limit',available:false,observed:{available:false}};
  base.windows={5:{eligible:true,estimates:base.estimates,coverage_seconds:{approximate:300},readings:21}};
  p.render(base);assert.equal(p.elements.rate.textContent,'—');assert.equal(p.elements.movement.textContent,'—');
  assert.equal(p.elements['segment-note'].textContent,'Recent history unavailable');
});

test('selected historical rate is dated, has no current gain or ETA, and never falls back to a different window',()=>{
  const p=page('player'),base=player();
  base.responsive_pace={active:true,age_seconds:0,level:60,readings:2,span_seconds:{approximate:20},estimates:base.estimates};
  base.recent_windows={60:{status:'ready',available:false,observed:{available:false},last_observed_pace:{
    ...base.responsive_pace,active:false,age_seconds:400,estimates:{...base.estimates,exp_per_hour:{...base.estimates.exp_per_hour,value:{approximate:6000}}}}}};
  p.render(base);p.buttons[4].listeners.click();
  assert.equal(p.elements.rate.textContent,'~6,000');assert.equal(p.elements.movement.textContent,'—');
  assert.match(p.elements['early-value'].textContent,/last observed 6m ago/);
  assert.equal(p.elements.eta.textContent,'—');assert.equal(p.elements['eta-stat'].hidden,false);
  delete base.recent_windows[60].last_observed_pace;p.render(base);
  assert.equal(p.elements.rate.textContent,'—');
});

test('current-level chart separates level-up, missing samples and quarantine; only guarded edges get lines',()=>{
  const p=page('player'),base=player({display_level:{evidence:{value:66},value:66,age_seconds:0},level_events:[{level:66,timestamp:'2026-01-01T00:00:15Z',first_observed_at:'2026-01-01T00:00:15Z'}]});
  p.render(base);
  const point=(seconds,level,bp,connect_previous=false)=>({timestamp:new Date(Date.UTC(2026,0,1,0,0,seconds)).toISOString(),level:{value:level},interval_seconds:15,connect_previous,reading:bp==null?null:{bp,percentage:(bp/100).toFixed(2),evidence:'strict_full'}});
  p.context.points=[point(0,65,9997),point(15,66,1),point(30,66,3,true),point(45,66,null),point(60,66,8),point(75,66,12,true)];
  p.run('chartMode="percentage";data.history=points;drawHistory()');
  const shapes=p.elements['history-chart'].children;
  assert.equal(shapes.filter(n=>n.attributes.class==='trend').length,2);
  assert.ok(!shapes.some(n=>n.tag==='text' && n.textContent==='99.97%'));
  assert.equal(p.elements['level-event'].textContent,'Level 66 reached!');
  assert.equal(p.elements['history-chart'].dataset.start,'2026-01-01T00:00:15.000Z');
  assert.match(p.elements['history-note'].textContent,/Lv. 66/);
});

test('EXP bars split only valid captured intervals, conserve amounts, and preserve missing versus zero',()=>{
  const p=page('player'),base=Date.parse('2026-01-01T00:00:00Z');
  const interval=(a,b,value)=>({connect_previous:true,gain:{start:new Date(base+a*1000).toISOString(),end:new Date(base+b*1000).toISOString(),value:{approximate:value}}});
  p.context.rows=[interval(50,70,100),interval(120,150,0),{connect_previous:false,gain:{start:new Date(base+70e3).toISOString(),end:new Date(base+120e3).toISOString(),value:{approximate:999}}}];
  p.context.anchor=base+180e3;
  const chart=JSON.parse(p.run('JSON.stringify(bucketHistory(rows,anchor,60))'));
  assert.equal(chart.end-chart.start,1800000);assert.equal(chart.bins.length,30);
  const populated=chart.bins.filter(b=>b.value!==null);
  assert.deepEqual(populated.map(b=>b.value),[50,50,0]);assert.equal(populated.reduce((s,b)=>s+b.covered,0),50);
  assert.ok(chart.bins.some(b=>b.state==='missing' && b.value===null));
  assert.ok(populated.every(b=>b.state==='partial'));
  p.context.rows=[interval(0,60,0)];
  const zero=JSON.parse(p.run('JSON.stringify(bucketHistory(rows,anchor,60))')).bins.find(b=>b.value===0);
  assert.equal(zero.state,'covered');assert.equal(zero.covered,60);
  assert.equal(p.run('bucketHistory(rows,anchor,5)'),null);
});

test('EXP history has fixed axes and the 24h view waits for aggregated history',()=>{
  const p=page('player');p.render(player());
  p.context.rows=[{connect_previous:true,gain:{start:'2026-01-01T00:00:00Z',end:'2026-01-01T00:00:15Z',value:{approximate:100}}}];
  p.run('data.history=rows;data.player.latest_attempt_at="2026-01-01T00:00:15Z";drawHistory()');
  assert.equal(p.elements['history-chart'].children.filter(n=>n.attributes.class==='exp-column missing').length,29);
  assert.equal(p.elements['history-chart'].children.filter(n=>n.attributes.class==='exp-column partial').length,1);
  p.run('data.served_at="2026-01-01T00:00:15Z"');
  for(const [bucket,seconds] of [[60,1800],[300,7200],[1800,86400]]){
    p.run(`bucketSeconds=${bucket};drawHistory()`);
    assert.equal(Date.parse(p.elements['history-chart'].dataset.end)-Date.parse(p.elements['history-chart'].dataset.start),seconds*1000);
  }
  p.elements['history-chart'].clientWidth=340;p.run('drawHistory()');
  assert.equal(p.elements['history-chart'].attributes.viewBox,'0 0 340 250');
});

test('24h summary and bars use the server total, retain zero, and age cached failures',()=>{
  const p=page('player');p.render(player());
  p.context.rolling={start:'2025-12-31T00:01:00+00:00',end:'2026-01-01T00:01:00+00:00',as_of:'2026-01-01T00:01:00+00:00',
    tracked_exp:{approximate:12345},coverage_seconds:{approximate:120},intervals:8,status:'ready',
    buckets:Array.from({length:48},(_,i)=>({start:new Date(Date.UTC(2025,11,31,0,1)+i*1800e3).toISOString(),end:new Date(Date.UTC(2025,11,31,0,1)+(i+1)*1800e3).toISOString(),
      value:i===47?{approximate:12345}:null,covered:{approximate:i===47?120:0},state:i===47?'partial':'missing'}))};
  p.run('rollingData=rolling;bucketSeconds=1800;renderPlayer();drawHistory()');
  assert.equal(p.elements['tracked-exp'].textContent,'~12,345');assert.match(p.elements['tracked-note'].textContent,/2m 0s tracked/);
  assert.equal(p.elements['history-chart'].children.filter(n=>n.attributes.class==='exp-column missing').length,47);
  p.context.performance.now=()=>35000;p.run('rollingFailed=true;renderPlayer()');
  assert.equal(p.elements['tracked-exp'].textContent,'~12,345');assert.match(p.elements['tracked-note'].textContent,/Saved.*35s ago/);
  p.run('rollingData.tracked_exp={approximate:0};renderPlayer()');assert.equal(p.elements['tracked-exp'].textContent,'~0');
  p.run('data.player.character.id=2;renderPlayer();drawHistory()');
  assert.equal(p.elements['tracked-exp'].textContent,'—');assert.equal(p.elements['tracked-exp'].title,'');
  assert.ok(!p.elements['history-chart'].children.some(n=>n.attributes.class==='exp-column partial'));
});

test('public progress uses EXP with percentage fallback and exact provenance in the tooltip',()=>{
  const p=page('player'),base=player({windows:{5:{eligible:false,observed:{available:true,
    difference_percentage_points:'0.14',estimated_exp:{value:{approximate:2329.7904},requirement:{version:'synthetic'}},
    span_seconds:{approximate:45},readings:4,interruptions:0,age_seconds:1}}}});
  p.render(base);assert.equal(p.elements.movement.textContent,'+2,330 EXP');assert.match(p.elements.movement.title,/0.14 percentage points/);
  delete base.windows[5].observed.estimated_exp;p.render(base);assert.equal(p.elements.movement.textContent,'+0.14%');
  assert.equal(p.run('expText(1234567890)'),'1.23B');assert.equal(p.run('expText(45)'),'45');
});

test('history polling is separate, bounded to one request, and invalidated by new attempts',async()=>{
  const calls=[];let resolveHistory;
  const p=page('player',url=>{calls.push(url);return new Promise(ok=>{if(url.endsWith('/history'))resolveHistory=ok;});});
  p.render(player({latest_attempt_at:'first'}));
  const pending=p.run('pollRolling()');await p.run('pollRolling(true)');
  assert.equal(calls.filter(u=>u.endsWith('/history')).length,1);
  resolveHistory({ok:false});await pending;
  assert.equal(p.elements['tracked-exp'].textContent,'—');assert.equal(p.elements['tracked-note'].textContent,'History unavailable');
  const success=p.run('pollRolling()');
  resolveHistory({ok:true,json:async()=>({status:'ready',buckets:Array.from({length:48},()=>({value:null,covered:{approximate:0}})),tracked_exp:null,coverage_seconds:{approximate:0},intervals:0})});
  await success;const count=calls.length;await p.run('pollRolling()');assert.equal(calls.length,count);
  p.run('data.player.latest_attempt_at="next";pollRolling()');assert.equal(calls.length,count+1);
  assert.ok(p.timers.includes(30000));
});

test('wide values retain whole numbers; measured overflow uses compact text and restores on resize',()=>{
  const p=page('player');p.render(player({windows:{5:{eligible:true,estimates:player().estimates,coverage_seconds:{approximate:300},readings:21}}}));
  assert.equal(p.elements.exp.textContent,'71,441 EXP');assert.equal(p.elements.rate.textContent,'~2,000');
  p.elements.exp.clientWidth=80;p.elements.exp.scrollWidth=130;p.run('renderPlayer()');
  assert.equal(p.elements.exp.textContent,'71.4K');assert.match(p.elements.exp.title,/71,441/);
  p.elements.exp.clientWidth=300;p.run('renderPlayer()');assert.equal(p.elements.exp.textContent,'71,441 EXP');
  assert.equal(p.run('expText(12345.678,true)'),'12,346');
});

test('completed/stopped capture labels take precedence over stale data but not API failures',()=>{
  const p=page('player');
  p.render(player({stale:true,activity:{state:'capture_finished'}}));assert.equal(p.elements.status.textContent,'Capture finished');
  p.render(player({stale:true,age_seconds:480,activity:{state:'coordinator_stopped'}}));assert.equal(p.elements.status.textContent,'Last tracked 8m ago');
  p.run('failed=true;renderPlayer()');assert.equal(p.elements.status.textContent,'Updates delayed');
});

test('chart inspection supports focus, touch, Escape and viewport bounds without HTML injection',()=>{
  const p=page('player');p.context.mark=new Element('circle');
  p.run('inspect(mark,"sample","No reading\\n<not HTML>")');
  p.context.mark.listeners.focus();
  assert.equal(p.run('tip.textContent'),'No reading\n<not HTML>');assert.equal(p.run('tip.hidden'),false);
  assert.equal(p.context.mark.attributes['aria-label'],'No reading\n<not HTML>');
  assert.ok(parseFloat(p.run('tip.style.left'))>=8);
  p.events.keydown({key:'Escape'});assert.equal(p.run('tip.hidden'),true);
  p.context.mark.listeners.pointerdown({pointerType:'touch'});assert.equal(p.run('tip.hidden'),false);
  p.context.mark.listeners.pointerdown({pointerType:'touch'});assert.equal(p.run('tip.hidden'),true);
});

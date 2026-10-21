import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../src/exp_tracker/web/product.js',import.meta.url),'utf8');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.style={};this.value='';}
  append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;}
  querySelector(){return null;}querySelectorAll(){return [];}contains(){return false;}focus(){}scrollIntoView(){}
  setAttribute(k,v){this.attributes[k]=String(v);}addEventListener(k,v,options){(this.listeners??={})[k]=v;(this.listenerOptions??={})[k]=options;}
  getBoundingClientRect(){return this.bounds??{left:100,top:200,bottom:220,width:100,height:20};}
}
function page(view='overlay',fetcher=()=>new Promise(()=>{}),search='',api=null){
  const elements={},timers=[],events={},visits=[];
  const buttons=[5,10,15,30,60].map(minutes=>{const button=new Element();button.dataset.window=String(minutes);return button;});
  const pathname=view==='overlay'?'/live/overlay/alpha':view==='board'?'/':'/stream/alpha';
  const modes=['streamers','characters'].map(mode=>{const button=new Element();button.dataset.mode=mode;return button;});
  const context=vm.createContext({Intl,Date,BigInt,AbortController,URL,URLSearchParams,performance:{now:()=>0},
    location:{pathname,search,href:'http://127.0.0.1:8765'+pathname+search,origin:'http://127.0.0.1:8765'},innerWidth:390,innerHeight:700,
    history:{pushState:(s,t,u)=>visits.push(['push',String(u)]),replaceState:(s,t,u)=>visits.push(['replace',String(u)])},
    navigator:{},addEventListener:(name,fn)=>{events[name]=fn;},document:{documentElement:{dataset:api==null?{}:{api}},body:Object.assign(new Element('body'),{dataset:{view}}),hidden:false,addEventListener:(name,fn)=>{events[name]=fn;},getElementById:id=>elements[id]??=new Element(),
      querySelectorAll:selector=>selector==='[data-window]'?buttons:selector==='[data-mode]'?modes:[],createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>new Element(tag)},
    fetch:fetcher,setInterval:()=>{},setTimeout:(fn,delay)=>{timers.push(delay);return timers.length;},clearTimeout:()=>{}});
  vm.runInContext(source,context);
  // Most cases below were written against the original 5 minute card and chart windows with 1 minute bars.
  if(view==='player' && !search.includes('defaults'))vm.runInContext('windowMinutes=5;lineWindow=5;chartWindow=5;bucketSeconds=60',context);
  return {context,elements,timers,buttons,modes,events,visits,run:expression=>vm.runInContext(expression,context),render:player=>{context.fixture={player};vm.runInContext('data=fixture;receivedAt=0;renderPlayer()',context);}};
}
function player(changes={}){return {channel:'alpha',character:{label:'Main'},source_kind:'twitch',reading:{exp:'71441',percentage:'5.90',bp:590,evidence:'strict_full',timestamp:'2026-01-01T00:00:00Z',level:{value:60,status:'agreement'}},
  age_seconds:1,stale:false,stale_after_seconds:45,activity:{state:'waiting'},segment:{readings:3,difference_percentage_points:'0.05',span_seconds:{approximate:30}},
  estimates:{exp_per_hour:{value:{approximate:2000},requirement:{version:'test'},hypotheses:{}},percentage_per_hour:{value:{approximate:12}},eta:{seconds:{approximate:900}}},...changes};}

for(const view of ['player','overlay'])test(`${view} shows manual partial values with provenance and no invented percentage`,()=>{
  const p=page(view),level={value:64,status:'manual_admin',correction_id:7};
  const reading={exp:'0',percentage:null,bp:null,evidence:'manual_admin',timestamp:'2026-01-01T00:00:00Z',level,
    provenance:{level:64,current_exp:0,percentage_bp:null,reason:'<script>literal operator text</script>'}};
  p.render(player({reading,display_level:{value:64,evidence:level,timestamp:reading.timestamp,age_seconds:1}}));
  assert.equal(p.elements.level.textContent,'Lv. 64');
  assert.match(p.elements.exp.textContent,/0/);
  assert.equal(p.elements.percentage.textContent,'—');assert.equal(p.elements.progress.hidden,true);
  assert.match(p.elements.exp.title,/Entered manually/);assert.match(p.elements.level.title,/Level entered manually/);
  p.render(player({reading:{...reading,exp:null,bp:0,percentage:'0.00'}}));
  assert.equal(p.elements.percentage.textContent,'0.00%');assert.equal(p.elements.progress.hidden,false);
  assert.equal(p.elements.progress.value,0);
});

test('homepage renders an operator correction with ordinary numeric labels',()=>{
  const p=page('board'),level={value:64,status:'manual_admin',correction_id:8};
  p.context.fixture=player({reading:{exp:'123456',percentage:'50.00',bp:5000,evidence:'manual_admin',
    timestamp:'2026-01-01T00:00:00Z',level,provenance:{level:64,current_exp:123456,percentage_bp:5000}}});
  const entry=p.run('entry({player:fixture,rank:1,value:64})');
  assert.ok(entry);assert.equal(p.run('levelText(fixture)'),'64');
  assert.match(p.run('expTitle(fixture.reading)'),/Entered manually by the tracker operator/);
});

for(const view of ['player','overlay'])test(`${view} marks estimated percentage and preserves inconsistent manual coordinates`,()=>{
  const p=page(view),level={value:64,status:'manual_admin',correction_id:9};
  const reading={exp:'749000',percentage:'50.00',bp:5000,evidence:'manual_admin',timestamp:'2026-01-01T00:00:00Z',level,
    estimated_percentage:{source:'manual_exp_and_community_requirement'},provenance:{kind:'baseline',level:64,current_exp:749000,percentage_bp:null}};
  p.render(player({reading}));assert.equal(p.elements.percentage.textContent,'~50.00%');
  assert.match(p.elements.exp.title,/% is estimated from the entered EXP/);
  p.render(player({reading:{...reading,exp:'1',estimated_percentage:null,exp_validity:{status:'invalid'},
    provenance:{kind:'point',level:64,current_exp:1,percentage_bp:5000}}}));
  assert.equal(p.elements.percentage.textContent,'50.00%');assert.match(p.elements.exp.textContent,/1/);
  assert.match(p.elements.exp.title,/don't fully match/);
});

test('character page tab names the channel before any reading; overlay keeps its own title',()=>{
  assert.equal(page('player').context.document.title,'alpha · EXP Tracker');
  assert.equal(page().context.document.title,undefined);
});

test('a warming server is described as preparing history, not as unavailable',async()=>{
  const p=page('player',()=>Promise.resolve({ok:false,status:503,json:()=>Promise.resolve({error:'warming_up'})}));
  await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(p.elements.status.textContent,'Preparing saved history…');
  const board=page('board',()=>new Promise(()=>{}));board.context.fixture={players:[],warming:['beta']};
  board.run("el('entries').querySelectorAll=()=>[];data=fixture;renderBoard()");assert.match(board.elements['board-count'].textContent,/1 more loading/);
});

for(const view of ['player','overlay'])test(`${view} clears previous identity while replacement publication warms and recovers`,async()=>{
  let respond;
  const p=page(view,()=>new Promise(resolve=>{respond=resolve;}));
  p.render(player({character:{id:1,label:'Old character'}}));
  p.run("el('history-chart').append(node('text',null,'Old history'))");
  respond({ok:false,status:503,json:async()=>({error:'warming_up'})});
  await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(p.elements.status.textContent,'Preparing saved history…');
  assert.equal(p.elements[view==='player'?'player-name':'character'].textContent,'alpha');
  for(const id of ['exp','percentage','rate','eta'])assert.equal(p.elements[id].textContent,'—');
  assert.equal(p.elements.progress.hidden,true);
  assert.equal(p.elements['history-chart'].children.length,0);
  assert.equal(p.run('data'),null);
  p.context.fetch=async()=>({ok:true,status:200,json:async()=>({player:player({character:{id:2,label:'New character'}})})});
  await p.run('poll()');
  assert.equal(p.elements[view==='player'?'player-name':'character'].textContent,'New character');
  assert.equal(p.elements.percentage.textContent,'5.90%');
});

test('ETA rounds once to the nearest minute and retains day, hour and minute detail',()=>{
  const p=page('player');
  for(const [seconds,expected] of [[24*60+31,'~25m'],[3600+22*60+12,'~1h 22m'],[7*3600+43*60+28,'~7h 43m'],
    [2*86400+14*3600+7*60,'~2d 14h 7m'],[0,'~0m'],[12,'~<1m'],[30,'~1m'],[3599,'~1h'],[86399,'~1d']]){
    p.context.duration={seconds:{approximate:seconds}};
    assert.equal(p.run('etaText(duration)'),expected);
  }
  p.context.duration={seconds:{approximate:-1}};assert.equal(p.run('etaText(duration)'),'—');
  assert.equal(p.run('etaText(null)'),'—');
  const overlay=page(),base=player();base.estimates.eta={seconds:{approximate:2*86400+14*3600+7*60}};
  overlay.render(base);assert.equal(overlay.elements.eta.textContent,'~2d 14h 7m');
  overlay.elements.eta.clientWidth=60;overlay.elements.eta.scrollWidth=120;overlay.render(base);
  assert.equal(overlay.elements.eta.textContent,'~2d 14h');assert.match(overlay.elements.eta.title,/~2d 14h 7m/);
});

test('public tracked gains prefer their coherent all-window packet while pace stays separate',()=>{
  const p=page('player'),base=player({tracked_status:'ready',tracked_windows:{'5':{observed:{available:true,
    estimated_exp:{value:{approximate:41228}},readings:97,span_seconds:{approximate:2100},age_seconds:0}}},
    tracked_current_level_windows:{'5':{observed:{available:true,estimated_exp:{value:{approximate:5000}},readings:4,span_seconds:{approximate:60},age_seconds:0}}}});
  p.render(base);assert.equal(p.elements.movement.dataset.fullNumber,'+41,228 EXP');
  p.elements['current-level-only'].listeners.change({target:{checked:true}});
  assert.equal(p.elements.movement.dataset.fullNumber,'+5,000 EXP');
  base.tracked_status='history_limit';base.tracked_windows={};base.tracked_current_level_windows={};
  p.render(base);assert.equal(p.elements.movement.textContent,'—');assert.equal(p.elements['segment-note'].textContent,'History unavailable');
});
test('overlay updates percentage-only without borrowing absolute EXP; recovered values stay marked',()=>{
  const p=page();p.render(player());assert.equal(p.elements.exp.textContent,'71.4K');assert.match(p.elements.exp.title,/71,441/);assert.equal(p.elements.progress.value,5.9);
  p.render(player({reading:{exp:null,percentage:'6.00',bp:600,evidence:'strict_percentage_only',level:{value:60,status:'single_reader'}}}));
  assert.equal(p.elements.exp.textContent,'—');assert.equal(p.elements.progress.value,6);assert.equal(p.elements.level.textContent,'Lv. 60');
  p.render(player({reading:{exp:'71441',percentage:'5.90',bp:590,evidence:'grammar_recovered',level:{value:null,status:'conflict',visual:54,neural:64}}}));
  assert.match(p.elements.exp.textContent,/^~/);assert.equal(p.elements.level.textContent,'Lv. —');assert.equal(p.elements.level.title,'Level unclear');
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
  assert.match(p.run('earlyText(data.player)'),/As of 1m ago/);
  p.run('failed=true;renderPlayer()');assert.equal(p.elements.rate.textContent,'~2K');
  p.run('failed=false');
  const board=page('board');board.context.sample=base;
  assert.equal(board.run('metricValue(sample,"exp_hour")'),null);
  p.context.performance.now=()=>240000;p.run('renderPlayer()');
  assert.equal(p.elements.rate.textContent,'~2K');assert.match(p.run('earlyText(data.player)'),/As of 5m ago/);
  assert.equal(p.elements.eta.textContent,'—');
  p.context.performance.now=()=>1740000;p.run('renderPlayer()');
  assert.equal(p.elements.rate.textContent,'—');assert.match(p.run('earlyText(data.player)'),/^Paused$/);
  p.context.performance.now=()=>0;base.responsive_pace.presentation={state:'historical',can_age:false};
  base.activity={state:'capture_finished'};p.render(base);
  assert.equal(p.elements.rate.textContent,'~2K');assert.equal(p.elements.status.textContent,'Tracking ended');
});

test('official live/offline and unknown status stay separate from capture and expire',()=>{
  const p=page();
  p.render(player({reading:null,latest_attempt_status:'capture_failed',twitch:{status:'live'}}));
  assert.equal(p.elements.status.textContent,"Live on Twitch · Can't read the stream");
  p.render(player({reading:null,latest_attempt_status:'capture_failed',twitch:{status:'offline'}}));
  assert.equal(p.elements.status.textContent,"Offline on Twitch · Can't read the stream");
  p.render(player({reading:null,latest_attempt_status:'capture_failed',twitch:{status:'unknown'}}));
  assert.equal(p.elements.status.textContent,"Can't read the stream");
  p.render(player({twitch:{status:'offline',capture_disagreement:true}}));
  assert.equal(p.elements.status.textContent,'Offline on Twitch · Tracker still updating');
  p.render(player({twitch:{status:'live'},stale:true,age_seconds:60,latest_attempt_status:'malformed_or_unavailable',
    latest_attempt_at:'2026-01-01T00:01:00Z',latest_attempt_age_seconds:1}));
  assert.equal(p.elements.status.textContent,'Live on Twitch · EXP bar not visible');
  p.render(player({reading:null,latest_attempt_status:'capture_failed',twitch:{status:'live',valid_until:'2026-01-01T00:01:00Z'}}));
  p.run('data.served_at="2026-01-01T00:00:00Z"');p.context.performance.now=()=>61000;p.run('renderPlayer()');
  assert.equal(p.elements.status.textContent,"Can't read the stream");
});
const livePace=rate=>({pace:{active:true,age_seconds:0,estimates:{exp_per_hour:{value:{approximate:rate}},percentage_per_hour:null,eta:null}}});
test('unavailable rates are not ranked as zero and equal live paces share rank',()=>{
  const p=page('board');
  p.context.fixtures=[player({channel:'b',recent_windows:{5:livePace(2000)}}),player({channel:'a',recent_windows:{5:livePace(2000)}}),player({channel:'c',recent_windows:{5:{}}})];
  const rows=JSON.parse(p.run('JSON.stringify(ranked(fixtures,"exp_hour").map(r=>({channel:r.player.channel,value:r.value,rank:r.rank})))'));
  assert.deepEqual(rows.map(r=>r.rank),[1,1,null]);assert.deepEqual(rows.map(r=>r.channel),['a','b','c']);
  p.render(player({activity:{state:'coordinator_stopped'}}));assert.equal(p.elements.status.textContent,'Tracking paused');
  assert.ok(!source.includes('innerHTML'));
});

test('window buttons use only eligible window metrics; overlay keeps its existing segment estimates',()=>{
  const p=page('player'),base=player();
  base.windows={5:{eligible:true,estimates:base.estimates,difference_percentage_points:'0.20',readings:21,coverage_seconds:{approximate:300}},
    10:{eligible:false,state:'building_history',estimates:{}}};
  p.render(base);assert.equal(p.elements.movement.textContent,'+0.20%');assert.equal(p.elements.rate.textContent,'~2,000');
  p.buttons[1].listeners.click();assert.equal(p.elements.movement.textContent,'—');assert.equal(p.elements.rate.textContent,'—');
  assert.match(p.elements['segment-note'].textContent,/Calculating…/);
  assert.equal(p.buttons[1].attributes['aria-pressed'],'true');
  const overlay=page();overlay.render({...base,windows:{}});assert.equal(overlay.elements.rate.textContent,'~2K');
  p.context.fixtures=[base,{...base,channel:'b',windows:{}}];
  assert.deepEqual(JSON.parse(p.run('JSON.stringify(ranked(fixtures,"movement").map(r=>r.rank))')),[null,null]);
});

test('recent graph has a fixed selected time axis, all supported levels and retained gaps',()=>{
  const p=page('player');p.render(player());
  const point=(timestamp,bp=100)=>({event_id:timestamp,timestamp,interval_seconds:15,level:{value:64},reading:{bp,percentage:(bp/100).toFixed(2),evidence:'strict_percentage_only'}});
  p.context.points=[point('2026-01-01T00:00:00Z'),point('2026-01-01T00:06:00Z'),point('2026-01-01T00:06:15Z',101)];
  p.run('chartMode="percentage";data.history=points;drawHistory()');
  assert.equal(p.elements['history-chart'].dataset.start,'2026-01-01T00:01:15.000Z');
  assert.match(p.elements['history-note'].textContent,/^Last 5 min · times in \S+/);
  // The stat-card window no longer moves the chart; the chart's own window does.
  p.buttons[1].listeners.click();assert.equal(p.elements['history-chart'].dataset.start,'2026-01-01T00:01:15.000Z');
  p.run('lineWindow=10;drawHistory()');assert.equal(p.elements['history-chart'].dataset.start,'2025-12-31T23:56:15.000Z');
  assert.ok(!p.elements['history-chart'].children.some(n=>n.attributes.class==='gap'));
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
  assert.equal(p.elements['early-value'].textContent,'Recent pace');
  assert.doesNotMatch(p.elements.rate.title,/readings|sampled/);
  assert.doesNotMatch(p.elements['early-value'].textContent,/240s/);
  base.responsive_pace.tentative=true;base.responsive_pace.readings=2;base.responsive_pace.interruptions=0;
  base.responsive_pace.coverage_seconds.approximate=15;
  p.render(base);assert.match(p.elements['early-value'].textContent,/^Early estimate$/);
});

test('percentage chart counts numerical points separately from missing and unknown-level attempts',()=>{
  const p=page('player');p.render(player());
  p.context.points=[
    {event_id:'a',timestamp:'2026-01-01T00:00:00Z',level:{value:60},reading:{bp:590,percentage:'5.90',evidence:'strict_full'}},
    {event_id:'b',timestamp:'2026-01-01T00:00:15Z',level:{value:null},reading:null},
    {event_id:'c',timestamp:'2026-01-01T00:00:30Z',level:{value:null},reading:{bp:591,percentage:'5.91',evidence:'strict_full'}},
    {event_id:'d',timestamp:'2026-01-01T00:00:45Z',level:{value:60},reading:{bp:592,percentage:'5.92',evidence:'strict_full'}}];
  p.run('chartMode="percentage";data.history=points;drawHistory()');
  assert.match(p.elements['history-note'].textContent,/Last 5 min.*couldn't read EXP/);
  const shapes=p.elements['history-chart'].children;
  assert.equal(shapes.filter(n=>n.tag==='circle').length,2);
  assert.equal(shapes.filter(n=>n.tag==='path').length,2);
  assert.equal(shapes.filter(n=>n.attributes.class==='trend').length,1);  // a joins d; b and c stay off the line
  assert.equal(shapes.filter(n=>n.attributes.class==='chart-grid').length,4);
});

test('endpoint pace discloses elapsed gaps and conditional recovery is never strict OCR',()=>{
  const p=page('player'),base=player();
  base.responsive_pace={active:true,tentative:false,age_seconds:1,start:'2026-01-01T00:00:00Z',end:'2026-01-01T00:02:20Z',
    readings:6,span_seconds:{approximate:140},coverage_seconds:{approximate:140},interruptions:0,missing_attempts:2,
    interval_counts:{direct:3,endpoint_supported:2},estimates:base.estimates};
  base.reading={...base.reading,evidence:'conditional_symbol',grammar_policy:'conditional_percent_v1'};
  p.render(base);
  assert.equal(p.elements['early-value'].textContent,'Recent pace');
  assert.ok(!p.elements['early-value'].title);
  assert.match(p.elements.rate.title,/Estimated from recent stream updates/);
    assert.ok(!p.elements['segment-note'].title);
  assert.match(p.elements.exp.textContent,/^~/);
  assert.match(p.elements.exp.title,/partly unclear on stream/);
  // A live pace is ranked as shown, even with gaps; only the displayed estimate is used.
  assert.equal(p.run('metricValue(data.player,"exp_hour")'),2000);
});

test('pace ranking changes with the selected window and never substitutes a short segment rate',()=>{
  const p=page('board');
  p.context.fixtures=[player({channel:'a',recent_windows:{5:livePace(100),30:livePace(300)}}),player({channel:'b',recent_windows:{5:livePace(200),30:{}}})];
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
    assert.match(p.elements['segment-note'].textContent,/^Based on 3m 28s tracked$/);
    assert.equal(p.elements['window-rate'].textContent,`Needs a full ${p.buttons[i].dataset.window} min`);
    assert.equal(p.elements.rate.textContent,'~2,000');
  }
  p.context.fixtures=[base];assert.deepEqual(JSON.parse(p.run('JSON.stringify(ranked(fixtures,"day").map(r=>r.rank))')),[null]);
  p.render({...base,stale:true});
  assert.equal(p.elements.movement.textContent,'+3.55%');assert.equal(p.elements.movement.dataset.paused,'true');
  assert.match(p.elements['segment-note'].textContent,/last updated/);
  assert.match(p.elements['segment-note'].textContent,/^Based on 3m 28s tracked/);
  assert.equal(p.elements['window-rate'].textContent,'Paused');
  p.run('failed=true;renderPlayer()');assert.match(p.elements['segment-note'].textContent,/last updated/);
});

test('withheld full EXP retains percentage and provisional level across product views',()=>{
  const p=page();p.render(player({reading:{exp:null,percentage:'45.09',bp:4509,evidence:'strict_full',
    exp_validity:{status:'invalid'},level:{value:65,status:'provisional_neural',visual:63,neural:65}}}));
  assert.equal(p.elements.exp.textContent,'—');assert.equal(p.elements.progress.value,45.09);
  assert.match(p.elements.exp.title,/EXP hidden/);assert.equal(p.elements.level.textContent,'Lv. 65');
});

test('percentage-derived EXP is explicitly approximate and leaves direct OCR integer display intact',()=>{
  const p=page(),r={exp:null,percentage:'67.72',bp:6772,evidence:'strict_percentage_only',level:{value:65,status:'provisional_neural'},
    estimated_exp:{value:{approximate:1069917.0836},level_evidence:{value:65},requirement:{version:'synthetic'},
      hypotheses:{nearest_half_up:{min:1069839,max:1069996,count:158},truncate:{min:1069918,max:1070075,count:158}}}};
  p.render(player({reading:r}));assert.equal(p.elements.exp.textContent,'~1.07M');assert.match(p.elements.exp.title,/Estimated from the level %/);
  p.render(player({reading:{...r,exp:'1069917',estimated_exp:null,evidence:'strict_full'}}));
  assert.equal(p.elements.exp.textContent,'1.07M');assert.match(p.elements.exp.title,/^1,070,000 EXP$|^[\d,]+ EXP$/);
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
    [{state:'stopped',completion:'completed'},'Tracking ended'],[{state:'stopped',completion:'interrupted'},'Tracking stopped']]){
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
    assert.equal(p.elements.level.textContent,'Lv. 65');assert.match(p.elements.level.title,/Last known level · read 40s ago/);
    assert.equal(p.elements.exp.textContent,'—');assert.equal(p.elements.rate.textContent,'—');
    if(view==='player')assert.equal(p.elements['level-note'],undefined);
  }
});

test('early segment pace is visible before a complete window and becomes paused on stale or failed API',()=>{
  const p=page('player'),base=player();
  base.early_pace={active:true,segment:{...base.segment,start:'start',end:'end'},estimates:base.estimates};
  p.render(base);assert.match(p.elements['early-value'].textContent,/^~2K EXP\/hour · Early estimate$/);
  assert.equal(p.elements.rate.textContent,'—');assert.match(p.elements['segment-note'].textContent,/^Calculating…$/);
  p.context.performance.now=()=>50000;p.run('renderPlayer()');assert.equal(p.elements['early-value'].textContent,'Paused');
  assert.equal(p.elements['early-value'].textContent,'Paused');
  p.context.performance.now=()=>0;p.run('failed=true;renderPlayer()');assert.equal(p.elements['early-value'].textContent,'Paused');
});

test('responsive pace has one current rate, retains an explicitly aged rate after gaps, and never ranks it',()=>{
  const p=page('player'),base=player();
  base.responsive_pace={active:true,tentative:true,age_seconds:0,readings:2,span_seconds:{approximate:15},estimates:{...base.estimates,eta:null}};
  p.render(base);assert.equal(p.elements.rate.textContent,'~2,000');assert.match(p.elements['early-value'].textContent,/^Early estimate$/);
  assert.equal(p.elements['window-rate'].textContent,'Calculating…');
  p.render({...base,responsive_pace:{...base.responsive_pace,active:false,age_seconds:35}});
  assert.equal(p.elements.rate.textContent,'~2,000');assert.match(p.elements['early-value'].textContent,/As of 35s ago/);
  assert.equal(p.elements.rate.dataset.paused,'true');assert.equal(p.elements['eta-stat'].hidden,false);
  p.context.fixtures=[{...base,responsive_pace:{...base.responsive_pace,active:false,age_seconds:35}}];
  assert.deepEqual(JSON.parse(p.run('JSON.stringify(ranked(fixtures,"exp_hour").map(r=>r.rank))')),[null]);
});

test('selected SQLite window controls gain, rate and tentative ETA while four cards stay present',()=>{
  const p=page('player'),base=player();
  base.responsive_pace={active:true,age_seconds:0,readings:2,span_seconds:{approximate:20},estimates:base.estimates};
  base.recent_windows=Object.fromEntries([5,10,15,30,60].map((minutes,i)=>[minutes,{status:'ready',available:true,
    eta:{estimate:base.estimates.eta,window_minutes:minutes,estimated_at:base.reading.timestamp,age_seconds:0,readings:2,tentative:i===0,historical:false},
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
    assert.equal(p.elements['window-rate'].textContent,`Needs a full ${p.buttons[i].dataset.window} min`);
  }
  p.buttons[0].listeners.click();assert.match(p.elements['eta-note'].textContent,/^Early estimate$/);
  base.recent_windows[5].pace.active=false;p.render(base);
  assert.equal(p.elements.eta.textContent,'~15m');assert.equal(p.elements['eta-stat'].hidden,false);
  assert.match(p.elements['eta-note'].textContent,/^Estimated .* ago/);
  assert.equal(p.elements['level-note'],undefined);
  base.recent_windows[5]={status:'history_limit',available:false,observed:{available:false}};
  base.windows={5:{eligible:true,estimates:base.estimates,coverage_seconds:{approximate:300},readings:21}};
  p.render(base);assert.equal(p.elements.rate.textContent,'—');assert.equal(p.elements.movement.textContent,'—');
  assert.equal(p.elements['segment-note'].textContent,'History unavailable');
});

test('selected historical rate is dated, has no current gain or ETA, and never falls back to a different window',()=>{
  const p=page('player'),base=player();
  base.responsive_pace={active:true,age_seconds:0,level:60,readings:2,span_seconds:{approximate:20},estimates:base.estimates};
  base.recent_windows={60:{status:'ready',available:false,observed:{available:false},last_observed_pace:{
    ...base.responsive_pace,active:false,age_seconds:400,estimates:{...base.estimates,exp_per_hour:{...base.estimates.exp_per_hour,value:{approximate:6000}}}}}};
  p.render(base);p.buttons[4].listeners.click();
  assert.equal(p.elements.rate.textContent,'~6,000');assert.equal(p.elements.movement.textContent,'—');
  assert.match(p.elements['early-value'].textContent,/As of 6m ago/);
  assert.equal(p.elements.eta.textContent,'—');assert.equal(p.elements['eta-stat'].hidden,false);
  delete base.recent_windows[60].last_observed_pace;p.render(base);
  assert.equal(p.elements.rate.textContent,'—');
});

test('character ETA is a dated static duration through failed polls, missing OCR and expired windows',()=>{
  const p=page('player'),base=player();
  base.recent_windows=Object.fromEntries([5,10,15,30,60].map(minutes=>[minutes,{status:'ready',available:false,observed:{available:false},
    eta:{estimate:{seconds:{approximate:minutes*600}},window_minutes:minutes,estimated_at:base.reading.timestamp,
      age_seconds:4000,readings:4,tentative:false,historical:true,static_duration:true}}]));
  base.stale=true;base.activity={state:'capture_finished'};base.latest_attempt_status='capture_failed';
  for(let i=0;i<p.buttons.length;i++){
    p.render(base);p.buttons[i].listeners.click();
    const text=p.elements.eta.textContent;
    assert.notEqual(text,'—');assert.equal(p.elements['eta-stat'].hidden,false);
    assert.match(p.elements['eta-note'].textContent,new RegExp(`^Estimated .* ago · ${p.buttons[i].dataset.window} min pace$`));
    p.run('failed=true;renderPlayer()');assert.equal(p.elements.eta.textContent,text);
    p.context.performance.now=()=>3600000;p.run('renderPlayer()');assert.equal(p.elements.eta.textContent,text);
    assert.equal(p.elements.movement.textContent,'—');
    p.run('failed=false');
  }
  // A new valid server estimate replaces the historical duration without reload.
  base.stale=false;base.recent_windows[60].eta.historical=false;base.recent_windows[60].eta.age_seconds=0;
  base.recent_windows[60].eta.estimate.seconds.approximate=900;p.context.performance.now=()=>0;p.render(base);
  assert.equal(p.elements.eta.textContent,'~15m');
  delete base.recent_windows[60].eta;p.render(base);assert.equal(p.elements.eta.textContent,'—');
});

test('all-level chart marks resets and current-only filtering retains the fixed time axis',()=>{
  const p=page('player'),base=player({display_level:{evidence:{value:66},value:66,age_seconds:0},level_events:[{level:66,timestamp:'2026-01-01T00:00:15Z',first_observed_at:'2026-01-01T00:00:15Z'}]});
  p.render(base);
  const point=(seconds,level,bp,connect_previous=false)=>({timestamp:new Date(Date.UTC(2026,0,1,0,0,seconds)).toISOString(),level:{value:level},interval_seconds:15,connect_previous,reading:bp==null?null:{bp,percentage:(bp/100).toFixed(2),evidence:'strict_full'}});
  p.context.points=[point(0,65,9997),point(15,66,1),point(30,66,3,true),point(45,66,null),point(60,66,8),point(75,66,12,true)];
  p.run('chartMode="percentage";data.history=points;drawHistory()');
  const shapes=p.elements['history-chart'].children;
  assert.equal(shapes.filter(n=>n.attributes.class==='trend').length,4);
  assert.ok(!shapes.some(n=>n.tag==='text' && n.textContent==='99.97%'));
  assert.equal(p.elements['level-event'].textContent,'Level 66 reached!');
  assert.equal(p.elements['history-chart'].dataset.start,'2025-12-31T23:56:15.000Z');
  assert.equal(shapes.filter(n=>n.tag==='circle').length,5);
  assert.equal(shapes.filter(n=>n.attributes.class==='level-transition').length,1);
  p.elements['current-level-only'].listeners.change({target:{checked:true}});
  assert.equal(p.elements['history-chart'].dataset.start,'2025-12-31T23:56:15.000Z');
  assert.equal(p.elements['history-chart'].children.filter(n=>n.tag==='circle').length,4);
  assert.match(p.elements['history-note'].textContent,/Lv. 66/);
});

test('mixed-level EXP-only summaries remain visible and the filter selects its own cards',()=>{
  const p=page('player'),base=player();
  const metric=gain=>({status:'ready',observed:{available:true,start:'2026-01-01T00:00:00Z',end:'2026-01-01T00:01:00Z',
    difference_percentage_points:null,estimated_exp:{value:{approximate:gain}},coverage_seconds:{approximate:40},
    span_seconds:{approximate:60},readings:4,age_seconds:0},eta:{estimate:{seconds:{approximate:600}},age_seconds:0,window_minutes:5}});
  base.recent_windows={'5':metric(763)};base.current_level_windows={'5':metric(575)};
  base.recent_windows['5'].pace={active:true,level:61,readings:4,age_seconds:0,span_seconds:{approximate:60},
    estimates:{exp_per_hour:{value:{approximate:763*3600/60},requirement:{version:'test'},hypotheses:null},percentage_per_hour:null}};
  p.render(base);
  assert.equal(p.elements.movement.textContent,'+763 EXP');assert.doesNotMatch(p.elements.movement.title,/null/);
  assert.equal(p.elements.rate.textContent,'~45,780');
  assert.equal(p.elements.eta.textContent,'~10m');
  p.elements['current-level-only'].listeners.change({target:{checked:true}});
  assert.equal(p.elements.movement.textContent,'+575 EXP');
  p.elements['current-level-only'].listeners.change({target:{checked:false}});
  assert.equal(p.elements.movement.textContent,'+763 EXP');
  assert.equal(p.elements['eta-stat'].hidden,false);
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

test('bar lookbacks exclude a whole boundary-crossing interval just like tracked cards',()=>{
  const p=page('player'),anchor=Date.parse('2026-01-01T00:10:00Z');p.context.anchor=anchor;
  p.context.rows=[{connect_previous:true,gain:{start:new Date(anchor-310000).toISOString(),end:new Date(anchor-290000).toISOString(),value:{approximate:100}}},
    {connect_previous:true,gain:{start:new Date(anchor-290000).toISOString(),end:new Date(anchor-260000).toISOString(),value:{approximate:20},kind:'endpoint_supported'}}];
  assert.equal(p.run('bucketHistory(rows,anchor,60,300).bins.reduce((s,b)=>s+(b.value??0),0)'),20);
  assert.equal(p.run('bucketHistory(rows,anchor,60,600).bins.reduce((s,b)=>s+(b.value??0),0)'),120);
  assert.ok(p.run('bucketHistory(rows,anchor,60,300).bins.filter(b=>b.value!=null).every(b=>b.state==="partial")'));
});

test('public endpoint bars record net changes at receipt without spreading capture gaps',()=>{
  const p=page('player'),base=Date.parse('2026-01-01T00:00:00Z');p.context.anchor=base+300e3;
  const interval=(a,b,value)=>({connect_previous:true,gain:{policy:'public_endpoint_window_v1',
    start:new Date(base+a*1000).toISOString(),end:new Date(base+b*1000).toISOString(),value:{approximate:value}}});
  p.context.rows=[interval(0,180,5000),interval(180,240,-1000)];
  const chart=JSON.parse(p.run('JSON.stringify(bucketHistory(rows,anchor,60,300))'));
  assert.deepEqual(chart.bins.map(b=>b.value),[null,null,null,5000,-1000]);
  assert.equal(chart.bins.reduce((sum,b)=>sum+(b.value??0),0),4000);
});

test('rolling interval bars include qualifying boundary crossings only at real later endpoints',()=>{
  const p=page('player'),anchor=Date.parse('2026-01-01T00:10:00Z');p.context.anchor=anchor;
  const interval=(a,b,value)=>({connect_previous:true,gain:{policy:'public_endpoint_window_v2',
    start:new Date(anchor+a*1000).toISOString(),end:new Date(anchor+b*1000).toISOString(),value:{approximate:value}}});
  p.context.rows=[interval(-310,-290,100),interval(-290,0,20)];
  const bins=JSON.parse(p.run('JSON.stringify(bucketHistory(rows,anchor,60,300).bins)'));
  assert.deepEqual(bins.map(b=>b.value),[100,null,null,null,20]);
  p.context.rows=[interval(-301,0,100),interval(-60,0,-5)];
  assert.equal(p.run('bucketHistory(rows,anchor,60,300).bins.reduce((s,b)=>s+(b.value??0),0)'),0);
});

test('missing level requirement is an explicit public window limitation',()=>{
  const p=page('player'),base=player({recent_windows:{5:{available:false,gain:null,
    reason:'level_transition_requirement_unavailable'}}});
  p.render(base);assert.match(p.elements['segment-note'].textContent,/^Can't total EXP across the level-up$/);
  assert.match(p.elements.movement.title,/^Can't total EXP across the level-up$/);
});

test('EXP history has fixed axes and the 24h view waits for aggregated history',()=>{
  const p=page('player');p.render(player());
  p.context.rows=[{connect_previous:true,gain:{start:'2026-01-01T00:00:00Z',end:'2026-01-01T00:00:15Z',value:{approximate:100}}}];
  p.run('data.history=rows;data.player.latest_attempt_at="2026-01-01T00:00:15Z";drawHistory()');
  assert.equal(p.elements['history-chart'].children.filter(n=>n.attributes.class==='exp-column missing').length,4);
  assert.equal(p.elements['history-chart'].children.filter(n=>n.attributes.class==='exp-column').length,1);
  p.run('data.served_at="2026-01-01T00:00:15Z"');
  for(const [bucket,seconds] of [[60,300],[300,300],[1800,86400]]){
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
  assert.ok(!p.elements['history-chart'].children.some(n=>n.attributes.class==='exp-column'));
});

test('public progress uses EXP with percentage fallback and exact provenance in the tooltip',()=>{
  const p=page('player'),base=player({windows:{5:{eligible:false,observed:{available:true,
    difference_percentage_points:'0.14',estimated_exp:{value:{approximate:2329.7904},requirement:{version:'synthetic'}},
    span_seconds:{approximate:45},readings:4,interruptions:0,age_seconds:1}}}});
  p.render(base);assert.equal(p.elements.movement.textContent,'+2,330 EXP');assert.match(p.elements.movement.title,/^\+2,330 EXP \(\+0\.14% of level\) gained between the first and last update/);
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
  p.render(player({stale:true,activity:{state:'capture_finished'}}));assert.equal(p.elements.status.textContent,'Tracking ended');
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

test('public inferred levels omit question marks and preserve hover provenance',()=>{
  const p=page('player'),level=(status,value)=>({display_level:{evidence:{value,status,reason:status},value,timestamp:'2026-01-01T00:00:00Z',age_seconds:0},
    level_context:{last_supported_level:42,source:'exp_derived',supported_at:'2026-01-01T00:00:00Z'}});
  p.render(player(level('exp_derived',42)));
  assert.equal(p.elements.level.textContent,'Lv. 42');assert.equal(p.elements.level.dataset.inferred,'true');
  assert.match(p.elements.level.title,/Level worked out from EXP/);
  p.render(player(level('retained_level',42)));
  assert.equal(p.elements.level.title,'Last confirmed level.');
  const possible=level('retained_level',42);possible.level_context.transition={phase:'possible',from_level:42,to_level:43,before_bp:9992,after_bp:18,detected_at:'2026-01-01T00:01:30Z'};
  p.render(player(possible));
  assert.equal(p.elements.level.textContent,'Lv. 42');assert.match(p.elements.level.title,/^Possible level-up to Lv\. 43; waiting for confirmation\.$/);
  p.render(player(level('provisional_level_up',43)));
  assert.equal(p.elements.level.textContent,'Lv. 43');assert.match(p.elements.level.title,/Likely level-up/);
  p.render(player(level('agreement',42)));
  assert.equal(p.elements.level.textContent,'Lv. 42');assert.equal(p.elements.level.dataset.inferred,'false');
});

test('homepage, character and overlay show supported levels through every transition phase',()=>{
  for(const phase of ['possible','provisional','corroborated'])for(const view of ['board','player','overlay']){
    const fixture=player({display_level:{value:phase==='possible'?42:43,age_seconds:0,
      evidence:{value:phase==='possible'?42:43,status:phase==='possible'?'retained_level':phase==='provisional'?'provisional_level_up':'exp_derived'}},
      level_context:{transition:phase==='corroborated'?null:{phase,from_level:42,to_level:43,before_bp:9992,after_bp:18,detected_at:'2026-01-01T00:01:30Z'}}});
    const p=page(view);p.context.sample=fixture;
    const expected=phase==='possible'?42:43;
    if(view==='board'){
      assert.equal(p.run('metricValue(sample,"level")'),expected);
      assert.equal(p.run('entry({player:sample,value:metricValue(sample,"level"),rank:1}).children[1].children[1].textContent'),String(expected));
    }else{
      p.render(fixture);assert.equal(p.elements.level.textContent,`Lv. ${expected}`);
      assert.match(p.elements.level.title,phase==='possible'?/Possible level-up/:phase==='provisional'?/Likely level-up/:/Level worked out from EXP/);
    }
    assert.equal(fixture.display_level.value,phase==='possible'?42:43);
  }
});

test('suspected wrap and unreadable HUD keep level 43 with its 99.97 percent bar until accepted evidence',()=>{
  const stamp='2026-01-01T00:00:00Z',old={exp:'391048',percentage:'99.97',bp:9997,evidence:'strict_full',timestamp:stamp,level:{value:43,status:'exp_derived'}},
    saved={value:43,age_seconds:45,timestamp:stamp,last_known:true,evidence:old.level},
    transition={phase:'possible',from_level:43,to_level:44,before_bp:9997,after_bp:3,detected_at:'2026-01-01T00:00:15Z'};
  for(const view of ['board','player','overlay']){
    const p=page(view),pending=player({reading:old,display_level:saved,stale:true,level_events:[],
      latest_attempt_status:'unavailable',latest_attempt_at:'2026-01-01T00:00:45Z',latest_attempt_age_seconds:0,
      level_context:{last_supported_level:43,transition}}),original=JSON.stringify(pending);
    p.context.sample=pending;
    if(view==='board'){
      assert.equal(p.run('metricValue(sample,"level")'),43);
      assert.equal(p.run('entry({player:sample,value:43,rank:1}).children[1].children[1].textContent'),'43');
      assert.match(p.run('statusText(sample)'),/Possible level-up \(confirming\)$/);
    }else{
      p.render(pending);assert.equal(p.elements.level.textContent,'Lv. 43');
      assert.equal(p.elements.progress.value,99.97);assert.equal(p.elements.percentage.textContent,'99.97%');
      assert.match(p.elements.status.textContent,/Possible level-up \(confirming\)$/);
      assert.match(p.elements.level.title,/^Possible level-up to Lv\. 44; waiting for confirmation\.$/);
      if(view==='player'){
        p.context.points=[{event_id:'old',timestamp:stamp,level:old.level,reading:old,interval_seconds:15},
          {event_id:'wrap',timestamp:transition.detected_at,level:{value:null,status:'possible_level_up'},reading:null,interval_seconds:15}];
        p.run('data.history=points;chartMode="percentage";currentLevelOnly=true;drawHistory()');
        assert.match(p.elements['history-note'].textContent,/Lv. 43/);
        assert.equal(p.elements['level-event'].hidden,true);
        assert.ok(!p.elements['history-chart'].children.some(n=>/44/.test(n.textContent ?? '')));
      }
      for(const accepted of [true,false]){
        const level=accepted?44:43,reading={...old,exp:accepted?'5000':'391100',percentage:accepted?'1.17':'99.98',bp:accepted?117:9998,level:{value:level,status:'exp_derived'}};
        p.render(player({reading,display_level:{...saved,value:level,evidence:reading.level},
          level_context:{last_supported_level:level,transition:null,last_transition:{...transition,phase:accepted?'corroborated':'abandoned'}}}));
        assert.equal(p.elements.level.textContent,`Lv. ${level}`);assert.equal(p.elements.progress.value,reading.bp/100);
        assert.doesNotMatch(p.elements.status.textContent,/Possible level-up/);
      }
    }
    assert.equal(JSON.stringify(pending),original); // Rendering preserves the pending evidence.
  }
});

test('a possible transition without a supported level keeps the unknown display',()=>{
  const p=page('player');p.render(player({reading:null,display_level:null,
    level_context:{transition:{phase:'possible',from_level:43,to_level:44}}}));
  assert.equal(p.elements.level.textContent,'Lv. —');assert.equal(p.elements.progress.hidden,true);
  assert.equal(p.run('metricValue(data.player,"level")'),null);
});

test('inferred level-up banner and chart marker stay provisional until corroborated',()=>{
  const event=status=>({kind:'inferred_level_up',inferred:true,status,level:43,previous_level:42,evidence:status==='corroborated'?'unique_exp_pair':'percentage_wrap_and_forward_progress',
    timestamp:'2026-01-01T00:00:15Z',first_observed_at:'2026-01-01T00:00:15Z'});
  const point=(seconds,level,bp)=>({timestamp:new Date(Date.UTC(2026,0,1,0,0,seconds)).toISOString(),level:{value:level},interval_seconds:15,connect_previous:false,reading:{bp,percentage:(bp/100).toFixed(2),evidence:'strict_percentage_only'}});
  for(const [status,banner,marker] of [['provisional','Level 43 reached','Lv. 43'],['corroborated','Level 43 reached','Level 43!']]){
    const p=page('player');p.render(player({display_level:{evidence:{value:43,status:'provisional_level_up'},value:43,age_seconds:0},level_events:[event(status)]}));
    p.context.points=[point(0,42,9992),point(15,43,116)];
    p.run('chartMode="percentage";data.history=points;drawHistory()');
    assert.equal(p.elements['level-event'].textContent,banner);
    assert.match(p.elements['level-event'].title,/^Up from Lv\. 42, spotted when the EXP bar reset/);
    assert.ok(p.elements['history-chart'].children.some(n=>n.tag==='text' && n.textContent===marker));
  }
});

// Same-origin (Python server) and a configured API origin (Pages export) poll identically.
for(const view of ['player','overlay'])for(const api of [null,'https://api.example.org'])test(`${view} ${api?'with an API origin ':''}polls name held history revisions, reuse unchanged sections and refetch in full after warming`,async()=>{
  const base=api ?? '';
  const requests=[],settle=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
  const rows=label=>[{event_id:label,timestamp:'2026-01-01T00:00:00Z'}],tracked=label=>({as_of:'2026-01-01T00:00:00Z',label});
  const body=(changes={})=>({player:player(),history_revision:'a'.repeat(16),tracked_revision:'b'.repeat(16),...changes});
  let reply=body({history:rows('first'),tracked_history:tracked('first')});
  const p=page(view,url=>{requests.push(url);return reply instanceof Error?Promise.reject(reply):Promise.resolve({ok:reply.status!==503,status:reply.status??200,json:async()=>reply});},'',api);
  await settle();
  assert.equal(requests[0],`${base}/api/players/alpha`);  // First load: nothing held, full body.
  const first=p.run('data.history');
  reply=body({player:player({reading:{...player().reading,percentage:'6.00',bp:600}})});  // Both sections unchanged and omitted.
  await p.run('poll()');
  assert.equal(requests.at(-1),`${base}/api/players/alpha?history=${'a'.repeat(16)}&tracked=${'b'.repeat(16)}`);
  assert.equal(p.run('data.history'),first);assert.equal(p.run('data.tracked_history.label'),'first');
  assert.equal(p.elements.percentage.textContent,'6.00%');  // Live values still update.
  reply=body({history_revision:'c'.repeat(16),history:rows('second')});  // History changed, tracked unchanged.
  await p.run('poll()');
  assert.equal(p.run('data.history[0].event_id'),'second');assert.equal(p.run('data.tracked_history.label'),'first');
  reply=new Error('offline');await p.run('poll()');assert.equal(p.run('failed'),true);
  reply=body({history_revision:'c'.repeat(16)});await p.run('poll()');  // Reconnect keeps the held revisions.
  assert.equal(requests.at(-1),`${base}/api/players/alpha?history=${'c'.repeat(16)}&tracked=${'b'.repeat(16)}`);
  assert.equal(p.run('failed'),false);assert.equal(p.run('data.history[0].event_id'),'second');
  reply={status:503,error:'warming_up'};await p.run('poll()');assert.equal(p.run('data'),null);  // Character change.
  reply=body({player:player({character:{id:2,label:'New character'}}),history_revision:'d'.repeat(16),tracked_revision:'e'.repeat(16),history:rows('new'),tracked_history:tracked('new')});
  await p.run('poll()');
  assert.equal(requests.at(-1),`${base}/api/players/alpha`);assert.equal(p.run('data.history[0].event_id'),'new');assert.equal(p.run('data.tracked_history.label'),'new');
  reply=body({history_revision:'f'.repeat(16),tracked_revision:'e'.repeat(16)});await p.run('poll()');  // Omitted but not the held revision: never reused.
  assert.equal(p.run('data.history'),undefined);
  reply=body({history_revision:'f'.repeat(16),tracked_revision:'e'.repeat(16),history:rows('healed'),tracked_history:tracked('new')});await p.run('poll()');
  assert.equal(requests.at(-1),`${base}/api/players/alpha`);assert.equal(p.run('data.history[0].event_id'),'healed');
});

test('homepage polls never name history revisions',async()=>{
  const requests=[];let open;const gate=new Promise(resolve=>{open=resolve;});
  const p=page('board',url=>{requests.push(url);return gate.then(()=>({ok:true,status:200,json:async()=>({players:[player()]})}));});
  p.run("el('entries').querySelectorAll=()=>[]");open();
  for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));
  await p.run('poll()');
  assert.deepEqual(requests,['/api/players','/api/players']);assert.equal(p.run('data.players.length'),1);assert.equal(p.run('failed'),false);
});

test('homepage ranks and renders the same without character-only current-level windows',()=>{
  const window=(gain,eligible)=>({available:true,gain:{approximate:gain},eligible,estimates:player().estimates,difference_percentage_points:'0.20',
    readings:10,coverage_seconds:{approximate:300},span_seconds:{approximate:300}});
  // Current-level values differ deliberately: any homepage read of them would change the output.
  const observed=gain=>({available:true,age_seconds:1,readings:10,coverage_seconds:{approximate:300},span_seconds:{approximate:300},estimated_exp:{value:{approximate:gain}}});
  const full=[['a',900,64],['b',300,65],['c',600,64]].map(([channel,gain,level])=>player({channel,reading:{...player().reading,level:{value:level,status:'agreement'}},
    tracked_status:'ready',windows:{5:window(gain,true),60:window(gain*2,true)},recent_windows:{5:window(gain,true),60:window(gain*2,true)},
    tracked_windows:{5:{observed:observed(gain)},60:{observed:observed(gain*2)}},
    current_level_windows:{5:{...window(10000-gain,true),reason:'observed_exp_decrease'},60:window(1,false)},
    tracked_current_level_windows:{5:{observed:observed(7)},60:{observed:observed(8)}}}));
  const shown=full.map(({current_level_windows,tracked_current_level_windows,...rest})=>rest);
  const board=fixtures=>{
    const p=page('board');p.run("el('entries').querySelectorAll=()=>[]");p.context.fixtures=fixtures;const results=[];
    for(const minutes of [5,60])for(const sort of ['exp_hour','level','movement']){
      p.run(`windowMinutes=${minutes};sort='${sort}';data={players:fixtures};renderBoard()`);
      results.push(p.run(`JSON.stringify([ranked(fixtures,'${sort}').map(r=>[r.player.channel,r.value,r.rank]),el('entries').children])`));
    }
    return results;
  };
  assert.deepEqual(board(shown),board(full));
});

// Saved-character roster (view-only selection).
const ALPHA={id:2,label:'Alpha',level:67,last_seen_at:'2026-01-01T00:00:00Z',current:true};
const BETA={id:3,label:'Beta',level:43,last_seen_at:'2025-12-31T22:00:00Z',current:false};
function body(roster,changes={}){return {player:player({character:{id:2,label:'Alpha'}}),roster,view:{character_id:2,current:true},served_at:'2026-01-01T00:00:00Z',...changes};}
function server(responses){
  const urls=[];
  return {urls,fetch:async url=>{urls.push(url);const next=responses.length>1?responses.shift():responses[0];return {ok:next.status==null,status:next.status ?? 200,json:async()=>next.body ?? next};}};
}
const settle=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};

test('one saved character shows exactly the existing profile: no roster at all',async()=>{
  const api=server([body([ALPHA])]),p=page('player',api.fetch);await settle();
  assert.equal(p.elements.roster.hidden,true);assert.equal(p.elements['roster-all'].hidden,true);
  assert.equal(p.elements['player-name'].textContent,'Alpha');assert.equal(api.urls[0],'/api/players/alpha');
});

test('a second saved character reveals the roster on the next poll; tracked character first and marked',async()=>{
  const api=server([body([ALPHA]),body([ALPHA,BETA])]),p=page('player',api.fetch);await settle();
  assert.equal(p.elements.roster.hidden,true);
  await p.run('poll()');
  assert.equal(p.elements.roster.hidden,false);
  const [alpha,beta]=p.elements['roster-track'].children;
  assert.equal(alpha.attributes['aria-current'],'page');assert.equal(beta.attributes['aria-current'],undefined);
  assert.equal(alpha.children[0].textContent,'Alpha');assert.equal(alpha.children[1].children[0].textContent,'Current');
  assert.equal(beta.href,'/stream/alpha?character=3');assert.equal(alpha.href,'/stream/alpha');
  assert.equal(p.elements['roster-all'].hidden,true);
});

test('choosing an inactive character is view-only, clears old numbers and discards a late response',async()=>{
  let release;const api=server([body([ALPHA,BETA])]),p=page('player',api.fetch);await settle();
  p.context.fetch=url=>{api.urls.push(url);return new Promise(resolve=>{release=resolve;});};
  p.run('poll()');  // An Alpha poll is in flight when the visitor clicks Beta.
  p.elements['roster-track'].children[1].listeners.click({button:0,preventDefault(){}});
  assert.deepEqual(p.visits.at(-1),['push','http://127.0.0.1:8765/stream/alpha?character=3']);
  assert.equal(p.run('data'),null);assert.equal(p.elements.exp.textContent,'—');
  assert.equal(p.elements['roster-track'].children[1].attributes['aria-current'],'page');
  release({ok:true,status:200,json:async()=>body([ALPHA,BETA])});await settle();
  assert.equal(p.run('data'),null,'Late Alpha body must not render under the Beta selection');
  assert.equal(p.timers.at(-1),0);
  const inactive=body([ALPHA,BETA],{player:player({character:{id:3,label:'Beta'},age_seconds:7200,stale:true,activity:{state:'historical_session'}}),view:{character_id:3,current:false}});
  p.context.fetch=async url=>{api.urls.push(url);return {ok:true,status:200,json:async()=>inactive};};
  await p.run('poll()');
  assert.match(api.urls.at(-1),/character=3/);
  assert.equal(p.elements['player-name'].textContent,'Beta');
  assert.match(p.elements.status.textContent,/^Not currently tracked · last seen 2h ago/);
  assert.equal(p.elements['segment-note'].textContent,'Saved history');
  assert.equal(p.elements['roster-track'].children[1].attributes['aria-current'],'page');
  assert.equal(p.elements['roster-track'].children[0].attributes['aria-current'],undefined);
});

test('a direct character URL is requested; an invalid one is ignored; an unknown one falls back to live',async()=>{
  const direct=server([body([ALPHA,BETA],{view:{character_id:3,current:false}})]);
  page('player',direct.fetch,'?character=3');await settle();assert.equal(direct.urls[0],'/api/players/alpha?character=3');
  const invalid=server([body([ALPHA,BETA])]);page('player',invalid.fetch,'?character=3%20OR%201');await settle();
  assert.equal(invalid.urls[0],'/api/players/alpha');
  const unknown=server([{status:404,body:{error:'unknown_character'}},body([ALPHA,BETA])]),p=page('player',unknown.fetch,'?character=99');await settle();
  assert.deepEqual(p.visits.at(-1),['replace','http://127.0.0.1:8765/stream/alpha']);
  assert.equal(p.run('viewCharacter'),null);assert.equal(p.timers.at(-1),0);
});

test('large rosters stay one row and add a searchable list of every character',async()=>{
  const many=Array.from({length:12},(_,i)=>({id:i+2,label:i?`Hero${i}`:'Alpha',level:30+i,last_seen_at:'2026-01-01T00:00:00Z',current:!i}));
  const p=page('player',server([body(many)]).fetch);await settle();
  assert.equal(p.elements['roster-track'].children.length,12);
  assert.equal(p.elements['roster-all'].hidden,false);assert.equal(p.elements['roster-count'].textContent,'All 12');
  p.elements['roster-search'].value='hero1';p.elements['roster-search'].listeners.input();
  assert.deepEqual(p.elements['roster-list'].children.filter(item=>!item.hidden).map(item=>item.dataset.name),['hero1','hero10','hero11']);
  const six=page('player',server([body(many.slice(0,6))]).fetch);await settle();assert.equal(six.elements['roster-all'].hidden,true);
});

for(const view of ['player','overlay'])test(`${view} renders a validated level floor as the display level`,()=>{
  const p=page(view),evidence={value:67,status:'validated_level_floor',reason:'validated_level_floor',trusted:false};
  p.render(player({display_level:{value:67,status:'validated_level_floor',evidence,timestamp:'2026-01-01T00:00:00Z',age_seconds:1}}));
  assert.equal(p.elements.level.textContent,'Lv. 67');assert.match(p.elements.level.title,/^Last confirmed level for this character\.$/);
});

test('homepage Characters uses compact records, scoped links and no stale pace rankings',async()=>{
  const characters=[{...ALPHA,channel:'alpha'},{...BETA,channel:'alpha'},
    {...BETA,id:9,channel:'other',label:'Alpha',level:99,last_seen_at:null}];
  const api=server([{characters,served_at:'2026-01-01T00:00:00Z'}]);
  const p=page('board',api.fetch,'?mode=characters');await settle();
  assert.deepEqual(api.urls,['/api/players?mode=characters']);
  assert.equal(p.elements['entries'].children.length,3);
  assert.equal(p.elements['streamer-metrics'].hidden,true);assert.equal(p.elements['streamer-windows'].hidden,true);
  assert.equal(p.elements['character-controls'].hidden,false);
  const [alpha,beta,other]=p.elements.entries.children;
  assert.equal(alpha.children[1].children[0].href,'/stream/alpha?character=2');
  assert.equal(other.children[1].children[0].href,'/stream/other?character=9');
  assert.equal(alpha.children[1].children[2].textContent,'Currently tracked');
  assert.equal(beta.children[1].children[2].textContent,'Not currently tracked');
  assert.equal(other.children[2].textContent,'Not seen yet');
  assert.match(p.elements['ranking-note'].textContent,/last known level$/);
  p.elements['character-sort'].value='level';p.elements['character-sort'].listeners.change();
  assert.equal(p.elements.entries.children[0].dataset.character,9);
  p.elements['character-filter'].value='OTHER';p.elements['character-filter'].listeners.input();
  assert.equal(p.elements.entries.children.length,1);assert.equal(p.elements.entries.children[0].dataset.channel,'other');
  p.elements['character-filter'].value='missing';p.elements['character-filter'].listeners.input();assert.equal(p.elements.empty.hidden,false);
});

test('homepage toggle is view-only, preserves default cards and handles Back/Forward without reload',async()=>{
  const streamers={players:[player()]},characters={characters:[{...ALPHA,channel:'alpha'}]};
  const api=server([streamers,characters,streamers,characters]),p=page('board',api.fetch);await settle();
  assert.equal(p.run('boardMode'),'streamers');assert.equal(p.elements.entries.children.length,1);
  p.modes[1].listeners.click();await settle();
  assert.equal(p.run('boardMode'),'characters');assert.match(p.visits[0][1],/\?mode=characters$/);
  assert.equal(p.modes[1].attributes['aria-pressed'],'true');
  p.context.location.search='';p.events.popstate();await settle();
  assert.equal(p.run('boardMode'),'streamers');assert.equal(p.elements['streamer-metrics'].hidden,false);
  p.context.location.search='?mode=characters';p.events.popstate();await settle();
  assert.equal(p.run('boardMode'),'characters');assert.equal(p.visits.length,1);
  assert.deepEqual(api.urls,['/api/players','/api/players?mode=characters','/api/players','/api/players?mode=characters']);
});

test('homepage discards a late Streamers response after changing to Characters',async()=>{
  let finish;const p=page('board',()=>new Promise(resolve=>{finish=resolve;}));
  p.modes[1].listeners.click();
  finish({ok:true,json:async()=>({players:[player()]})});await settle();
  assert.equal(p.run('boardMode'),'characters');assert.equal(p.run('data'),null);assert.equal(p.run('failed'),false);
  assert.equal(p.timers.at(-1),0);
});

test('viewed roster chip is positioned after last-seen labels fill its final width',async()=>{
  const p=page('player',server([body([ALPHA,BETA])]).fetch);await settle();
  const query=p.context.document.querySelectorAll;
  p.context.document.querySelectorAll=selector=>selector==='#roster [data-seen]'?
    p.elements['roster-track'].children.map(link=>link.children[1].children[0]).filter(n=>n.dataset.seen):query(selector);
  let positioned=false;
  p.elements['roster-track'].querySelector=()=>({scrollIntoView(){
    const beta=p.elements['roster-track'].children[1];
    assert.equal(beta.children[1].children[0].textContent,'2h ago');positioned=true;
  }});
  p.run("viewCharacter='3';renderRoster()");assert(positioned);
});

function rosterMouse(p=page('player')){
  const track=p.elements['roster-track'];track.clientWidth=200;track.scrollWidth=1000;
  let left=200,captured=null;
  Object.defineProperty(track,'scrollLeft',{get:()=>left,set:value=>{left=Math.max(0,Math.min(track.scrollWidth-track.clientWidth,value));}});
  track.setPointerCapture=id=>{captured=id;};track.hasPointerCapture=id=>captured===id;
  track.releasePointerCapture=()=>{captured=null;};
  const fire=(type,changes={})=>{
    const e={pointerType:'mouse',pointerId:1,isPrimary:true,button:0,buttons:1,clientX:150,
      deltaX:0,deltaY:0,deltaMode:0,detail:1,prevented:false,stopped:false,
      preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;},...changes};
    track.listeners[type](e);return e;
  };
  return {p,track,fire,captured:()=>captured};
}

test('roster converts only vertical unmodified wheel input, including line and page units',()=>{
  const {track,fire}=rosterMouse();
  assert.equal(track.listenerOptions.wheel.passive,false);
  assert(fire('wheel',{deltaY:24}).prevented);assert.equal(track.scrollLeft,224);
  assert(fire('wheel',{deltaY:-2,deltaMode:1}).prevented);assert.equal(track.scrollLeft,192);
  assert(fire('wheel',{deltaY:1,deltaMode:2}).prevented);assert.equal(track.scrollLeft,392);
  for(const changes of [{deltaX:10},{deltaX:10,deltaY:40},...['ctrlKey','metaKey','shiftKey','altKey'].map(k=>({[k]:true,deltaY:50}))]){
    assert.equal(fire('wheel',changes).prevented,false);assert.equal(track.scrollLeft,392);
  }
});

test('roster gives the page its vertical wheel back at either boundary or without overflow',()=>{
  const {track,fire}=rosterMouse();track.scrollLeft=0;
  assert.equal(fire('wheel',{deltaY:-40}).prevented,false);
  assert(fire('wheel',{deltaY:2}).prevented);assert.equal(track.scrollLeft,2);
  track.scrollLeft=790;assert(fire('wheel',{deltaY:40}).prevented);assert.equal(track.scrollLeft,800);
  assert.equal(fire('wheel',{deltaY:40}).prevented,false);
  assert(fire('wheel',{deltaY:-40}).prevented);assert.equal(track.scrollLeft,760);
  track.scrollWidth=200;track.scrollLeft=0;
  assert.equal(fire('wheel',{deltaY:40}).prevented,false);
});

test('mouse drag captures after a small threshold, moves the strip, and suppresses only its pointer click',()=>{
  const {track,fire,captured}=rosterMouse();
  assert.equal(track.listenerOptions.click,true);
  assert.equal(fire('pointerdown').prevented,false);
  assert.equal(fire('pointermove',{clientX:147}).prevented,false);assert.equal(captured(),null);
  assert(fire('dragstart').prevented);
  assert(fire('pointermove',{clientX:100}).prevented);assert.equal(track.scrollLeft,250);
  assert.equal(captured(),1);assert.equal(track.dataset.dragging,'true');
  fire('pointerleave');assert.equal(captured(),1); // Captured release outside still finishes the drag.
  fire('pointerup',{buttons:0});assert.equal(captured(),null);assert.equal(track.dataset.dragging,undefined);
  assert.equal(fire('click',{detail:0}).prevented,false); // Keyboard activation is never swallowed.
  for(const changes of [{button:1},...['ctrlKey','shiftKey','metaKey','altKey'].map(k=>({[k]:true}))])assert.equal(fire('click',changes).prevented,false);
  const click=fire('click');assert(click.prevented && click.stopped);
  assert.equal(fire('click').prevented,false);
});

test('pointer cancellation, capture loss, early leave and released buttons clean up safely',()=>{
  for(const ending of ['pointercancel','lostpointercapture','released_buttons','modified_move']){
    const {track,fire,captured}=rosterMouse();fire('pointerdown');fire('pointermove',{clientX:100});
    if(ending==='released_buttons')fire('pointermove',{buttons:0});
    else if(ending==='modified_move')fire('pointermove',{ctrlKey:true});
    else fire(ending);
    assert.equal(track.dataset.dragging,undefined);assert.equal(captured(),null);
    fire('pointermove',{clientX:50});assert.equal(track.scrollLeft,250);
    fire('pointerdown');fire('pointerup',{buttons:0});assert.equal(fire('click').prevented,false);
  }
  const {track,fire}=rosterMouse();fire('pointerdown');fire('pointerleave');
  assert.equal(fire('pointermove',{clientX:50}).prevented,false);assert.equal(track.scrollLeft,200);
});

test('touch, pen, modified, secondary and nonoverflow gestures retain native behavior',()=>{
  for(const changes of [{pointerType:'touch'},{pointerType:'pen'},{button:1},{button:2},{isPrimary:false},
    ...['ctrlKey','metaKey','shiftKey','altKey'].map(k=>({[k]:true}))]){
    const {track,fire,captured}=rosterMouse();assert.equal(fire('pointerdown',changes).prevented,false);
    assert.equal(fire('pointermove',{...changes,clientX:80}).prevented,false);
    assert.equal(captured(),null);assert.equal(track.scrollLeft,200);
  }
  const {track,fire}=rosterMouse();track.scrollWidth=200;track.scrollLeft=0;
  fire('pointerdown');assert.equal(fire('pointermove',{clientX:80}).prevented,false);
});

test('a plain roster click navigates, a drag does not, and the next normal click still navigates',async()=>{
  const p=page('player',server([body([ALPHA,BETA])]).fetch);await settle();
  const {track,fire}=rosterMouse(p),beta=track.children[1];
  fire('pointerdown');fire('pointermove',{clientX:80});fire('pointerup',{buttons:0});
  const dragged=fire('click');if(!dragged.stopped)beta.listeners.click(dragged);
  assert.equal(p.visits.length,0);assert.equal(p.run('viewCharacter'),null);
  fire('pointerdown');fire('pointermove',{clientX:148});fire('pointerup',{buttons:0});
  const clicked=fire('click');if(!clicked.stopped)beta.listeners.click(clicked);
  assert.equal(p.run('viewCharacter'),'3');assert.match(p.visits.at(-1)[1],/\?character=3$/);
  assert.equal(p.elements['roster-list'].listeners?.wheel,undefined);
  assert.equal(p.elements['roster-search'].listeners?.pointerdown,undefined);
});

test('character page defaults: 15 min cards, 24h bar chart and a 15 min line chart',()=>{
  const p=page('player',undefined,'?defaults');
  assert.deepEqual(JSON.parse(p.run('JSON.stringify([windowMinutes,bucketSeconds,chartWindow,lineWindow])')),[15,1800,60,15]);
});

test('overlay URL options fall back on unknown values and accept only six-digit hex colours',()=>{
  const p=page('overlay');
  assert.deepEqual(JSON.parse(p.run('JSON.stringify(overlayOptions("?layout=rates&name=nope&title=tracker&bar=ABCDEF&accent=red&header=%23123456"))')),
    {layout:'rates',title:'tracker',icon:'off',name:'both',theme:'night',bar:'abcdef'});
  assert.deepEqual(JSON.parse(p.run('JSON.stringify(overlayOptions(""))')),{layout:'card',title:'site',icon:'off',name:'both',theme:'night'});
  assert.equal(p.run('overlayOptions("?icon=on").icon'),'on');
});

test('overlay rates read each lookback window; the last-hour chart keeps untracked bins unknown',()=>{
  const p=page('overlay');
  const pace=rate=>({active:true,age_seconds:0,estimates:{exp_per_hour:{value:{approximate:rate}},percentage_per_hour:null,eta:null}});
  const base=player({recent_windows:{'15':{pace:pace(1500)},'60':{pace:pace(6000)}}});p.render(base);
  assert.equal(p.run('publicPace(data.player,15).estimates.exp_per_hour.value.approximate'),1500);
  assert.equal(p.run('publicPace(data.player,60).estimates.exp_per_hour.value.approximate'),6000);
  assert.equal(p.run('publicPace(data.player,30)'),null);
  p.context.tracked={as_of:'2026-01-01T01:00:00Z',chart_intervals:[{start:'2026-01-01T00:50:00Z',end:'2026-01-01T00:52:00Z',value:{approximate:400},policy:'public_endpoint_window_v2'}]};
  p.run('data.tracked_history=tracked;drawHourChart()');
  const bars=p.elements['overlay-chart'].children;
  assert.equal(bars.length,12);assert.equal(bars.filter(b=>b.attributes.class==='bar').length,1);
  assert.equal(p.elements['hour-total'].textContent,'~400 EXP');
});

test('level ranking breaks ties on EXP % within the level and still shows the level',()=>{
  const p=page('board'),at=(channel,level,bp)=>player({channel,reading:{...player().reading,bp,level:{value:level,status:'agreement'}}});
  p.context.fixtures=[at('a',65,5000),at('b',65,7500),at('c',66,100),at('d',65,7500)];
  const rows=JSON.parse(p.run('JSON.stringify(ranked(fixtures,"level").map(r=>[r.player.channel,r.value,r.rank]))'));
  assert.deepEqual(rows,[['c',66,1],['b',65,2],['d',65,2],['a',65,4]]);
});

test('24 hour ranking uses the saved total, including streams that are not live',()=>{
  const p=page('board'),day=gain=>({tracked_status:'ready',tracked_windows:{1440:{available:true,gain:{approximate:gain}}}});
  p.context.fixtures=[player({channel:'a',...day(500)}),player({channel:'b',stale:true,...day(9000)}),player({channel:'c'})];
  assert.deepEqual(JSON.parse(p.run('JSON.stringify(ranked(fixtures,"day").map(r=>[r.player.channel,r.rank]))')),[['b',1],['a',2],['c',null]]);
});

test('the Pages export calls its configured API origin; backend-served pages stay same-origin',async()=>{
  const api=server([body([ALPHA],{history:[]})]),p=page('player',api.fetch,'?character=2','https://api.example.org');await settle();
  assert.equal(api.urls[0],'https://api.example.org/api/players/alpha?character=2');
  assert.ok(api.urls.includes('https://api.example.org/api/players/alpha/history'));
  // Overlay links and character links stay on the page's own origin, never the API's.
  assert.equal(p.elements['overlay-url'].value,'http://127.0.0.1:8765/live/overlay/alpha');
  const board=server([{players:[]}]);page('board',board.fetch,'','https://api.example.org');await settle();
  assert.equal(board.urls[0],'https://api.example.org/api/players');
  const local=server([body([ALPHA],{history:[]})]);page('player',local.fetch);await settle();
  assert.equal(local.urls[0],'/api/players/alpha');assert.ok(local.urls.includes('/api/players/alpha/history'));
  assert.equal(page('overlay',undefined,'','http://127.0.0.1:8890').run('endpoint'),'http://127.0.0.1:8890/api/players/alpha');
  for(const bad of ['http://api.example.org','https://api.example.org/','https://api.example.org/api','javascript:alert(1)','//evil.example','https://API.example.org'])
    assert.throws(()=>page('board',undefined,'',bad),/Invalid data-api origin/);
});

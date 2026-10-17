import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/exp_tracker/web/shadow.js", import.meta.url), "utf8");
class Element {
  constructor(tag = "div") { this.tag = tag; this.children = []; this.dataset = {}; this.attributes = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(name, callback) { (this.listeners ??= {})[name] = callback; }
}
function page(pathname = "/dev/shadow") {
  const elements = {}, timers = [];
  const context = vm.createContext({Intl, Date, BigInt, AbortController, URLSearchParams, location: {pathname}, performance: {now: () => 0},
    document: {hidden: false, getElementById: id => elements[id] ??= new Element(),
      createElement: tag => new Element(tag), createElementNS: (ns, tag) => new Element(tag)},
    fetch: () => new Promise(() => {}), setTimeout: (callback, delay) => { timers.push({callback, delay}); return timers.length; },
    clearTimeout: () => {}, setInterval: () => {}});
  vm.runInContext(source, context);
  const evaluate = expression => JSON.parse(vm.runInContext(`JSON.stringify(${expression})`, context));
  function render(data) { context.fixture = data; vm.runInContext('snapshot = fixture; receivedAt=0; render()', context); }
  return {elements, context, timers, evaluate, render};
}

test('conditional integer veto removes EXP chart points but preserves raw evidence and percentage',()=>{
  const p=page('/dashboard/synthetic');
  const row=observation(1,{candidate:{exp:'2458',percentage:'45.09'},raw_text:'2,458[45.09%]',
    exp_validity:{status:'invalid',reason:'contradicts_both_display_hypotheses'},
    experimental_level:{value:65,status:'recent_context',reason:'short_missing_level_read',policy:'experimental_level_v1'}});
  p.context.row=row;
  assert.equal(p.evaluate('chartValue(row,false).value'),null);
  assert.equal(p.evaluate('chartValue(row,true).value'),'45.09');
  p.render(state({channel:'synthetic',storage:'sqlite_diagnostics',selected_character:{label:'Assigned'},session:{id:1,started_at:'2026-01-01'},
    latest_reading:{observation:row},observations:[row]}));
  assert.match(p.elements['latest-candidate'].textContent,/Full EXP withheld/);
  assert.equal(p.elements['player-link'].href,'/stream/synthetic');
});

test("SQLite dashboard keeps candidate values and trusted accounting separate", async () => {
  const p = page('/dashboard/synthetic');
  const data = state({storage:'sqlite_diagnostics', selected_character:{id:1,label:'Assigned <character>'},
    session:{id:3,started_at:'2026-01-01T00:00:00Z'}, trusted_state:{last_trusted:null},
    latest_reading:{observation:observation(1),age_seconds:60,stale:true}});
  p.render(data);
  assert.equal(p.elements.persisted.hidden, false);
  assert.equal(p.elements.assignment.textContent, 'Assigned <character>');
  assert.match(p.elements['latest-candidate'].textContent, /UNVERIFIED candidate: 100 EXP/);
  assert.match(p.elements['candidate-age'].textContent, /STALE/);
  assert.match(p.elements['trusted-summary'].textContent, /no trusted session observations/);
  const requests = [];
  p.context.fetch = async url => {requests.push(url); return {ok:true,json:async()=>data};};
  await vm.runInContext('poll()',p.context);
  assert.deepEqual(requests,['/dev/api/streams/synthetic/diagnostics']);
  data.latest_reading.observation = observation(2,{candidate:null,percentage_only_candidate:{percentage:'70.51'}});
  p.render(data);
  assert.match(p.elements['latest-candidate'].textContent,/percentage only.*EXP unavailable/);
  p.render({...data,session:null,selected_character:null,latest_reading:null,observations:[]});
  assert.match(p.elements.session.textContent,/Start a session/);
  assert.match(p.elements['latest-candidate'].textContent,/Waiting/);
});
function observation(index, overrides = {}) {
  return {index, channel: "synthetic", status: "diagnostic_pair", fresh_at_capture: true,
    received_at: new Date(Date.UTC(2026, 0, 1) + index * 15000).toISOString(), attempted_at: null,
    candidate: {exp: "100", percentage: "25.00"}, raw_text: "100[25.00%]", visual_level: null,
    visual_attempts: [], hypotheses: {nearest_half_up: {status: "ambiguous", levels: [1, 2]},
      truncate: {status: "incompatible", levels: []}}, relation: "visual_unavailable", ...overrides};
}
function state(overrides = {}) {
  return {channel: "synthetic", log_status: "ready", source_status: "diagnostic_pair", run_status: "unfinished",
    observations: [observation(1)], interval_seconds: 15, age_seconds: 5, stale_after_seconds: 45, ...overrides};
}

test('chart defaults to recent captures while all loaded history and the original table remain available',()=>{
  const p=page('/dashboard/synthetic');
  p.render(state({observations:[observation(1),observation(30),observation(31)]}));
  assert.equal(p.elements.readings.children.length,3);
  assert.equal(p.elements.timeline.dataset.start,new Date(Date.UTC(2026,0,1)+30*15000).toISOString());
  assert.match(p.elements['chart-note'].textContent,/Last 5 min.*2 timestamped attempts/);
  p.elements['chart-range'].value='all';p.elements['chart-range'].listeners.change();
  assert.equal(p.elements.timeline.dataset.start,new Date(Date.UTC(2026,0,1)+15000).toISOString());
  assert.match(p.elements['chart-note'].textContent,/All loaded history.*3 timestamped attempts.*1 sampling gaps/);
  assert.equal(p.elements['percentage-timeline'].dataset.start,p.elements.timeline.dataset.start);
});

test("grammar proposals render separately and never become timeline or latest strict values", () => {
  const p=page('/dashboard/synthetic');
  const recovery={classification:'unique_proposal',raw:'123,456112.34%1',proposals:[{
    interpretation:'123,456[12.34%]',reading:{exp:'123456',percentage:'12.34'},
    edits:[{index:7,old:'1',new:'[',category:'opening_bracket'}]}]};
  const row=observation(1,{candidate:null,raw_text:recovery.raw,grammar_recovery:recovery});
  p.render(state({storage:'sqlite_diagnostics',session:{id:1,started_at:'2026-01-01'},
    selected_character:{label:'Explicit'},latest_reading:null,trusted_state:{last_trusted:null},observations:[row]}));
  const card=p.elements.readings.children[0].children[2].children.at(-1);
  assert.equal(card.className,'grammar-proposal');
  assert.equal(card.children[0].textContent,'GRAMMAR-RECOVERED / EXPERIMENTAL / UNVERIFIED');
  assert.match(card.children[1].textContent,/123,456112.34%1 → 123,456\[12.34%\]/);
  assert.ok(p.elements.timeline.children.every(n=>n.attributes.class!=='sample'));
  assert.ok(p.elements['percentage-timeline'].children.every(n=>n.attributes.class!=='sample'));
  assert.match(p.elements['latest-candidate'].textContent,/Waiting/);
  assert.equal(p.elements['latest-grammar'].hidden,false);
  row.grammar_recovery={classification:'ambiguous',reason:'multiple_interpretations_abstain',proposals:recovery.proposals};
  p.render(state({observations:[row]}));
  assert.notEqual(p.elements.readings.children[0].children[2].children.at(-1).className,'grammar-proposal');
});

test("raw and candidate values stay distinct; neither hypothesis supplies missing visual level", () => {
  const p = page(); p.render(state());
  const row = p.elements.readings.children[0];
  assert.equal(row.children[2].children[0].textContent, "100[25.00%]");
  assert.equal(row.children[2].children[1].textContent, "100 EXP [25.00%]");
  assert.equal(row.children[3].textContent, "—");
  assert.equal(row.children[4].textContent, "ambiguous · 1, 2");
  assert.equal(row.children[5].textContent, "incompatible · no candidates");
  assert.match(row.children[1].children[2].textContent, /UNVERIFIED/);
});

test("experimental progress renders recovered contributions separately and expires pace locally",()=>{
  const p=page('/dashboard/synthetic');
  const bounds={lower:{approximate:10.8},upper:{approximate:13.2}};
  const pace={value:{approximate:12},nearest_half_up:bounds,truncation:bounds};
  const estimated={lower:{approximate:1348},upper:{approximate:1647}};
  const progress={latest_percentage:{percentage:'33.10',evidence:'grammar_recovered'},age_seconds:1,stale:false,
    latest_movement:{change:'positive',difference_bp:5,difference_percentage_points:'0.05'},current_pace:pace,
    current_segment:{start_percentage:'33.00',end_percentage:'33.10',readings:3,span_seconds:{approximate:30},level:64,
      evidence_counts:{strict_full:1,strict_percentage_only:1,grammar_recovered:1},pace_reason:'eligible_experimental_endpoints',
      requirement:{status:'community_provisional',to_next:1497832},
      estimated_exp:{hypotheses:{nearest_half_up:estimated,truncation:estimated}}}};
  p.render(state({percentage_progress:progress}));
  assert.equal(p.elements['experimental-progress'].hidden,false);
  assert.match(p.elements['progress-latest'].textContent,/33.10%.*grammar-recovered proposal/);
  assert.match(p.elements['progress-pace'].textContent,/EXPERIMENTAL.*12.00 percentage points\/hour/);
  assert.match(p.elements['progress-exp'].textContent,/Not an earned-EXP total/);
  vm.runInContext('requestError=true;snapshot.run_status="active";renderStatus()',p.context);
  assert.match(p.elements['progress-pace'].textContent,/unavailable.*disconnected/);
  assert.match(p.elements['run-status'].textContent,/previously active.*activity unknown/);
  vm.runInContext('requestError=false',p.context);
  p.context.performance.now=()=>60000;vm.runInContext('renderStatus()',p.context);
  assert.match(p.elements['progress-pace'].textContent,/unavailable.*old\/stopped/);
  p.render(state({percentage_progress:{...progress,current_segment:null,current_pace:null,reason:'visual_level_unavailable'}}));
  assert.match(p.elements['progress-latest'].textContent,/33.10%/);
  assert.match(p.elements['progress-segment'].textContent,/visual level unavailable/);
});

test("v2 percentage recovery and optional chart layers never replace strict evidence", () => {
  const p = page('/dashboard/synthetic');
  const proposal = (reading) => ({classification:'unique_proposal',proposals:[{
    interpretation:reading.exp ? `${reading.exp}[${reading.percentage}%]` : `[${reading.percentage}%]`,
    reading,edits:[{index:9,old:',',new:'.',category:'percentage_decimal'}]}]});
  const full = observation(2,{candidate:null,raw_text:'123,456|12.34%|',interpretations:{
    policy:'bounded_exp_v2',raw:'123,456|12.34%|',full_exp:proposal({exp:'123456',percentage:'12.34'}),percentage:proposal({percentage:'12.34'})}});
  const only = observation(3,{candidate:null,raw_text:'5,031[33,05%]',event_id:'saved-event:3',interpretations:{
    policy:'bounded_exp_v2',raw:'5,031[33,05%]',full_exp:{classification:'rejected',reason:'exp_completeness_unknown',proposals:[]},percentage:proposal({percentage:'33.05'})}});
  const stale = {...only,index:4,fresh_at_capture:false};
  const rows = [observation(1),full,only,stale];
  p.render(state({observations:rows}));
  let nodes = p.elements.timeline.children;
  assert.equal(nodes.filter(n=>n.attributes.class==='sample').length,1);
  assert.equal(nodes.filter(n=>n.attributes.class==='recovered-full').length,0);
  const percentageCard = p.elements.readings.children[2].children[2].children.at(-1);
  assert.equal(percentageCard.children[1].textContent,'5,031[33,05%] → [33.05%]');
  assert.match(percentageCard.children[2].textContent,/Recovered percentage: 33.05%.*Absolute EXP: unavailable/);
  p.elements['show-recovered'].checked=true;
  p.elements['show-recovered'].listeners.change();
  nodes=p.elements.timeline.children;
  assert.equal(nodes.filter(n=>n.attributes.class==='sample').length,1);
  assert.equal(nodes.filter(n=>n.attributes.class==='recovered-full').length,1);
  assert.equal(nodes.filter(n=>n.attributes.class==='rejected').length,3); // Original strict failures remain visible beneath the layer.
  const percentages=p.elements['percentage-timeline'].children.filter(n=>n.attributes.class==='recovered-percentage');
  assert.equal(percentages.length,3);
  assert.equal(percentages[1].attributes['data-event-id'],'saved-event:3');
  assert.equal(percentages[2].attributes['data-stale'],'true');
  assert.equal(full.candidate,null);
  assert.ok(nodes.filter(n=>n.tag==='line').every(n=>n.attributes.class==='axis'));
  full.interpretations.full_exp.classification='ambiguous';
  only.interpretations.percentage.classification='ambiguous';
  p.render(state({observations:rows}));
  assert.equal(p.elements.timeline.children.filter(n=>n.attributes.class==='recovered-full').length,0);
  assert.match(p.elements.readings.children[2].children[2].children.at(-1).textContent,/Grammar bounded_exp_v2: full_exp: rejected.*percentage: ambiguous/);
});

test("coverage is explicitly bounded and overlapping, not accuracy or summed observations", () => {
  const p = page('/dashboard/synthetic');
  p.render(state({coverage:{session_attempts:200,summarized_attempts:120,history_limit:120,
    acquired_frames:120,unique_huds:100,strict_full_pairs:20,strict_percentage_only:5,recovered_full_exp:50,
    recovered_percentages:60,percentage_recovery_without_full:10,unrecoverable:35,ambiguous:0,
    malformed_or_missing_strict:95,visual_level_unavailable:10,neural_level_unavailable:20,
    level_conflicts:3,acquisition_unknown:0,hud_unknown:5}}));
  assert.equal(p.elements.coverage.hidden,false);
  assert.match(p.elements['coverage-scope'].textContent,/200 session attempts.*latest 120.*Categories overlap/);
  assert.equal(p.elements['coverage-counts'].children[0].children[1].textContent,'120');
  assert.match(p.elements['coverage-unknown'].textContent,/HUD-count evidence unknown: 5/);
  p.render(state());
  assert.equal(p.elements.coverage.hidden,true);
});

test("timeline is points only and marks missing sampling time, failures and stale frames", () => {
  const p = page();
  p.render(state({observations: [observation(1), observation(2, {candidate: null, status: "capture_failed"}),
    observation(5, {fresh_at_capture: false, status: "stale_local_frame"})]}));
  const nodes = p.elements.timeline.children;
  assert.equal(nodes.filter(node => node.attributes.class === "sample").length, 1);
  assert.equal(nodes.filter(node => node.attributes.class === "rejected").length, 1);
  assert.equal(nodes.filter(node => node.attributes.class === "stale").length, 1);
  assert.equal(nodes.filter(node => node.attributes.class === "gap").length, 1);
  assert.ok(nodes.filter(node => node.tag === "line").every(node => node.attributes.class === "axis"));
});

test("missing timestamps are not invented and zero EXP remains visible", () => {
  const p = page();
  p.render(state({observations: [observation(1, {candidate: {exp:"0",percentage:"0.00"}}),
    observation(2, {received_at: null, attempted_at: null})]}));
  assert.match(p.elements["chart-note"].textContent, /1 without usable timestamps/);
  assert.equal(p.elements.readings.children[0].children[2].children[1].textContent, "0 EXP [0.00%]");
  assert.equal(p.elements.readings.children[1].children[0].children[0].textContent, "Timestamp unavailable");
});

test("sampling gaps use each saved run's cadence, rather than the latest run for all history", () => {
  const p = page();
  const rows = [observation(1,{interval_seconds:30}), observation(3,{interval_seconds:30}),
    observation(4,{interval_seconds:7}), observation(6,{interval_seconds:7})];
  p.render(state({observations:rows,interval_seconds:7}));
  assert.equal(p.elements.timeline.children.filter(n=>n.attributes.class==='gap').length,1);
  assert.match(p.elements['chart-note'].textContent,/Recorded cadences: 30 \/ 7s/);
});

test("no data, missing log and malformed lines show explicit diagnostic states", () => {
  const p = page();
  p.render(state({observations: [], log_status: "missing", age_seconds: null}));
  assert.equal(p.elements.empty.hidden, false);
  assert.equal(p.elements.age.textContent, "No reading time");
  assert.match(p.elements.notice.textContent, /not found/);
  p.render(state({malformed_lines: 1, incomplete_tail: true, truncated: true}));
  assert.match(p.elements.notice.textContent, /incomplete/);
  assert.match(p.elements.notice.textContent, /malformed/);
  assert.match(p.elements.notice.textContent, /earlier content omitted/);
});

test("age advances without successful polling; cached values are never presented as fresh", async () => {
  const p = page(); p.render(state());
  p.context.performance.now = () => 41000;
  vm.runInContext('renderStatus()', p.context);
  assert.match(p.elements.age.textContent, /46s ago · OLD LOG/);
  p.context.fetch = async () => ({ok: false});
  await vm.runInContext('poll()', p.context);
  assert.match(p.elements.notice.textContent, /disconnected.*cached UNVERIFIED/);
  assert.equal(p.elements.readings.children.length, 1);
  assert.ok(p.timers.some(timer => timer.delay === 2000));
});

test("polling reads only its fixed endpoint and schedules after completion", async () => {
  const p = page();
  const requests = [];
  p.context.fetch = async (url, options) => { requests.push({url, options}); return {ok:true, json: async () => state({source_status: "offline_or_unavailable"})}; };
  await vm.runInContext('poll()', p.context);
  assert.equal(requests[0].url, "/dev/api/shadow");
  assert.equal(requests[0].options.cache, "no-store");
  assert.equal(p.elements["source-status"].textContent, "offline_or_unavailable");
  assert.ok(p.timers.some(timer => timer.delay === 5000));
  p.context.document.hidden = true;
  await vm.runInContext('poll()', p.context);
  assert.equal(requests.length, 1);
  assert.equal(p.timers.at(-1).delay, 10000);
});

test("big integers and unexpected text remain literal, without HTML injection", () => {
  const p = page();
  p.render(state({observations: [observation(1, {raw_text: "<script>", candidate: {exp:"9223372036854775807", percentage:"99.99"}})]}));
  assert.equal(p.elements.readings.children[0].children[2].children[0].textContent, "<script>");
  assert.match(p.elements.readings.children[0].children[2].children[1].textContent, /9,223,372,036,854,775,807/);
  assert.ok(!source.includes("innerHTML"));
});

test("percentage-only has no absolute EXP and partial evidence is not plotted", () => {
  const p = page();
  p.render(state({observations:[observation(1,{candidate:null,raw_text:'[70.51%]',
    percentage_only_candidate:{kind:'percentage_only',percentage:'70.51',percentage_bp:7051,trusted:false},
    diagnostic_type:'percentage_only',status:'diagnostic_percentage_only',visual_level:63}),
    observation(2,{candidate:null,partial_percentage_evidence:{percentage:'92.17'}})]}));
  assert.match(p.elements.readings.children[0].children[2].children[1].textContent,/70.51% · percentage only · EXP unavailable/);
  assert.equal(p.elements.timeline.children.filter(node=>node.attributes.class==='sample').length,0);
  assert.equal(p.elements['percentage-timeline'].children.filter(node=>node.attributes.class==='sample').length,1);
  const point=p.elements['percentage-timeline'].children.find(node=>node.attributes.class==='sample');
  assert.match(point.children[0].textContent,/70.51%/);
  assert.match(point.children[0].textContent,/visual level 63/);
});

test("percentage chart keeps gaps, stale values and visual level boundaries without joining points", () => {
  const p = page();
  p.render(state({observations:[observation(1,{visual_level:1}),
    observation(2,{visual_level:2,fresh_at_capture:false,status:'stale_local_frame'}),
    observation(5,{candidate:null})]}));
  const nodes=p.elements['percentage-timeline'].children;
  assert.equal(nodes.filter(node=>node.attributes.class==='level-break').length,1);
  assert.equal(nodes.filter(node=>node.attributes.class==='stale').length,1);
  assert.equal(nodes.filter(node=>node.attributes.class==='gap').length,1);
  assert.equal(nodes.filter(node=>node.attributes.class==='rejected').length,1);
  assert.equal(nodes.filter(node=>node.attributes.class==='level-unknown').length,1);
  assert.ok(nodes.filter(node=>node.tag==='line').every(node=>['axis','level-break','level-unknown'].includes(node.attributes.class)));
});

test("neural level is a separate unverified comparison and never supplies the chart level", () => {
  const p=page();
  p.render(state({observations:[observation(1,{visual_level:null,
    neural_level:{level:51,text:'51',score:.99,status:'numeric_candidate',comparison:'insufficient_visual_evidence'}})]}));
  const visual=p.elements.readings.children[0].children[3];
  assert.equal(visual.textContent,'—');
  assert.ok(visual.children.some(node=>node.textContent.includes('RapidOCR EXPERIMENTAL / UNVERIFIED: 51')));
  const point=p.elements['percentage-timeline'].children.find(node=>node.attributes.class==='sample');
  assert.match(point.children[0].textContent,/visual level unavailable/);
});

test('history navigation uses bounded API filters and does not relabel archived pace as current',async()=>{
  const p=page('/dashboard/synthetic');
  p.render(state({storage:'sqlite_diagnostics',historical:true,selected_character:{label:'Previous character'},
    session:{id:1,started_at:'2026-01-01'},history:{next_before:99},
    percentage_progress:{latest_percentage:null,latest_movement:null,current_segment:null,current_pace:{value:{approximate:99}},
      stale:false,age_seconds:0,segments:[]}}));
  assert.equal(p.elements['page-title'].textContent,'Streamer history');
  assert.match(p.elements['history-note'].textContent,/ARCHIVED/);
  assert.equal(p.elements['older-attempts'].disabled,false);
  assert.match(p.elements['progress-pace'].textContent,/unavailable/);
  const urls=[];
  p.context.fetch=async url=>{urls.push(url);return {ok:true,json:async()=>({sessions:[{id:1,label:'Previous character',started_at:'2026-01-01',ended_at:'2026-01-02'}],next_before:null})};};
  await vm.runInContext("loadHistory('sessions')",p.context);
  assert.equal(urls[0],'/dev/api/streams/synthetic/sessions?');
  assert.match(p.elements['history-session'].children[1].textContent,/Previous character.*closed/);
  p.elements['history-session'].value='1';
  p.context.fetch=async url=>{urls.push(url);return {ok:true,json:async()=>state({storage:'sqlite_diagnostics',historical:true,selected_character:{label:'Previous character'},session:{id:1,started_at:'2026-01-01'},history:{}})};};
  await vm.runInContext("selectHistory(new URLSearchParams('session=1&before=99'));poll()",p.context);
  assert.ok(urls.at(-1).includes('session=1&before=99'));
});

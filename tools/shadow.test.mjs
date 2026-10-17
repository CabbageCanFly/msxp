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
}
function page() {
  const elements = {}, timers = [];
  const context = vm.createContext({Intl, Date, BigInt, AbortController, performance: {now: () => 0},
    document: {hidden: false, getElementById: id => elements[id] ??= new Element(),
      createElement: tag => new Element(tag), createElementNS: (ns, tag) => new Element(tag)},
    fetch: () => new Promise(() => {}), setTimeout: (callback, delay) => { timers.push({callback, delay}); return timers.length; },
    clearTimeout: () => {}, setInterval: () => {}});
  vm.runInContext(source, context);
  const evaluate = expression => JSON.parse(vm.runInContext(`JSON.stringify(${expression})`, context));
  function render(data) { context.fixture = data; vm.runInContext('snapshot = fixture; receivedAt=0; render()', context); }
  return {elements, context, timers, evaluate, render};
}
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
  assert.ok(nodes.filter(node=>node.tag==='line').every(node=>['axis','level-break'].includes(node.attributes.class)));
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

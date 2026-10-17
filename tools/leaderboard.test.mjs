import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/exp_tracker/web/leaderboard.js", import.meta.url), "utf8");
class Element {
  constructor(tag = "div") { this.tag = tag; this.dataset = {}; this.children = []; this.attributes = {}; this.listeners = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(key, callback) { this.listeners[key] = callback; }
}
function page() {
  const elements = Object.fromEntries(["entries", "ranking-note", "ranking-count"].map(id => [id, new Element()]));
  const metrics = ["pace", "today", "level"].map(metric => Object.assign(new Element("button"), {dataset: {metric}}));
  const windows = [5, 10, 15, 30].map(minutes => Object.assign(new Element("button"), {dataset: {window: String(minutes)}}));
  const context = vm.createContext({Intl, document: {
    getElementById: id => elements[id], createElement: tag => new Element(tag),
    querySelectorAll: selector => selector === "[data-metric]" ? metrics : windows,
  }});
  vm.runInContext(source, context);
  const evaluate = expression => JSON.parse(vm.runInContext(`JSON.stringify(${expression})`, context));
  return {elements, metrics, windows, context, evaluate,
    ids: () => elements.entries.children.map(entry => entry.dataset.id)};
}

test("default simulated 30-minute pace ranks by derived rate, nulls last", () => {
  const p = page();
  assert.deepEqual(p.ids().slice(0, 3), ["fern", "moss", "ember"]);
  assert.equal(p.elements["ranking-count"].textContent, "3 ranked · 8 simulated");
  const rows = p.evaluate('rankedRows(DEMO, "pace", 30)');
  assert.deepEqual(rows.slice(0, 3).map(row => row.value), [211600, 196200, 164200]);
  assert.ok(rows.slice(3).every(row => row.value === null && row.rank === null));
});

test("every pace window is functional and score labels match its denominator", () => {
  const p = page();
  for (const button of p.windows) {
    button.listeners.click();
    const minutes = Number(button.dataset.window);
    const rows = p.evaluate(`rankedRows(DEMO, "pace", ${minutes})`);
    assert.equal(rows[0].value, rows[0].row.gains[minutes] * 60 / minutes);
    assert.match(p.elements["ranking-note"].textContent, new RegExp(`${minutes}-minute`));
    assert.ok(p.elements.entries.children.every(entry => entry.children[4].children[1].textContent === `EXP/h · ${minutes}m`));
    assert.equal(button.attributes["aria-pressed"], "true");
  }
  p.windows[0].listeners.click();
  assert.deepEqual(p.ids().slice(0, 4), ["moss", "ember", "fern", "sprout"]);
  assert.equal(p.elements["ranking-count"].textContent, "4 ranked · 8 simulated");
});

test("today and level disable irrelevant windows, then restore selected pace window", () => {
  const p = page();
  p.windows[0].listeners.click();
  p.metrics[1].listeners.click();
  assert.deepEqual(p.ids().slice(0, 6), ["fern", "moss", "ember", "bramble", "lumen", "sprout"]);
  assert.match(p.elements["ranking-note"].textContent, /16 Oct 2026 \(UTC\)/);
  assert.ok(p.windows.every(button => button.disabled));
  p.metrics[2].listeners.click();
  assert.deepEqual(p.ids().slice(0, 6), ["fern", "moss", "ember", "bramble", "lumen", "sprout"]);
  assert.match(p.elements["ranking-note"].textContent, /Last-known/);
  assert.equal(p.metrics[2].attributes["aria-pressed"], "true");
  p.metrics[0].listeners.click();
  assert.equal(p.ids()[0], "moss");
  assert.ok(p.windows.every(button => !button.disabled));
  assert.equal(p.windows[0].attributes["aria-pressed"], "true");
});

test("offline and stale never gain a pace from stored simulated history", () => {
  const p = page();
  for (const state of ["offline", "stale", "unknown", "missing"])
    assert.equal(p.evaluate(`metricValue({...DEMO[0], state: ${JSON.stringify(state)}}, "pace", 30)`), null);
  const offline = p.elements.entries.children.find(row => row.dataset.id === "bramble");
  assert.match(offline.children[2].children[2].textContent, /Offline · Last update 2h ago/);
  assert.match(offline.children[3].children[1].textContent, /Last-known EXP/);
});

test("missing readings stay absent while genuine simulated zero remains rankable", () => {
  const p = page();
  const empty = p.elements.entries.children.find(row => row.dataset.id === "pebble");
  assert.equal(empty.children[0].textContent, "—");
  assert.equal(empty.children[1].children[1].textContent, "—");
  assert.equal(empty.children[3].children[0].children[0].hidden, true);
  assert.equal(empty.children[3].children[0].children[1].children[1].textContent, "—");
  assert.equal(empty.children[4].children[0].textContent, "—");
  assert.equal(p.evaluate('metricValue({...DEMO[0], gains: {30: 0}}, "pace", 30)'), 0);
  assert.equal(p.evaluate('rankedRows([{...DEMO[0], gains: {30: 0}}], "pace", 30)[0].rank'), 1);
});

test("ties share competition rank with stable identity order", () => {
  const p = page();
  const rows = p.evaluate('rankedRows([{...DEMO[0], id:"b", level:10}, {...DEMO[0], id:"a", level:10}, {...DEMO[0], id:"c", level:5}], "level", 30)');
  assert.deepEqual(rows.map(row => [row.row.id, row.rank]), [["a", 1], ["b", 1], ["c", 3]]);
});

test("unknown controls fail explicitly; names are literal DOM text", () => {
  const p = page();
  assert.throws(() => p.evaluate('rankedRows(DEMO, "eta", 30)'), /Unknown demo control/);
  assert.throws(() => p.evaluate('rankedRows(DEMO, "pace", 1)'), /Unknown demo control/);
  assert.equal(p.evaluate('entryElement({row:{...DEMO[0],character:"<script>"},value:1,rank:1}).children[2].children[0].textContent'), "<script>");
  assert.ok(!/innerHTML|fetch\(|XMLHttpRequest|WebSocket/.test(source));
});

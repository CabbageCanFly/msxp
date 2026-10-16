import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/exp_tracker/web/overlay.js", import.meta.url), "utf8");
function page() {
  const elements = {};
  const context = vm.createContext({Intl, AbortController, location: {pathname: "/overlay/demo"},
    document: {getElementById: id => elements[id] ??= {dataset: {}, textContent: ""}},
    performance: {now: () => 0}, fetch: () => new Promise(() => {}),
    setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => {}});
  vm.runInContext(source, context);
  function render(state, elapsed = 0) {
    context.fixture = state;
    context.performance.now = () => elapsed * 1000;
    vm.runInContext("snapshot = fixture; receivedAt = 0; render()", context);
    return elements;
  }
  return {elements, context, render};
}
function state(overrides = {}) {
  return {channel: "demo", selected_character: {id: 1, label: "Synthetic <script>"}, session: {id: 1},
    status: "tracking", reason: "same_level_gain", last_trusted: {session_id: 1, level: 60, current_exp: 1500,
      percentage_bp: 1500, observed_at: "2026-01-01T00:00:00Z"}, age_seconds: 5, stale: false,
    stale_after_seconds: 120, observed_session_exp: 500, bridged_session_exp: 0, continuity_broken: false, ...overrides};
}

test("trusted values and literal character text render without HTML injection", () => {
  const elements = page().render(state({bridged_session_exp: 100}));
  assert.equal(elements.exp.textContent, "1,500");
  assert.equal(elements.percentage.textContent, "15.00%");
  assert.equal(elements.progress.value, 15);
  assert.equal(elements["session-exp"].textContent, "+500");
  assert.equal(elements.character.textContent, "Synthetic <script>");
  assert.equal(elements.bridged.hidden, false);
  assert.equal(elements.status.textContent, "Tracking");
});

test("staleness advances locally without new API responses", () => {
  const current = page();
  assert.equal(current.render(state(), 115).status.textContent, "Tracking");
  const stale = current.render(state(), 116);
  assert.equal(stale.status.textContent, "Stale");
  assert.equal(stale.exp.textContent, "1,500");
  assert.equal(stale.card.dataset.stale, "true");
  assert.match(stale.age.textContent, /121s ago/);
});

test("soft pause, hard pause and offline have distinct honest labels", () => {
  assert.equal(page().render(state({status: "paused"})).status.textContent, "OCR interrupted");
  assert.equal(page().render(state({status: "paused", continuity_broken: true})).status.textContent, "Paused");
  assert.equal(page().render(state({status: "offline"})).status.textContent, "Offline");
  assert.equal(page().render(state({status: "offline", stale: true})).status.textContent, "Offline · stale");
});

test("unconfigured, no-session and waiting states do not invent zero readings", () => {
  const empty = page().render(state({selected_character: null, session: null, last_trusted: null}));
  assert.equal(empty.status.textContent, "Unconfigured");
  assert.equal(empty.exp.textContent, "—");
  assert.equal(empty["session-exp"].textContent, "—");
  assert.equal(page().render(state({session: null})).status.textContent, "No active session");
  assert.equal(page().render(state({last_trusted: null, status: "waiting"})).status.textContent, "Waiting for reading");
  assert.equal(page().render(state({last_trusted: null, status: "paused", continuity_broken: true})).status.textContent, "Paused");
  const previous = page().render(state({session: {id: 2}, status: "waiting"}));
  assert.match(previous.detail.textContent, /previous session/);
  assert.match(page().render(state({session: {id: 2}, status: "waiting", stale: true})).detail.textContent, /previous session/);
});

test("HTTP failure retains cached values and never labels them tracking", async () => {
  const current = page();
  current.render(state());
  current.context.fetch = async () => ({ok: false, status: 503});
  await vm.runInContext("poll()", current.context);
  assert.equal(current.elements.status.textContent, "API unavailable");
  assert.equal(current.elements.exp.textContent, "1,500");
  assert.match(current.elements.detail.textContent, /cached/);
});

test("successful polling replaces selection and clears the old character's values", async () => {
  const current = page();
  current.render(state());
  current.context.fetch = async () => ({ok: true, json: async () => state({selected_character: {id: 2, label: "Bowman"},
    status: "waiting", last_trusted: null, observed_session_exp: 0})});
  await vm.runInContext("poll()", current.context);
  assert.equal(current.elements.character.textContent, "Bowman");
  assert.equal(current.elements.exp.textContent, "—");
  assert.equal(current.elements["session-exp"].textContent, "+0");
});

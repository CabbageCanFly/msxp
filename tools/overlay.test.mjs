import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/exp_tracker/web/overlay.js", import.meta.url), "utf8");
function page() {
  const elements = {};
  const scheduled = [];
  const context = vm.createContext({Intl, AbortController, location: {pathname: "/overlay/demo"},
    document: {getElementById: id => elements[id] ??= {dataset: {}, textContent: ""}},
    performance: {now: () => 0}, fetch: () => new Promise(() => {}),
    setTimeout: (callback, delay) => { scheduled.push({callback, delay}); return scheduled.length; },
    clearTimeout: () => {}, setInterval: () => {}});
  vm.runInContext(source, context);
  function render(state, elapsed = 0) {
    context.fixture = state;
    context.performance.now = () => elapsed * 1000;
    vm.runInContext("snapshot = fixture; receivedAt = 0; render()", context);
    return elements;
  }
  return {elements, context, render, scheduled};
}
function state(overrides = {}) {
  return {channel: "demo", selected_character: {id: 1, label: "Synthetic <script>"}, session: {id: 1},
    status: "tracking", reason: "same_level_gain", last_trusted: {session_id: 1, level: 60, current_exp: 1500,
      percentage_bp: 1500, observed_at: "2026-01-01T00:00:00Z"}, age_seconds: 5, stale: false,
    stale_after_seconds: 120, observed_session_exp: 500, bridged_session_exp: 0, continuity_broken: false,
    statistics: {last_5_min: {exp: 20000, covered_seconds: 300, window_seconds: 300, boundary_trimmed: false},
      exp_per_hour_30m: {exp: 120000, exp_per_hour: 240000, covered_seconds: 1800, window_seconds: 1800},
      to_next_level: {seconds: 11400}}, ...overrides};
}

test("trusted values and literal character text render without HTML injection", () => {
  const elements = page().render(state({bridged_session_exp: 100}));
  assert.equal(elements.exp.textContent, "1,500");
  assert.equal(elements.percentage.textContent, "15.00%");
  assert.equal(elements.progress.value, 15);
  assert.equal(elements["session-exp"].textContent, "+500");
  assert.equal(elements.character.textContent, "Synthetic <script>");
  assert.equal(elements.status.textContent, "");
  assert.equal(elements.age.textContent, "Updated 5s ago");
  assert.equal(elements.character.title, "Synthetic <script>");
  assert.equal(elements.bridged, undefined);
  assert.equal(elements.detail, undefined);
  assert.equal(elements.channel, undefined);
  assert.equal(elements.streamer.textContent, "ttv/demo");
  assert.equal(elements.rank.hidden, true);
  assert.equal(elements.rank.textContent, "");
  assert.equal(elements["recent-exp"].textContent, "+20K");
  assert.equal(elements.pace.textContent, "~240K");
  assert.equal(elements.eta.textContent, "~3h 10m");
});

test("staleness advances locally without new API responses", () => {
  const current = page();
  assert.equal(current.render(state(), 115).status.textContent, "");
  const stale = current.render(state(), 116);
  assert.equal(stale.status.textContent, "Updates delayed");
  assert.equal(stale.exp.textContent, "1,500");
  assert.equal(stale.card.dataset.stale, "true");
  assert.match(stale.age.textContent, /121s ago/);
  assert.equal(stale.pace.textContent, "—");
  assert.equal(stale["recent-exp"].textContent, "—");
  assert.equal(stale.eta.textContent, "—");
});

test("brief unreadable frames stay quiet; hard pause and offline stay understandable", () => {
  assert.equal(page().render(state({status: "paused", reason: "synthetic_demo_unreadable"})).status.textContent, "");
  assert.equal(page().render(state({status: "paused", reason: "explicit_pause", continuity_broken: true})).status.textContent, "Paused");
  assert.equal(page().render(state({status: "offline"})).status.textContent, "Offline");
  const offline = page().render(state({status: "offline", stale: true, age_seconds: 121}));
  assert.equal(offline.status.textContent, "Offline");
  assert.equal(offline.age.textContent, "Updated 121s ago");
  assert.equal(offline.pace.textContent, "—");
  assert.equal(page().render(state({status: "offline", last_trusted: null})).status.textContent, "Offline");
  assert.equal(page().render(state({status: "ambiguous"})).status.textContent, "Updates delayed");
});

test("unconfigured, no-session and waiting states do not invent zero readings", () => {
  const empty = page().render(state({selected_character: null, session: null, last_trusted: null}));
  assert.equal(empty.status.textContent, "Waiting for EXP");
  assert.equal(empty.exp.textContent, "—");
  assert.equal(empty["session-exp"].textContent, "—");
  assert.equal(empty.age.textContent, "");
  assert.equal(page().render(state({session: null})).status.textContent, "Paused");
  assert.equal(page().render(state({last_trusted: null, status: "waiting"})).status.textContent, "Waiting for EXP");
  assert.equal(page().render(state({last_trusted: null, status: "paused", continuity_broken: true})).status.textContent, "Waiting for EXP");
  const previous = page().render(state({session: {id: 2}, status: "waiting"}));
  assert.equal(previous.status.textContent, "Waiting for EXP");
  assert.equal(previous.exp.textContent, "1,500");
});

test("HTTP failure retains cached values and never labels them tracking", async () => {
  const current = page();
  current.render(state());
  current.context.fetch = async () => ({ok: false, status: 503});
  await vm.runInContext("poll()", current.context);
  assert.equal(current.elements.status.textContent, "Updates delayed");
  assert.equal(current.elements.exp.textContent, "1,500");
  assert.equal(current.elements.age.textContent, "Updated 5s ago");
  assert.equal(current.elements.pace.textContent, "—");
  assert.equal(current.elements["session-exp"].textContent, "+500");
  assert.equal(current.scheduled.at(-1).delay, 2000);
  assert.equal(current.scheduled.at(-2).delay, 4000);
  current.context.fetch = async () => ({ok: true, json: async () => state({age_seconds: 0,
    last_trusted: {...state().last_trusted, current_exp: 2000}})});
  await vm.runInContext("poll()", current.context);
  assert.equal(current.elements.status.textContent, "");
  assert.equal(current.elements.exp.textContent, "2,000");
  assert.equal(current.elements.age.textContent, "Updated 0s ago");
  assert.equal(current.elements.pace.textContent, "~240K");
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

test("long names and large metrics use controlled overflow and smaller numerals", () => {
  const character = "VeryLongCharacterName".repeat(5);
  const elements = page().render(state({selected_character: {id: 1, label: character},
    last_trusted: {...state().last_trusted, current_exp: Number.MAX_SAFE_INTEGER, percentage_bp: 9999},
    observed_session_exp: Number.MAX_SAFE_INTEGER}));
  assert.equal(elements.character.textContent, character);
  assert.equal(elements.character.title, character);
  assert.equal(elements.exp.textContent, "9,007,199,254,740,991");
  assert.equal(elements["session-exp"].textContent, "+9007.2T");
  assert.equal(elements.exp.dataset.size, "long");
  assert.equal(elements["session-exp"].title, "9,007,199,254,740,991");
  assert.equal(elements.percentage.textContent, "99.99%");
});

test("initial request failures and unknown channels stay simple without inventing values", async () => {
  const current = page();
  current.context.fetch = async () => ({ok: false, status: 404});
  await vm.runInContext("poll()", current.context);
  assert.equal(current.elements.status.textContent, "Waiting for EXP");
  assert.equal(current.elements.exp.textContent, "—");
  assert.equal(current.elements.age.textContent, "");
  const text = Object.values(current.elements).map(element => element.textContent).join(" ");
  assert.doesNotMatch(text, /API|OCR|trusted|bridged|synthetic_demo|Live/);
});

test("unavailable windows show dashes while valid zero progress stays zero", () => {
  const empty = page().render(state({statistics: {last_5_min: {exp: null}, exp_per_hour_30m: {exp_per_hour: null}, to_next_level: {seconds: null}}}));
  assert.equal(empty["recent-exp"].textContent, "—");
  assert.equal(empty.pace.textContent, "—");
  assert.equal(empty.eta.textContent, "—");
  const zero = page().render(state({statistics: {last_5_min: {exp: 0}, exp_per_hour_30m: {exp_per_hour: 0}}}));
  assert.equal(zero["recent-exp"].textContent, "+0");
  assert.equal(zero.pace.textContent, "~0");
  assert.equal(zero.eta.textContent, "—");
});

test("trimmed windows are marked and ETA is rounded to minutes instead of counting down", () => {
  const current = page();
  const partial = state({statistics: {...state().statistics, last_5_min: {...state().statistics.last_5_min, exp: 18000, boundary_trimmed: true},
    to_next_level: {seconds: 61}}});
  assert.equal(current.render(partial)["recent-exp"].textContent, "~18K");
  assert.equal(current.render(partial, 10).eta.textContent, "~2m");
  assert.equal(page().render(state({statistics: {to_next_level: {seconds: 172800}}})).eta.textContent, "~2d 0h");
});

test("rank is absent unless authoritative and valid; sample rank is synthetic test data only", () => {
  for (const ranking of [undefined, {rank: 7}, {rank: 7, authoritative: false}, {rank: 0, authoritative: true},
    {rank: -1, authoritative: true}, {rank: 1.5, authoritative: true}]) {
    const elements = page().render(state({ranking}));
    assert.equal(elements.rank.hidden, true);
    assert.equal(elements.rank.textContent, "");
  }
  // No production API emits ranking. This is explicitly synthetic browser-test input.
  const elements = page().render(state({ranking: {rank: 7, authoritative: true}}));
  assert.equal(elements.rank.textContent, "#7");
  assert.equal(elements.rank.hidden, false);
  assert.equal(elements.streamer.textContent, "ttv/demo");
  assert.equal(elements.character.textContent, "Synthetic <script>");
});

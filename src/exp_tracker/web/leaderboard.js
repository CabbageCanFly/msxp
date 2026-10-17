"use strict";

// Fixed invented snapshots, not Store statistics or an EXP-to-level table.
const DEMO = [
  {id: "fern", character: "Sunfern", channel: "demo_sunfern", state: "tracking", age: "Updated 8s ago", level: 63, exp: 482160, bp: 6142, today: 3800000, gains: {5: 19300, 10: 36600, 15: 53500, 30: 105800}},
  {id: "moss", character: "Mosswhisper", channel: "demo_moss", state: "tracking", age: "Updated 12s ago", level: 61, exp: 386240, bp: 4288, today: 1700000, gains: {5: 21000, 10: 40000, 15: 55500, 30: 98100}},
  {id: "ember", character: "Embertrail", channel: "demo_ember", state: "tracking", age: "Updated 6s ago", level: 55, exp: 512780, bp: 6925, today: 1100000, gains: {5: 20525, 10: 39000, 15: 56000, 30: 82100}},
  {id: "sprout", character: "LittleSprout", channel: "demo_sprout", state: "insufficient", age: "Updated 10s ago", level: 29, exp: 23910, bp: 3826, today: 200700, gains: {5: 4000, 10: null, 15: null, 30: null}},
  {id: "bramble", character: "Brambleberry", channel: "demo_bramble", state: "offline", age: "Last update 2h ago", level: 45, exp: 168240, bp: 3591, today: 640000, gains: {}},
  {id: "lumen", character: "Lumenvale", channel: "demo_lumen", state: "stale", age: "Last update 3m ago", level: 40, exp: 96480, bp: 3280, today: 300000, gains: {}},
  {id: "wisp", character: "Cloudwisp", channel: "demo_wisp", state: "unknown", age: "No update time", level: null, exp: null, bp: null, today: null, gains: {}},
  {id: "pebble", character: "PocketPebble", channel: "demo_pebble", state: "missing", age: "No reading yet", level: null, exp: null, bp: null, today: null, gains: {}},
];
const WINDOWS = [5, 10, 15, 30];
const METRICS = {pace: "EXP / hour", today: "Today's EXP", level: "Level"};
const STATES = {tracking: "Tracking", insufficient: "Building history", offline: "Offline", stale: "Updates delayed", unknown: "Status unknown", missing: "Waiting for EXP"};
const numbers = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", {notation: "compact", maximumFractionDigits: 1});
let metric = "pace", windowMinutes = 30;

function metricValue(row, key, minutes) {
  if (!(key in METRICS) || !WINDOWS.includes(minutes)) throw new Error("Unknown demo control");
  if (key === "level") return row.level;
  if (key === "today") return row.today;
  if (!["tracking", "insufficient"].includes(row.state)) return null;
  const gain = row.gains[minutes];
  return gain == null ? null : gain * 60 / minutes;
}

function rankedRows(rows, key, minutes) {
  const sorted = rows.map(row => ({row, value: metricValue(row, key, minutes)})).sort((a, b) =>
    (a.value == null) - (b.value == null) || (b.value ?? 0) - (a.value ?? 0) || a.row.id.localeCompare(b.row.id, "en"));
  let rank = null, previous = null;
  return sorted.map((entry, index) => {
    if (entry.value != null && entry.value !== previous) rank = index + 1;
    previous = entry.value;
    return {...entry, rank: entry.value == null ? null : rank};
  });
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function entryElement({row, value, rank}) {
  const entry = element("li", "entry");
  entry.dataset.id = row.id;
  entry.dataset.state = row.state;
  entry.dataset.rank = rank ?? "";
  const badge = element("span", "rank", rank ?? "—");
  badge.dataset.medal = rank <= 3 && rank !== null ? rank : "";
  badge.setAttribute("aria-label", rank == null ? "Unranked: metric unavailable" : `Simulated rank ${rank}`);
  const level = element("span", "level");
  level.append(element("small", "", "LV."), element("strong", "", row.level ?? "—"));
  const identity = element("div", "identity");
  const name = element("span", "character", row.character);
  name.title = row.character;
  const channel = element("span", "channel", `ttv/${row.channel}`);
  channel.title = `Simulated Twitch identity: ${row.channel}`;
  identity.append(name, channel, element("span", "status", `${STATES[row.state]} · ${row.age}`));
  const expSection = element("div", "exp-section"), bar = element("div", "exp-bar");
  const progress = element("progress", "");
  progress.max = 100;
  progress.hidden = row.bp == null;
  if (row.bp != null) progress.value = row.bp / 100;
  progress.setAttribute("aria-label", `Simulated EXP percentage for ${row.character}`);
  const label = element("span", "exp-label");
  label.append(element("small", "", "EXP"), element("span", "exp-number", row.exp == null ? "—" : numbers.format(row.exp)),
    element("span", "percentage", row.bp == null ? "" : `[${(row.bp / 100).toFixed(2)}%]`));
  bar.append(progress, label);
  let detail = row.today == null ? "Today's EXP unavailable" : `${compact.format(row.today)} recorded in demo day`;
  if (metric === "pace") detail = value == null ? "No complete, fresh window" : `+${numbers.format(row.gains[windowMinutes])} EXP in ${windowMinutes}m`;
  if (["offline", "stale"].includes(row.state)) detail = `Last-known EXP · ${detail}`;
  expSection.append(bar, element("div", "exp-detail", detail));
  const score = element("div", "score");
  const scoreLabel = metric === "pace" ? `EXP/h · ${windowMinutes}m` : metric === "today" ? "EXP · demo day" : "last-known level";
  const formatted = value == null ? "—" : metric === "level" ? numbers.format(value) : compact.format(value);
  score.append(element("strong", "score-value", formatted), element("small", "score-label", scoreLabel));
  score.title = value == null ? "Unavailable; not ranked" : `${numbers.format(value)} ${scoreLabel} (simulated)`;
  entry.append(badge, level, identity, expSection, score);
  return entry;
}

function renderLeaderboard() {
  const rows = rankedRows(DEMO, metric, windowMinutes);
  document.getElementById("entries").replaceChildren(...rows.map(entryElement));
  document.getElementById("ranking-note").textContent = metric === "pace"
    ? `Estimated hourly pace from complete simulated ${windowMinutes}-minute windows.`
    : metric === "today" ? "Recorded EXP · simulated 16 Oct 2026 (UTC). Time-window controls do not apply."
    : "Last-known simulated levels. Time-window controls do not apply.";
  document.getElementById("ranking-count").textContent = `${rows.filter(row => row.rank != null).length} ranked · ${rows.length} simulated`;
  document.querySelectorAll("[data-metric]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.metric === metric)));
  document.querySelectorAll("[data-window]").forEach(button => {
    button.disabled = metric !== "pace";
    button.setAttribute("aria-pressed", String(Number(button.dataset.window) === windowMinutes));
  });
}

document.querySelectorAll("[data-metric]").forEach(button => button.addEventListener("click", () => {
  metric = button.dataset.metric;
  renderLeaderboard();
}));
document.querySelectorAll("[data-window]").forEach(button => button.addEventListener("click", () => {
  windowMinutes = Number(button.dataset.window);
  renderLeaderboard();
}));
renderLeaderboard();

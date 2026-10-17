"use strict";
let snapshot = null, receivedAt = 0, requestError = false;
const nf = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", {notation: "compact", maximumFractionDigits: 1});
const svgNS = "http://www.w3.org/2000/svg";

function element(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}
function timeOf(row) {
  const value = Date.parse(row.received_at || row.attempted_at || "");
  return Number.isFinite(value) ? value : null;
}
function displayTime(row) {
  const value = timeOf(row);
  return value == null ? "Timestamp unavailable" : new Date(value).toISOString().replace("T", " ").replace("+00:00", "");
}
function levels(hypothesis) {
  if (!hypothesis) return "Unavailable";
  return `${hypothesis.status} · ${hypothesis.levels.length ? hypothesis.levels.join(", ") : "no candidates"}`;
}
function exactExp(value) {
  return value == null ? "—" : nf.format(BigInt(value));
}
function timelineData(rows, interval) {
  const points = rows.map((row, position) => ({row, position, time: timeOf(row)})).filter(point => point.time !== null);
  const gaps = [];
  for (let i = 1; i < points.length; i++) {
    const previous = points[i - 1], point = points[i];
    if (interval && point.time - previous.time > interval * 1500) gaps.push([previous.time, point.time]);
  }
  return {points, gaps, missingTimes: rows.length - points.length};
}
function drawTimeline(rows, interval) {
  const svg = document.getElementById("timeline");
  svg.replaceChildren();
  const {points, gaps, missingTimes} = timelineData(rows, interval);
  function shape(tag, attributes, title) {
    const node = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (title) { const label = document.createElementNS(svgNS, "title"); label.textContent = title; node.append(label); }
    svg.append(node);
    return node;
  }
  document.getElementById("chart-note").textContent = `${points.length} timestamped attempts · ${gaps.length} sampling gaps · ${missingTimes} without usable timestamps. ${interval ? `Expected cadence ${interval}s.` : "Expected cadence unavailable."}`;
  if (!points.length) { shape("text", {x: 40, y: 105}).textContent = "Waiting for timestamped attempts"; return; }
  const times = points.map(point => point.time), values = points.filter(p => p.row.candidate).map(p => Number(p.row.candidate.exp));
  const left = Math.min(...times), right = Math.max(...times), low = Math.min(...values), high = Math.max(...values);
  const x = time => 80 + (time - left) / (right - left || 1) * 850;
  const y = value => high === low ? 95 : 155 - (value - low) / (high - low) * 115;
  for (const [start, end] of gaps) shape("rect", {x: x(start), y: 20, width: x(end) - x(start), height: 160, class: "gap"}, "Unobserved sampling gap; no values inferred");
  shape("line", {x1: 80, x2: 930, y1: 180, y2: 180, class: "axis"});
  if (values.length) {
    shape("text", {x: 4, y: 43}).textContent = compact.format(high);
    shape("text", {x: 4, y: 158}).textContent = compact.format(low);
  }
  for (const point of points) {
    const row = point.row, px = x(point.time);
    const label = `#${row.index ?? "?"} ${displayTime(row)} · ${row.status}`;
    if (row.candidate) {
      const py = y(Number(row.candidate.exp));
      if (row.fresh_at_capture && row.status === "diagnostic_pair")
        shape("circle", {cx: px, cy: py, r: 4, class: "sample"}, `${label} · UNVERIFIED ${exactExp(row.candidate.exp)} EXP`);
      else shape("path", {d: `M${px} ${py-5}l5 5-5 5-5-5Z`, class: "stale"}, label);
    } else shape("path", {d: `M${px-4} 168l8 8m0-8-8 8`, class: "rejected"}, label);
  }
  shape("text", {x: 80, y: 211}).textContent = new Date(left).toISOString().slice(11, 19) + " UTC";
  shape("text", {x: 930, y: 211, "text-anchor": "end"}).textContent = new Date(right).toISOString().slice(11, 19) + " UTC";
}
function renderStatus() {
  const age = snapshot?.age_seconds == null ? null : snapshot.age_seconds + (performance.now() - receivedAt) / 1000;
  const delayed = snapshot?.stale || age > (snapshot?.stale_after_seconds ?? 45);
  document.getElementById("age").textContent = age == null ? "No reading time" : `${Math.floor(age)}s ago${delayed ? " · OLD LOG" : " · local age only"}`;
  const notices = [];
  if (requestError) notices.push("Viewer disconnected · showing cached UNVERIFIED diagnostics");
  if (snapshot?.log_status === "missing") notices.push("Configured log not found yet; waiting for the capture writer");
  if (snapshot?.log_status === "unavailable") notices.push("Configured diagnostic file unavailable");
  if (snapshot?.incomplete_tail) notices.push("Trailing write incomplete; only completed lines shown");
  if (snapshot?.malformed_lines) notices.push(`${snapshot.malformed_lines} malformed lines; no repair attempted`);
  if (snapshot?.truncated) notices.push("Bounded recent history only; earlier content omitted");
  if (delayed) notices.push("Updates old/delayed; capture activity is not established");
  document.getElementById("notice").textContent = notices.join(" · ") || "Read-only UNVERIFIED diagnostics · local delivery does not prove source freshness";
}
function render() {
  const rows = snapshot?.observations || [];
  document.getElementById("channel").textContent = snapshot?.mixed_channels ? "Mixed sources — see rows" : snapshot?.channel ? `ttv/${snapshot.channel}` : "Local video / channel unavailable";
  document.getElementById("source-status").textContent = snapshot?.source_status || "Waiting for diagnostics";
  document.getElementById("run-status").textContent = `Run: ${snapshot?.run_status || "waiting"} · UNVERIFIED`;
  document.getElementById("count").textContent = `(${rows.length} · UNVERIFIED)`;
  document.getElementById("empty").hidden = rows.length > 0;
  const entries = rows.map(row => {
    const tr = element("tr");
    tr.dataset.status = row.status;
    if (!row.candidate || !row.fresh_at_capture) tr.className = "rejected-row";
    const when = element("td", `#${row.index ?? "—"}`);
    when.append(element("small", displayTime(row)), element("small", row.channel ? `ttv/${row.channel}` : "Source unspecified"));
    const status = element("td", row.status);
    status.append(element("small", `Neural: ${row.neural_status ?? "not available"}`), element("small", row.fresh_at_capture ? "Fresh at local capture" : "Not fresh / unavailable at capture"), element("small", "UNVERIFIED"));
    const value = element("td");
    value.append(element("code", row.raw_text_redacted ? "[Non-numeric diagnostic text redacted]" : row.raw_text ?? "—"),
      element("span", row.candidate ? `${exactExp(row.candidate.exp)} EXP [${row.candidate.percentage}%]` : "No complete saved pair"));
    const visual = element("td", row.visual_level ?? "—");
    visual.append(element("small", `Visual: ${row.visual_status ?? "unavailable"}`));
    if (row.visual_attempts?.length) visual.append(element("small", `Raw passes: ${row.visual_attempts.map(text => text ?? "[redacted]").join(" / ")}`));
    const evidence = element("td", row.relation ?? "Unavailable");
    evidence.append(element("small", row.reasons?.join(", ") || "No additional reason codes"));
    if (row.candidate_invalid) evidence.append(element("small", "Saved candidate invalid; not repaired"));
    tr.append(when, status, value, visual, element("td", levels(row.hypotheses?.nearest_half_up)), element("td", levels(row.hypotheses?.truncate)), evidence);
    return tr;
  });
  document.getElementById("readings").replaceChildren(...entries);
  drawTimeline(rows, snapshot?.interval_seconds);
  renderStatus();
}
async function poll() {
  let controller, timer;
  try {
    if (document.hidden) return;
    controller = new AbortController();
    timer = setTimeout(() => controller.abort(), 5000);
    const response = await fetch("/dev/api/shadow", {cache: "no-store", signal: controller.signal});
    if (!response.ok) throw new Error("Viewer unavailable");
    snapshot = await response.json();
    receivedAt = performance.now();
    requestError = false;
    render();
  } catch {
    requestError = true;
    renderStatus();
  } finally {
    clearTimeout(timer);
    setTimeout(poll, document.hidden ? 10000 : 2000);
  }
}
poll();
setInterval(renderStatus, 1000);

"use strict";
let snapshot = null, receivedAt = 0, requestError = false;
const nf = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", {notation: "compact", maximumFractionDigits: 1});
const svgNS = "http://www.w3.org/2000/svg";
const dashboardChannel = /^\/dashboard\/([A-Za-z0-9_]{1,25})$/.exec(globalThis.location?.pathname ?? "")?.[1];
const endpoint = dashboardChannel ? `/dev/api/streams/${encodeURIComponent(dashboardChannel)}/diagnostics` : "/dev/api/shadow";

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
function grammarCard(recovery) {
  if (recovery?.classification !== "unique_proposal" || recovery.proposals?.length !== 1) return null;
  const proposal = recovery.proposals[0], card = element("div");
  card.className = "grammar-proposal";
  card.append(element("small", "GRAMMAR-RECOVERED / EXPERIMENTAL / UNVERIFIED"),
    element("code", `${recovery.raw} → ${proposal.interpretation}`),
    element("small", `${exactExp(proposal.reading.exp)} EXP [${proposal.reading.percentage}%] · proposal only`),
    element("small", `Edits (zero-based): ${proposal.edits.map(e => `${e.index}: ${e.old} → ${e.new} (${e.category})`).join("; ")}`),
    element("small", "Source completeness and numeric digits unverified. No tracking or pace contribution."));
  return card;
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
function drawTimeline(rows, interval, percentage = false) {
  const svg = document.getElementById(percentage ? "percentage-timeline" : "timeline");
  svg.replaceChildren();
  const {points, gaps, missingTimes} = timelineData(rows, interval);
  function shape(tag, attributes, title) {
    const node = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (title) { const label = document.createElementNS(svgNS, "title"); label.textContent = title; node.append(label); }
    svg.append(node);
    return node;
  }
  const levelBreaks = points.filter((point, i) => i && point.row.visual_level != null && points[i-1].row.visual_level != null && point.row.visual_level !== points[i-1].row.visual_level);
  document.getElementById(percentage ? "percentage-note" : "chart-note").textContent = `${points.length} timestamped attempts · ${gaps.length} sampling gaps · ${missingTimes} without usable timestamps. ${interval ? `Expected cadence ${interval}s.` : "Expected cadence unavailable."}${percentage ? ` ${levelBreaks.length} observed visual-level changes; unknown levels do not establish continuity. Hover points for exact percentage and visual level.` : ""}`;
  if (!points.length) { shape("text", {x: 40, y: 105}).textContent = "Waiting for timestamped attempts"; return; }
  const valueOf = row => percentage ? row.candidate?.percentage ?? row.percentage_only_candidate?.percentage ?? null : row.candidate?.exp ?? null;
  const times = points.map(point => point.time), values = points.map(p => valueOf(p.row)).filter(value => value !== null).map(Number);
  const left = Math.min(...times), right = Math.max(...times), low = percentage ? 0 : Math.min(...values), high = percentage ? 100 : Math.max(...values);
  const x = time => 80 + (time - left) / (right - left || 1) * 850;
  const y = value => high === low ? 95 : 155 - (value - low) / (high - low) * 115;
  for (const [start, end] of gaps) shape("rect", {x: x(start), y: 20, width: x(end) - x(start), height: 160, class: "gap"}, "Unobserved sampling gap; no values inferred");
  shape("line", {x1: 80, x2: 930, y1: 180, y2: 180, class: "axis"});
  if (values.length) {
    shape("text", {x: 4, y: 43}).textContent = percentage ? "100.00%" : compact.format(high);
    shape("text", {x: 4, y: 158}).textContent = percentage ? "0.00%" : compact.format(low);
  }
  if (percentage) for (const point of levelBreaks) shape("line", {x1:x(point.time),x2:x(point.time),y1:20,y2:180,class:"level-break"}, "Visual level changed; no continuity or automatic level-up is inferred");
  for (const point of points) {
    const row = point.row, px = x(point.time);
    const value = valueOf(row);
    const label = `#${row.index ?? "?"} ${displayTime(row)} · ${row.status} · visual level ${row.visual_level ?? "unavailable"}`;
    const detail = value === null ? label : `${label} · UNVERIFIED ${percentage ? value+"%" : exactExp(value)+" EXP"}`;
    if (value !== null) {
      const py = y(Number(value));
      if (row.fresh_at_capture && row.timestamp_ordered !== false && (row.status === "diagnostic_pair" || percentage && row.percentage_only_candidate && ["diagnostic_percentage_only", "malformed_or_unavailable"].includes(row.status)))
        shape("circle", {cx: px, cy: py, r: 4, class: "sample"}, detail);
      else shape("path", {d: `M${px} ${py-5}l5 5-5 5-5-5Z`, class: "stale"}, detail);
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
  if (snapshot?.storage === "sqlite_diagnostics") {
    const latest = snapshot.latest_reading;
    const age = latest ? latest.age_seconds + (performance.now() - receivedAt) / 1000 : null;
    document.getElementById("candidate-age").textContent = age == null ? "No complete diagnostic values in this session" :
      `Candidate ${Math.floor(age)}s old · ${latest.stale || age > snapshot.stale_after_seconds ? "STALE" : "local age only"} · broadcast freshness unknown`;
  }
  document.getElementById("notice").textContent = notices.join(" · ") || "Read-only UNVERIFIED diagnostics · local delivery does not prove source freshness";
}
function render() {
  const rows = snapshot?.observations || [];
  const persisted = snapshot?.storage === "sqlite_diagnostics";
  document.getElementById("persisted").hidden = !persisted;
  if (persisted) {
    document.getElementById("page-title").textContent = "Local streamer dashboard";
    document.getElementById("assignment").textContent = snapshot.selected_character?.label ?? "Select a character using the tracking CLI";
    document.getElementById("session").textContent = snapshot.session ?
      `${snapshot.selected_character.label} · session ${snapshot.session.id} · started ${snapshot.session.started_at}` : "Start a session using the tracking CLI";
    const latest = snapshot.latest_reading?.observation;
    document.getElementById("latest-candidate").textContent = latest?.candidate ?
      `UNVERIFIED candidate: ${exactExp(latest.candidate.exp)} EXP [${latest.candidate.percentage}%]` : latest?.percentage_only_candidate ?
      `UNVERIFIED candidate: ${latest.percentage_only_candidate.percentage}% · percentage only · absolute EXP unavailable` : "Waiting for complete diagnostic values";
    const trusted = snapshot.trusted_state;
    document.getElementById("trusted-summary").textContent = snapshot.session && trusted?.last_trusted?.session_id === snapshot.session.id ?
      `Separate trusted engine: ${exactExp(trusted.observed_session_exp)} counted session EXP. Shadow candidates do not contribute.` :
      "Trusted session totals unavailable · no trusted session observations. These diagnostic candidates do not count EXP gains.";
    const last = rows.at(-1), holder = document.getElementById("latest-grammar");
    const card = !last?.candidate && !last?.percentage_only_candidate ? grammarCard(last?.grammar_recovery) : null;
    holder.hidden = !card;
    holder.replaceChildren(...(card ? [element("small", "Last attempt's text hypothesis; timestamp/age shown above"), card] : []));
  }
  document.getElementById("channel").textContent = snapshot?.mixed_channels ? "Mixed sources — see rows" : snapshot?.channel ? `ttv/${snapshot.channel}` : "Local video / channel unavailable";
  document.getElementById("source-status").textContent = snapshot?.source_status || "Waiting for diagnostics";
  document.getElementById("run-status").textContent = `Run: ${snapshot?.run_status || "waiting"} · UNVERIFIED`;
  document.getElementById("count").textContent = `(${rows.length} · UNVERIFIED)`;
  document.getElementById("empty").hidden = rows.length > 0;
  const entries = rows.map(row => {
    const tr = element("tr");
    tr.dataset.status = row.status;
    if ((!row.candidate && !row.percentage_only_candidate) || !row.fresh_at_capture) tr.className = "rejected-row";
    const when = element("td", `#${row.index ?? "—"}`);
    when.append(element("small", displayTime(row)), element("small", row.channel ? `ttv/${row.channel}` : "Source unspecified"));
    const status = element("td", row.status);
    status.append(element("small", `Neural: ${row.neural_status ?? "not available"}`), element("small", row.fresh_at_capture ? "Fresh at local capture" : "Not fresh / unavailable at capture"), element("small", "UNVERIFIED"));
    const value = element("td");
    value.append(element("code", row.raw_text_redacted ? "[Non-numeric diagnostic text redacted]" : row.raw_text ?? "—"),
      element("span", row.candidate ? `${exactExp(row.candidate.exp)} EXP [${row.candidate.percentage}%]` : row.percentage_only_candidate ? `${row.percentage_only_candidate.percentage}% · percentage only · EXP unavailable` : "No complete saved pair"));
    if (row.percentage_only_origin === "legacy_raw_parse") value.append(element("small", "Percentage-only syntax parsed for display from legacy raw text"));
    if (row.partial_percentage_evidence) value.append(element("small", `Partial only: ${row.partial_percentage_evidence.percentage}% · not a complete observation`));
    if (!row.candidate && !row.percentage_only_candidate) {
      const card = grammarCard(row.grammar_recovery);
      if (card) value.append(card);
      else if (row.grammar_recovery) value.append(element("small", `Grammar: ${row.grammar_recovery.classification} · ${row.grammar_recovery.reason}`));
    }
    const visual = element("td", row.visual_level ?? "—");
    visual.append(element("small", `Tesseract (UNVERIFIED): ${row.visual_status ?? "unavailable"}`));
    if (row.visual_attempts?.length) visual.append(element("small", `Raw passes: ${row.visual_attempts.map(text => text ?? "[redacted]").join(" / ")}`));
    if (row.neural_level) {
      const neural=row.neural_level;
      visual.append(element("small", `RapidOCR EXPERIMENTAL / UNVERIFIED: ${neural.level ?? "unavailable"} · ${neural.status}`),
        element("small", `Neural raw: ${neural.text_redacted ? "[redacted]" : neural.text ?? "—"} · score ${neural.score ?? "unavailable"}`),
        element("small", `Level comparison: ${neural.comparison} · complete source level unverified`));
    }
    const evidence = element("td", row.relation ?? "Unavailable");
    evidence.append(element("small", row.reasons?.join(", ") || "No additional reason codes"));
    if (row.candidate_invalid) evidence.append(element("small", "Saved candidate invalid; not repaired"));
    if (row.percentage_only_invalid) evidence.append(element("small", "Percentage-only candidate contradicts raw syntax; not repaired"));
    if (row.timestamp_ordered === false) evidence.append(element("small", "Out-of-order source timestamp; not current evidence"));
    if (row.event_id) when.append(element("small", `ID ${row.event_id}`));
    tr.append(when, status, value, visual, element("td", levels(row.hypotheses?.nearest_half_up)), element("td", levels(row.hypotheses?.truncate)), evidence);
    return tr;
  });
  document.getElementById("readings").replaceChildren(...entries);
  drawTimeline(rows, snapshot?.interval_seconds);
  drawTimeline(rows, snapshot?.interval_seconds, true);
  renderStatus();
}
async function poll() {
  let controller, timer;
  try {
    if (document.hidden) return;
    controller = new AbortController();
    timer = setTimeout(() => controller.abort(), 5000);
    const response = await fetch(endpoint, {cache: "no-store", signal: controller.signal});
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

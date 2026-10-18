"use strict";
let snapshot = null, receivedAt = 0, requestError = false;
const nf = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", {notation: "compact", maximumFractionDigits: 1});
const svgNS = "http://www.w3.org/2000/svg";
const reason = code => (code ?? "unavailable").replaceAll("_"," ");
const dashboardChannel = /^\/dashboard\/([A-Za-z0-9_]{1,25})$/.exec(globalThis.location?.pathname ?? "")?.[1];
const endpoint = dashboardChannel ? `/dev/api/streams/${encodeURIComponent(dashboardChannel)}/diagnostics` : "/dev/api/shadow";
let historyQuery = dashboardChannel ? globalThis.location?.search || "" : "";
let pollTimer=null,activeController=null,pollSequence=0;
const operationLabels={running:"Capturing",waiting:"Waiting for next capture",capture_delayed:"Capture delayed",capture_failing:"Capture failing",stopped:"Coordinator stopped",coordinator_stopped:"Coordinator stopped",previous_unfinished_run:"Previous unfinished run · activity unknown",historical_session:"Historical session"};

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
function grammarCard(recovery, percentageOnly = false, raw = recovery?.raw) {
  if (recovery?.classification !== "unique_proposal" || recovery.proposals?.length !== 1) return null;
  const proposal = recovery.proposals[0], card = element("div");
  card.className = "grammar-proposal";
  card.append(element("small", "GRAMMAR-RECOVERED / EXPERIMENTAL / UNVERIFIED"),
    element("code", `${raw} → ${proposal.interpretation}`),
    element("small", percentageOnly ? `Recovered percentage: ${proposal.reading.percentage}% · Absolute EXP: unavailable` :
      `${exactExp(proposal.reading.exp)} EXP [${proposal.reading.percentage}%] · proposal only`),
    element("small", `Edits (zero-based): ${proposal.edits.map(e => `${e.index}: ${e.old} → ${e.new} (${e.category})`).join("; ")}`),
    element("small", "Source completeness and numeric digits unverified. No trusted accounting contribution; may qualify for separate experimental percentage progress."));
  return card;
}
function grammarCards(row) {
  const full = row?.interpretations?.full_exp ?? row?.grammar_recovery;
  const card = grammarCard(full, row?.exp_validity?.status==='invalid', row?.interpretations?.raw ?? full?.raw);
  const percentage = !card ? grammarCard(row?.interpretations?.percentage, true, row?.interpretations?.raw) : null;
  const selected = card || percentage;
  if (selected && row?.interpretations) selected.append(element("small", `Policy: ${row.interpretations.policy}${percentage ? ` · Full EXP withheld: ${full.reason}` : ""}`));
  return selected;
}
function chartValue(row, percentage) {
  if (!percentage && row.exp_validity?.status==='invalid') return {value:null};
  const strict = percentage ? row.candidate?.percentage ?? row.percentage_only_candidate?.percentage : row.candidate?.exp;
  if (strict != null) return {value: strict, kind: row.candidate ? "strict-full" : "strict-percentage"};
  if (!document.getElementById("show-recovered").checked) return {value: null};
  const field = percentage ? row.interpretations?.percentage : row.interpretations?.full_exp ?? row.grammar_recovery;
  if (field?.classification !== "unique_proposal" || field.proposals?.length !== 1) return {value: null};
  const reading = field.proposals[0].reading;
  return {value: percentage ? reading.percentage : reading.exp, kind: percentage ? "recovered-percentage" : "recovered-full"};
}
function renderCoverage() {
  const holder = document.getElementById("coverage"), counts = snapshot?.coverage;
  holder.hidden = !counts;
  if (!counts) return;
  document.getElementById("coverage-scope").textContent = `${counts.session_attempts} session attempts; counts below cover ${snapshot?.historical?'this page of':'the latest'} ${counts.summarized_attempts} (limit ${counts.history_limit}). Categories overlap; not an accuracy score.`;
  const labels = [["Acquired frames", "acquired_frames"], ["Unique HUDs", "unique_huds"],
    ["Original strict EXP pairs", "strict_full_pairs"], ["Additional full EXP proposals", "recovered_full_exp"],
    ["Original percentage-only", "strict_percentage_only"], ["Recovered percentages (overlap)", "recovered_percentages"],
    ["Percentage recovery without full", "percentage_recovery_without_full"], ["Unrecoverable / unavailable", "unrecoverable"],
    ["Malformed / missing strict values", "malformed_or_missing_strict"],
    ["Ambiguous grammar", "ambiguous"], ["Unavailable Tesseract levels", "visual_level_unavailable"],
    ["Unavailable neural levels", "neural_level_unavailable"], ["Visual / neural conflicts", "level_conflicts"]];
  document.getElementById("coverage-counts").replaceChildren(...labels.map(([label, key]) => {
    const cell = element("div"); cell.append(element("dt", label), element("dd", String(counts[key]))); return cell;
  }));
  document.getElementById("coverage-unknown").textContent = `Acquisition evidence unknown: ${counts.acquisition_unknown}; HUD-count evidence unknown: ${counts.hud_unknown}. A unique HUD does not verify character identity.`;
}
function timelineData(rows, interval) {
  const points = rows.map((row, position) => ({row, position, time: timeOf(row)})).filter(point => point.time !== null);
  const gaps = [];
  for (let i = 1; i < points.length; i++) {
    const previous = points[i - 1], point = points[i];
    const cadence = previous.row.interval_seconds ?? interval;
    if (cadence && point.time - previous.time > cadence * 1500) gaps.push([previous.time, point.time]);
  }
  return {points, gaps, missingTimes: rows.length - points.length};
}
function drawTimeline(rows, interval, percentage = false) {
  const svg = document.getElementById(percentage ? "percentage-timeline" : "timeline");
  svg.replaceChildren();
  delete svg.dataset.start; delete svg.dataset.end;
  const missingTimes = rows.filter(row => timeOf(row) === null).length;
  const range = document.getElementById("chart-range").value || "5";
  const lastTime = Math.max(...rows.map(timeOf).filter(time => time !== null));
  if (range !== "all") rows = rows.filter(row => timeOf(row) !== null && timeOf(row) >= lastTime - Number(range)*60000);
  const {points, gaps} = timelineData(rows, interval);
  function shape(tag, attributes, title) {
    const node = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (title) { const label = document.createElementNS(svgNS, "title"); label.textContent = title; node.append(label); }
    svg.append(node);
    return node;
  }
  const chartLevel=row=>row.experimental_level?row.experimental_level.value:row.visual_level;
  const levelBreaks = points.filter((point, i) => i && chartLevel(point.row)!=null && chartLevel(points[i-1].row)!=null && chartLevel(point.row)!==chartLevel(points[i-1].row));
  const uncertainLevels=points.filter((point,i)=>i && (chartLevel(point.row)==null || chartLevel(points[i-1].row)==null));
  const cadences = [...new Set(points.map(p=>p.row.interval_seconds ?? interval).filter(n=>n))];
  const cadenceNote = cadences.length ? `Recorded cadence${cadences.length>1?"s":""}: ${cadences.join(" / ")}s.` : "Expected cadence unavailable.";
  document.getElementById(percentage ? "percentage-note" : "chart-note").textContent = `${range === 'all' ? 'All loaded history' : `Last ${range} min ending at latest loaded capture`} · ${points.length} timestamped attempts · ${gaps.length} sampling gaps · ${missingTimes} without usable timestamps in loaded history. The table retains every loaded attempt. ${cadenceNote}${percentage ? ` ${levelBreaks.length} observed visual-level changes; unknown levels do not establish continuity. Hover points for exact percentage and visual level.` : ""}`;
  if (!points.length) { shape("text", {x: 40, y: 105}).textContent = "Waiting for timestamped attempts"; return; }
  const valueOf = row => chartValue(row, percentage).value;
  const times = points.map(point => point.time), values = points.map(p => valueOf(p.row)).filter(value => value !== null).map(Number);
  const left = Math.min(...times), right = Math.max(...times);
  svg.dataset.start = new Date(left).toISOString(); svg.dataset.end = new Date(right).toISOString();
  let low = Math.min(...values), high = Math.max(...values);
  if (percentage && values.length) {
    const padding = Math.max(.01, (high-low)*.1);
    low = Math.max(0, low-padding); high = Math.min(100, high+padding);
  }
  const x = time => 80 + (time - left) / (right - left || 1) * 850;
  const y = value => high === low ? 95 : 155 - (value - low) / (high - low) * 115;
  for (const [start, end] of gaps) shape("rect", {x: x(start), y: 20, width: x(end) - x(start), height: 160, class: "gap"}, "Unobserved sampling gap; no values inferred");
  shape("line", {x1: 80, x2: 930, y1: 180, y2: 180, class: "axis"});
  if (values.length) {
    shape("text", {x: 4, y: 43}).textContent = percentage ? high.toFixed(2)+"%" : compact.format(high);
    shape("text", {x: 4, y: 158}).textContent = percentage ? low.toFixed(2)+"%" : compact.format(low);
  }
  if (percentage) for (const point of levelBreaks) shape("line", {x1:x(point.time),x2:x(point.time),y1:20,y2:180,class:"level-break"}, "Visual level changed; no continuity or automatic level-up is inferred");
  if (percentage) for (const point of uncertainLevels) shape('line',{x1:x(point.time),x2:x(point.time),y1:170,y2:180,class:'level-unknown'},'Visual level unavailable; same-level continuity unknown');
  for (const point of points) {
    const row = point.row, px = x(point.time);
    const value = valueOf(row);
    const label = `#${row.index ?? "?"} ${displayTime(row)} · ${row.status} · experimental level ${chartLevel(row) ?? "unavailable"} · raw visual level ${row.visual_level ?? "unavailable"} (Tesseract)`;
    const kind = chartValue(row, percentage).kind;
    const detail = value === null ? label : `${label} · ${kind} · UNVERIFIED ${percentage ? value+"%" : exactExp(value)+" EXP"} · ${row.event_id ?? "no event ID"}`;
    if (value !== null) {
      const py = y(Number(value));
      const fresh = row.fresh_at_capture && row.timestamp_ordered !== false;
      if (kind?.startsWith("recovered")) {
        shape("path", {d: kind === "recovered-full" ? `M${px} ${py-6}l6 11h-12Z` : `M${px} ${py-6}l6 6-6 6-6-6Z`,
          class: kind, "data-stale": String(!fresh), "data-event-id": row.event_id ?? ""}, detail + (fresh ? "" : " · NOT FRESH"));
        shape("path", {d: `M${px-4} 168l8 8m0-8-8 8`, class: "rejected"}, label + " · Original strict value unavailable; hollow point is the same attempt's hypothesis");
      }
      else if (fresh && (row.status === "diagnostic_pair" || percentage && row.percentage_only_candidate && ["diagnostic_percentage_only", "malformed_or_unavailable"].includes(row.status))) {
        if (kind === "strict-percentage") shape("rect", {x: px-4, y: py-4, width:8, height:8, class:"sample", "data-kind":kind}, detail);
        else shape("circle", {cx: px, cy: py, r: 4, class: "sample", "data-kind":kind}, detail);
      }
      else shape("path", {d: `M${px} ${py-5}l5 5-5 5-5-5Z`, class: "stale"}, detail);
    } else shape("path", {d: `M${px-4} 168l8 8m0-8-8 8`, class: "rejected"}, label);
  }
  for (let i=0;i<5;i++) {
    const time=left+(right-left)*i/4;
    shape("text", {x:x(time),y:211,"text-anchor":i===0?'start':i===4?'end':'middle'}).textContent = new Date(time).toISOString().slice(11,19)+(i===4?' UTC':'');
  }
}
function renderStatus() {
  const age = snapshot?.age_seconds == null ? null : snapshot.age_seconds + (performance.now() - receivedAt) / 1000;
  const delayed = snapshot?.stale || age > (snapshot?.stale_after_seconds ?? 45);
  document.getElementById("age").textContent = age == null ? "No reading time" : `${Math.floor(age)}s ago${delayed ? " · OLD LOG" : " · local age only"}`;
  if(snapshot?.historical) document.getElementById('age').textContent=`Archived · ${displayTime(snapshot.observations.at(-1) ?? {})}`;
  const notices = [];
  if (requestError) notices.push("Viewer disconnected · showing cached UNVERIFIED diagnostics");
  if (snapshot?.log_status === "missing") notices.push("Configured log not found yet; waiting for the capture writer");
  if (snapshot?.log_status === "unavailable") notices.push("Configured diagnostic file unavailable");
  if (snapshot?.incomplete_tail) notices.push("Trailing write incomplete; only completed lines shown");
  if (snapshot?.malformed_lines) notices.push(`${snapshot.malformed_lines} malformed lines; no repair attempted`);
  if (snapshot?.truncated) notices.push(snapshot.storage==='sqlite_diagnostics'?"Bounded page; earlier attempts available":"Bounded recent history only; earlier content omitted");
  if(snapshot?.historical) notices.push('Historical selection · original timestamps · no current pace');
  if (delayed && !snapshot?.historical) notices.push("Updates old/delayed; capture activity is not established");
  if (snapshot?.storage === "sqlite_diagnostics") {
    const latest = snapshot.latest_reading;
    const age = latest ? latest.age_seconds + (performance.now() - receivedAt) / 1000 : null;
    document.getElementById("candidate-age").textContent = age == null ? "No complete diagnostic values in this session" :
      `Candidate ${Math.floor(age)}s old · ${latest.stale || age > snapshot.stale_after_seconds ? "STALE" : "local age only"} · broadcast freshness unknown`;
    if(snapshot.historical && latest) document.getElementById('candidate-age').textContent=`Historical reading · ${displayTime(latest.observation)} · UNVERIFIED`;
  }
  document.getElementById("notice").textContent = notices.join(" · ") || "Read-only UNVERIFIED diagnostics · local delivery does not prove source freshness";
  const runLabel=requestError && snapshot?.run_status==="active" ? "previously active; current activity unknown" : snapshot?.run_status || "waiting";
  document.getElementById("run-status").textContent = `Run: ${runLabel} · UNVERIFIED${snapshot?.unfinished_run_count ? ` · ${snapshot.unfinished_run_count} unfinished database run(s); activity established only when marked active` : ""}`;
  if(snapshot?.operation) document.getElementById("run-status").textContent=
    `${requestError?"Capture activity unknown · cached values":operationLabels[snapshot.operation.state] ?? "Activity unknown"} · Run: ${runLabel}`;
  if(snapshot?.operation) document.getElementById('source-status').textContent=requestError?'Capture activity unknown':operationLabels[snapshot.operation.state] ?? 'Activity unknown';
  renderProgress();
}
function renderProgress() {
  const data = snapshot?.percentage_progress, holder = document.getElementById("experimental-progress");
  holder.hidden = !data;
  if (!data) return;
  const elapsed = (performance.now()-receivedAt)/1000;
  const stale = data.stale || data.age_seconds == null || data.age_seconds+elapsed>snapshot.stale_after_seconds;
  const point = data.latest_percentage, movement = data.latest_movement, segment = data.current_segment;
  const label = kind => ({strict_full:"original strict full EXP",strict_percentage_only:"original percentage-only",grammar_recovered:"grammar-recovered proposal"}[kind] ?? "unavailable");
  document.getElementById("progress-latest").textContent = point ?
    `Last displayed percentage: ${point.percentage}% · ${label(point.evidence)} · ${Math.floor((data.age_seconds ?? 0)+elapsed)}s old${stale?" · STALE":" · local age only"}` : "No usable percentage in recent history";
  document.getElementById("progress-movement").textContent = movement?.difference_bp != null ?
    `Last displayed movement: ${movement.difference_bp>0?"+":""}${movement.difference_percentage_points} percentage points${movement.change==="negative"?" · segment ended; no level-up inferred":" · UNVERIFIED"}` :
    `Comparable movement unavailable: ${reason(movement?.reason ?? data.reason)}`;
  document.getElementById("progress-segment").textContent = segment ?
    `Recent segment: ${segment.start_percentage}% → ${segment.end_percentage}% · ${segment.readings} attempts / ${segment.span_seconds.approximate.toFixed(3)}s · visual level ${segment.level}. Strict full ${segment.evidence_counts.strict_full}, strict percentage-only ${segment.evidence_counts.strict_percentage_only}, recovered ${segment.evidence_counts.grammar_recovered}. No missing intermediate attempts.` :
    `No current eligible segment: ${reason(data.reason)}. Individual percentage points remain visible.`;
  const pace = !snapshot?.historical && !stale && !requestError ? data.current_pace : null;
  document.getElementById("progress-pace").textContent = pace ?
    `EXPERIMENTAL / UNVERIFIED recent pace: ${pace.value.approximate.toFixed(2)} percentage points/hour` :
    `Percentage pace unavailable: ${requestError?"viewer disconnected":stale?"updates old/stopped":reason(segment?.pace_reason ?? data.reason)} (requires ≥3 comparable readings spanning ≥30s)`;
  document.getElementById("progress-bounds").textContent = pace ? ["nearest_half_up","truncation"].map(rule=>
    `${reason(rule)}: ${pace[rule].lower.approximate.toFixed(3)} to ${pace[rule].upper.approximate.toFixed(3)} pp/hour`).join(" · ")+" · outer display-precision bounds; neither rule selected" : "";
  const estimate = !stale && !requestError ? segment?.estimated_exp : null;
  document.getElementById("progress-exp").textContent = estimate ?
    `UNVERIFIED estimated EXP range · community-provisional requirement ${nf.format(segment.requirement.to_next)}: `+
      Object.entries(estimate.hypotheses).map(([rule,bounds])=>`${reason(rule)} ~ ${bounds.lower.approximate.toFixed(1)} to ${bounds.upper.approximate.toFixed(1)} EXP`).join(" · ")+". Not an earned-EXP total." :
    `Estimated EXP unavailable: ${stale?"stale observations":reason(segment?.requirement?.status ?? "stable visual level required")}. Percentages are never converted to absolute current EXP.`;
  const historical = (data.segments ?? []).filter(s=>s.pace).at(-1);
  document.getElementById("progress-history").textContent = historical && (!pace || historical.last_event_id!==segment?.last_event_id) ?
    `Historical qualifying segment (not current): ${historical.difference_percentage_points} pp over ${historical.span_seconds.approximate.toFixed(3)}s / ${historical.readings} attempts; strict ${historical.evidence_counts.strict_full+historical.evidence_counts.strict_percentage_only}, recovered ${historical.evidence_counts.grammar_recovered}. Recorded pace ${historical.pace.value.approximate.toFixed(2)} pp/hour · EXPERIMENTAL / UNVERIFIED · ended ${historical.end}` : "";
  document.getElementById("progress-segments").replaceChildren(...(data.segments ?? []).map(s=>{
    const p=element('p',`${s.start} → ${s.end}: ${s.start_percentage}% → ${s.end_percentage}% (${s.difference_percentage_points} pp), level ${s.level}, ${s.readings} readings. ${s.pace?`Historical/experimental pace ${s.pace.value.approximate.toFixed(2)} pp/hour`:reason(s.pace_reason)}.`);
    if(s.end_reason) p.append(element('small',`Boundary: ${reason(s.end_reason)}`));
    if(s.estimated_exp) p.append(element('small',`Historical UNVERIFIED estimated EXP ranges (${s.requirement.status}): `+
      Object.entries(s.estimated_exp.hypotheses).map(([rule,bounds])=>`${reason(rule)} ${bounds.lower.approximate.toFixed(1)} to ${bounds.upper.approximate.toFixed(1)}`).join(' · ')+'. Display quantization only; not earned totals.'));
    return p;
  }));
}
function render() {
  const rows = snapshot?.observations || [];
  const persisted = snapshot?.storage === "sqlite_diagnostics";
  document.getElementById("directory-link").hidden = !persisted;
  document.getElementById("player-link").hidden = !persisted;
  if(persisted) document.getElementById("player-link").href=`/stream/${encodeURIComponent(snapshot.channel)}`;
  document.getElementById("persisted").hidden = !persisted;
  document.getElementById("history-controls").hidden=!persisted;
  document.getElementById("older-attempts").disabled=!snapshot?.history?.next_before;
  if(persisted) document.getElementById("history-note").textContent=
    `${snapshot.historical?"ARCHIVED selection · historical pace only":"Current session · latest page"} · ${rows.length} attempts${snapshot.truncated?" · earlier attempts available":""}. Original UTC timestamps; no interpolation or retiming.`;
  if (persisted) {
    document.getElementById("page-title").textContent = snapshot.historical ? "Streamer history" : "Local streamer dashboard";
    document.getElementById("assignment").textContent = snapshot.selected_character?.label ?? "Select a character using the tracking CLI";
    document.getElementById("session").textContent = snapshot.session ?
      `${snapshot.selected_character.label} · session ${snapshot.session.id} · started ${snapshot.session.started_at}` : "Start a session using the tracking CLI";
    const latest = snapshot.latest_reading?.observation;
    document.getElementById("latest-candidate").textContent = latest?.candidate && latest.exp_validity?.status==='invalid' ?
      `Full EXP withheld: inconsistent with provisional level/percentage under both hypotheses. Original percentage: ${latest.candidate.percentage}% (UNVERIFIED).` : latest?.candidate ?
      `UNVERIFIED candidate: ${exactExp(latest.candidate.exp)} EXP [${latest.candidate.percentage}%]` : latest?.percentage_only_candidate ?
      `UNVERIFIED candidate: ${latest.percentage_only_candidate.percentage}% · percentage only · absolute EXP unavailable` : "Waiting for complete diagnostic values";
    const trusted = snapshot.trusted_state;
    document.getElementById("trusted-summary").textContent = snapshot.session && trusted?.last_trusted?.session_id === snapshot.session.id ?
      `Separate trusted engine: ${exactExp(trusted.observed_session_exp)} counted session EXP. Shadow candidates do not contribute.` :
      "Trusted session totals unavailable · no trusted session observations. These diagnostic candidates do not count EXP gains.";
    const last = rows.at(-1), holder = document.getElementById("latest-grammar");
    const card = !last?.candidate && !last?.percentage_only_candidate ? grammarCards(last) : null;
    holder.hidden = !card;
    holder.replaceChildren(...(card ? [element("small", "Last attempt's text hypothesis; timestamp/age shown above"), card] : []));
  }
  document.getElementById("channel").textContent = snapshot?.mixed_channels ? "Mixed sources — see rows" : snapshot?.channel ? `${snapshot.source_kind==='file'?'Local video · ':snapshot.source_kind==='twitch'?'ttv/':''}${snapshot.channel}` : "Local video / channel unavailable";
  document.getElementById("source-status").textContent = snapshot?.source_status || "Waiting for diagnostics";
  document.getElementById("run-status").textContent = `Run: ${snapshot?.run_status || "waiting"} · UNVERIFIED${snapshot?.unfinished_run_count ? ` · ${snapshot.unfinished_run_count} unfinished database run(s); activity established only when marked active` : ""}`;
  document.getElementById("count").textContent = `(${rows.length} · UNVERIFIED)`;
  document.getElementById("empty").hidden = rows.length > 0;
  renderCoverage();
  const entries = rows.map(row => {
    const tr = element("tr");
    tr.dataset.status = row.status;
    if ((!row.candidate && !row.percentage_only_candidate) || !row.fresh_at_capture) tr.className = "rejected-row";
    const when = element("td", `#${row.index ?? "—"}`);
    when.append(element("small", displayTime(row)), element("small", row.channel ? `ttv/${row.channel}` : "Source unspecified"));
    if(row.actual_interval_seconds!=null) when.append(element('small',`Actual interval ${row.actual_interval_seconds.toFixed(2)}s / requested ${row.interval_seconds}s · skipped ${row.skipped_deadlines ?? 0}`));
    if(row.coordinator_attempt_seconds!=null) when.append(element('small',`Capture + OCR ${row.coordinator_attempt_seconds.toFixed(2)}s · scheduling delay ${row.scheduler_delay_seconds?.toFixed(2) ?? 'unknown'}s${row.timing_mode==='simulated'?' · SIMULATED':''}`));
    const status = element("td", row.status);
    status.append(element("small", `Neural: ${row.neural_status ?? "not available"}`), element("small", row.fresh_at_capture ? "Fresh at local capture" : "Not fresh / unavailable at capture"), element("small", "UNVERIFIED"));
    const value = element("td");
    value.append(element("code", row.raw_text_redacted ? "[Non-numeric diagnostic text redacted]" : row.raw_text ?? "—"),
      element("span", row.candidate ? `${row.exp_validity?.status==='invalid'?'WITHHELD original saved pair: ':''}${exactExp(row.candidate.exp)} EXP [${row.candidate.percentage}%]` : row.percentage_only_candidate ? `${row.percentage_only_candidate.percentage}% · percentage only · EXP unavailable` : "No complete saved pair"));
    if(row.exp_validity) value.append(element('small',`Read-time full EXP: ${row.exp_validity.status} · ${reason(row.exp_validity.reason)}. Percentage retained independently; arithmetic agreement does not verify digits.`));
    if (row.percentage_only_origin === "legacy_raw_parse") value.append(element("small", "Percentage-only syntax parsed for display from legacy raw text"));
    if (row.partial_percentage_evidence) value.append(element("small", `Partial only: ${row.partial_percentage_evidence.percentage}% · not a complete observation`));
    if (!row.candidate && !row.percentage_only_candidate) {
      const card = grammarCards(row);
      if (card) value.append(card);
      else if (row.interpretations) value.append(element("small", `Grammar ${row.interpretations.policy}: ${["full_exp", "percentage"].map(field => `${field}: ${row.interpretations[field].classification} · ${row.interpretations[field].reason}`).join("; ")}`));
      else if (row.grammar_recovery) value.append(element("small", `Grammar: ${row.grammar_recovery.classification} · ${row.grammar_recovery.reason}`));
    }
    const visual = element("td", row.visual_level ?? "—");
    if(row.experimental_level) visual.append(element('strong',`Experimental level: ${row.experimental_level.value ?? '—'} · ${row.experimental_level.status}`),
      element('small',`${row.experimental_level.policy}: ${reason(row.experimental_level.reason)} · neural score ${row.experimental_level.neural_score ?? 'unavailable'} · raw readers below`));
    if(row.experimental_level?.context_hypothesis) {
      const context=row.experimental_level.context_hypothesis;
      visual.append(element('small',`Recent level hypothesis ${context.value}: ${context.samples} supported samples; ${context.age_seconds.toFixed(1)}s old, expires after ${context.expires_after_seconds}s. Original reader decision: ${reason(row.experimental_level.reader_evidence?.reason ?? row.experimental_level.reason)}`));
    }
    for(const hypothesis of row.interpretations?.symbol_hypotheses ?? [])
      value.append(element('small',row.conditional_percent?
        `${row.conditional_percent.policy}: ${row.conditional_percent.status} · ${reason(row.conditional_percent.reason)} · ${hypothesis.interpretation} · untrusted; original strict evidence unchanged`:
        `Review only: ${hypothesis.interpretation} · missing % symbol; excluded from observations and pace`));
    visual.append(element("small", `Tesseract (UNVERIFIED): ${row.visual_status ?? "unavailable"}`));
    if (row.visual_attempts?.length) visual.append(element("small", `Raw passes: ${row.visual_attempts.map(text => text ?? "[redacted]").join(" / ")}`));
    if (row.neural_level) {
      const neural=row.neural_level;
      visual.append(element("small", `RapidOCR EXPERIMENTAL / UNVERIFIED: ${neural.level ?? "unavailable"} · ${neural.status}`),
        element("small", `Neural raw: ${neural.text_redacted ? "[redacted]" : neural.text ?? "—"} · score ${neural.score ?? "unavailable"}`),
        element("small", `Level comparison: ${neural.comparison} · complete source level unverified`));
    }
    if (row.requirements) {
      const req = row.requirements.visual;
      visual.append(element("small", `Current community table (${req.version}): ${req.status}${req.to_next == null ? " · no selected requirement" : ` · ${exactExp(req.to_next)} EXP to next`}`));
      if (Object.keys(req.published_alternatives).length) visual.append(element("small", `Disputed publications: ${Object.entries(req.published_alternatives).map(([site, n]) => `${site}: ${exactExp(n)}`).join(" / ")}`));
    }
    const evidence = element("td", row.relation ?? "Unavailable");
    if(row.percentage_review) evidence.append(element('strong',`Percentage: ${reason(row.percentage_review.status)}`),
      element('small',`${row.percentage_review.policy}: ${reason(row.percentage_review.reason)}${row.percentage_review.resolution?' · '+reason(row.percentage_review.resolution):''}${row.percentage_review.resolves_event_id?' · resolves '+row.percentage_review.resolves_event_id:''}. Public ${row.percentage_review.public_eligible?'eligible':'WITHHELD'}.`));
    if(row.crop_suspect)evidence.append(element('small','Known vertical crop displacement; cannot corroborate a loss baseline'));
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
  clearTimeout(pollTimer);activeController?.abort();
  const sequence=++pollSequence;
  let controller, timer;
  try {
    if (document.hidden) return;
    controller = new AbortController();
    activeController=controller;
    timer = setTimeout(() => controller.abort(), 5000);
    const selection=historyQuery;
    const response = await fetch(endpoint+selection, {cache: "no-store", signal: controller.signal});
    if (!response.ok) throw new Error("Viewer unavailable");
    const data=await response.json();
    if(sequence!==pollSequence || selection!==historyQuery) return;
    snapshot = data;
    receivedAt = performance.now();
    requestError = false;
    render();
  } catch {
    if(sequence===pollSequence) { requestError = true;renderStatus(); }
  } finally {
    clearTimeout(timer);
    if(sequence===pollSequence) pollTimer=setTimeout(poll, document.hidden ? 10000 : 2000);
  }
}
poll();
setInterval(renderStatus, 1000);
document.getElementById("show-recovered").addEventListener("change", () => {
  drawTimeline(snapshot?.observations || [], snapshot?.interval_seconds);
  drawTimeline(snapshot?.observations || [], snapshot?.interval_seconds, true);
});
document.getElementById("chart-range").addEventListener("change", () => {
  drawTimeline(snapshot?.observations || [], snapshot?.interval_seconds);
  drawTimeline(snapshot?.observations || [], snapshot?.interval_seconds, true);
});

let sessionCursor=null,runCursor=null;
async function loadHistory(kind,older=false) {
  if(!dashboardChannel) return;
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),5000);
  try {
    const params=new URLSearchParams();
    if(kind==='runs') params.set('session',document.getElementById('history-session').value || snapshot?.session?.id || '');
    const cursor=kind==='runs'?runCursor:sessionCursor;
    if(older && cursor) params.set('before',cursor);
    const response=await fetch(`/dev/api/streams/${encodeURIComponent(dashboardChannel)}/${kind}?${params}`,{cache:'no-store',signal:controller.signal});
    if(!response.ok) throw new Error();
    const data=await response.json(), select=document.getElementById(kind==='runs'?'history-run':'history-session');
    if(!older) { const option=element('option',kind==='runs'?'All runs in session':'Current session');option.value='';select.replaceChildren(option); }
    for(const item of data[kind]) {
      const option=element('option',kind==='runs'?`${item.created_at} · ${item.status} · ${item.attempts} attempts · ${item.run_id.slice(0,8)}`:
        `${item.label} · session ${item.id} · ${item.started_at}${item.ended_at?' · closed':' · open'}`);
      option.value=String(kind==='runs'?item.run_id:item.id);select.append(option);
    }
    if(kind==='runs') runCursor=data.next_before;else sessionCursor=data.next_before;
    document.getElementById(kind==='runs'?'more-runs':'more-sessions').hidden=!data.next_before;
  } catch { document.getElementById('history-note').textContent='History list unavailable; saved selection remains unchanged.'; }
  finally { clearTimeout(timer); }
}
function selectHistory(params) {
  historyQuery=params.toString()?`?${params}`:'';
  globalThis.history?.replaceState(null,'',globalThis.location.pathname+historyQuery);
  snapshot=null;render();poll();
}
document.getElementById('browse-history').addEventListener('click',()=>loadHistory('sessions'));
document.getElementById('more-sessions').addEventListener('click',()=>loadHistory('sessions',true));
document.getElementById('history-session').addEventListener('change',()=>loadHistory('runs'));
document.getElementById('more-runs').addEventListener('click',()=>loadHistory('runs',true));
document.getElementById('apply-history').addEventListener('click',()=>{
  const params=new URLSearchParams();
  for(const [id,key] of [['history-session','session'],['history-run','run'],['history-start','start'],['history-end','end']]) {
    let value=document.getElementById(id).value;
    if(value) { if(key==='start'||key==='end') value+='Z'; params.set(key,value); }
  }
  selectHistory(params);
});
document.getElementById('older-attempts').addEventListener('click',()=>{
  if(!snapshot?.history?.next_before) return;
  const params=new URLSearchParams(historyQuery);params.set('before',snapshot.history.next_before);
  if(snapshot.session) params.set('session',snapshot.session.id);
  selectHistory(params);
});
document.getElementById('current-history').addEventListener('click',()=>selectHistory(new URLSearchParams()));

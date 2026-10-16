"use strict";

const channel = decodeURIComponent(location.pathname.split("/")[2]).toLowerCase();
const elements = Object.fromEntries(["card", "character", "status", "level", "exp", "percentage",
  "progress", "session-exp", "age"].map(id => [id, document.getElementById(id)]));
const number = new Intl.NumberFormat("en-US");
let snapshot = null;
let receivedAt = 0;
let requestError = null;

function render() {
  const state = snapshot;
  const last = state?.last_trusted;
  const age = last ? state.age_seconds + (performance.now() - receivedAt) / 1000 : null;
  const stale = !last || state.stale || age > state.stale_after_seconds;
  const phase = state?.status || "waiting";
  let label = "";
  if (!requestError && phase === "offline") label = "Offline";
  else if (!last) label = "Waiting for EXP";
  else if (requestError) label = "Updates delayed";
  else if (!state.session || (phase === "paused" && state.continuity_broken && state.reason !== "stale")) label = "Paused";
  else if (phase === "waiting" || last.session_id !== state.session.id) label = "Waiting for EXP";
  else if (stale || phase === "ambiguous") label = "Updates delayed";

  elements.card.dataset.state = phase;
  elements.card.dataset.stale = String(stale);
  elements.character.textContent = state?.selected_character?.label || channel;
  elements.character.title = elements.character.textContent;
  elements.status.textContent = label;
  elements.level.textContent = last ? `Lv. ${last.level}` : "Lv. —";
  elements.exp.textContent = last ? number.format(last.current_exp) : "—";
  elements.percentage.textContent = last ? `${(last.percentage_bp / 100).toFixed(2)}%` : "—";
  elements.progress.value = last ? last.percentage_bp / 100 : 0;
  elements["session-exp"].textContent = state?.session ? `+${number.format(state.observed_session_exp)}` : "—";
  for (const id of ["exp", "session-exp"]) {
    const length = elements[id].textContent.length;
    elements[id].dataset.size = length > 16 ? "long" : length > 11 ? "medium" : "normal";
  }
  elements.age.textContent = last ? `Updated ${Math.floor(age)}s ago` : "";
  elements.age.dateTime = last?.observed_at || "";
  elements.age.title = last?.observed_at || "";
}

async function poll() {
  const requestedAt = performance.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch(`/api/streams/${encodeURIComponent(channel)}/state`, {cache: "no-store", signal: controller.signal});
    if (!response.ok) throw new Error(response.status === 404 ? "unknown_channel" : "api_unavailable");
    snapshot = await response.json();
    receivedAt = requestedAt; // Include request time conservatively in cached-value age.
    requestError = null;
  } catch (error) {
    requestError = error.message;
  } finally {
    clearTimeout(timeout);
    render();
    setTimeout(poll, 2000);
  }
}

render();
setInterval(render, 1000);
poll();

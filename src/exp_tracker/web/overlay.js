"use strict";

const channel = decodeURIComponent(location.pathname.split("/")[2]).toLowerCase();
const elements = Object.fromEntries(["card", "character", "channel", "status", "level", "exp", "percentage",
  "progress", "session-exp", "bridged", "detail", "age"].map(id => [id, document.getElementById(id)]));
const number = new Intl.NumberFormat("en-US");
let snapshot = null;
let receivedAt = 0;
let requestError = null;

function render() {
  const state = snapshot;
  const last = state?.last_trusted;
  const age = last ? state.age_seconds + (performance.now() - receivedAt) / 1000 : null;
  const stale = !last || state.stale || age > state.stale_after_seconds;
  let phase = state?.status || "waiting";
  let label = "Connecting";
  let detail = state?.reason?.replaceAll("_", " ") || "Waiting for local state";

  if (requestError) {
    phase = "disconnected";
    label = requestError === "unknown_channel" ? "Unknown channel" : "API unavailable";
    detail = last ? "Connection lost · showing cached trusted values" : "No local state available";
  } else if (state) {
    if (!state.selected_character || !state.session) {
      phase = state.selected_character ? "stopped" : "unconfigured";
      label = state.selected_character ? "No active session" : "Unconfigured";
    } else if (phase === "offline") {
      label = stale ? "Offline · stale" : "Offline";
    } else if (!last) {
      phase = phase === "paused" ? "paused" : "waiting";
      label = phase === "paused" ? (state.continuity_broken ? "Paused" : "OCR interrupted") : "Waiting for reading";
    } else if (phase === "ambiguous") {
      label = stale ? "Needs review · stale" : "Needs review";
    } else if (stale) {
      phase = "stale";
      label = "Stale";
    } else if (phase === "paused") {
      label = state.continuity_broken ? "Paused" : "OCR interrupted";
    } else if (phase === "waiting" || last.session_id !== state.session.id) {
      phase = "waiting";
      label = "Waiting for reading";
    } else {
      label = "Tracking";
    }
  }
  if (!requestError && last && state?.session && last.session_id !== state.session.id) {
    detail = "Showing previous session's trusted reading";
  }

  elements.card.dataset.state = phase;
  elements.card.dataset.stale = String(stale);
  elements.character.textContent = state?.selected_character?.label || channel;
  elements.channel.textContent = `twitch.tv/${state?.channel || channel}`;
  elements.status.textContent = label;
  elements.level.textContent = last ? `Lv. ${last.level}` : "Lv. —";
  elements.exp.textContent = last ? number.format(last.current_exp) : "—";
  elements.percentage.textContent = last ? `${(last.percentage_bp / 100).toFixed(2)}%` : "—";
  elements.progress.value = last ? last.percentage_bp / 100 : 0;
  elements["session-exp"].textContent = state?.session ? `+${number.format(state.observed_session_exp)}` : "—";
  elements.bridged.hidden = !state?.session || !state.bridged_session_exp;
  elements.bridged.textContent = state ? `Includes ${number.format(state.bridged_session_exp)} net EXP across missing observations` : "";
  elements.detail.textContent = detail;
  elements.detail.title = detail;
  elements.age.textContent = last ? `${stale ? "Stale · " : ""}Last trusted ${Math.floor(age)}s ago` : "No trusted reading";
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

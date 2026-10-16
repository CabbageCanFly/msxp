"use strict";

const channel = decodeURIComponent(location.pathname.split("/")[2]).toLowerCase();
const elements = Object.fromEntries(["card", "streamer", "character", "rank", "status", "level", "exp", "percentage",
  "progress", "recent-exp", "pace", "session-exp", "eta", "age"].map(id => [id, document.getElementById(id)]));
const number = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", {notation: "compact", maximumFractionDigits: 1});
let snapshot = null;
let receivedAt = 0;
let requestError = null;

function etaText(seconds) {
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `~${minutes}m`;
  if (minutes < 1440) return `~${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return `~${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h`;
}

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
  elements.streamer.textContent = `ttv/${state?.channel || channel}`;
  elements.streamer.title = elements.streamer.textContent;
  elements.character.textContent = state?.selected_character?.label || "—";
  elements.character.title = elements.character.textContent;
  const rank = state?.ranking;
  const ranked = rank?.authoritative === true && Number.isSafeInteger(rank.rank) && rank.rank > 0;
  elements.rank.hidden = !ranked;
  elements.rank.textContent = ranked ? `#${compact.format(rank.rank)}` : "";
  elements.rank.title = ranked ? `Leaderboard rank ${number.format(rank.rank)}` : "";
  elements.status.textContent = label;
  elements.level.textContent = last ? `Lv. ${last.level}` : "Lv. —";
  elements.exp.textContent = last ? number.format(last.current_exp) : "—";
  elements.percentage.textContent = last ? `${(last.percentage_bp / 100).toFixed(2)}%` : "—";
  elements.progress.value = last ? last.percentage_bp / 100 : 0;
  elements["session-exp"].textContent = state?.session ? `+${compact.format(state.observed_session_exp)}` : "—";
  elements["session-exp"].title = state?.session ? number.format(state.observed_session_exp) : "";
  const statistics = state?.statistics;
  const usable = !requestError && !stale && !!state?.session && !state.continuity_broken &&
    phase !== "offline" && phase !== "ambiguous" && last?.session_id === state.session.id;
  const recent = usable ? statistics?.last_5_min : null;
  const pace = usable ? statistics?.exp_per_hour_30m : null;
  const eta = usable ? statistics?.to_next_level : null;
  elements["recent-exp"].textContent = recent?.exp != null ? `${recent.boundary_trimmed ? "~" : "+"}${compact.format(recent.exp)}` : "—";
  elements.pace.textContent = pace?.exp_per_hour != null ? `~${compact.format(pace.exp_per_hour)}` : "—";
  elements.eta.textContent = eta?.seconds != null ? etaText(eta.seconds) : "—";
  for (const [id, window] of [["recent-exp", recent], ["pace", pace]]) {
    elements[id].title = window?.exp != null ? `${number.format(window.exp)} EXP across ${Math.round(window.covered_seconds)}s of updates in the last ${window.window_seconds / 60} min; no estimates for the edges` : "";
  }
  elements.eta.title = eta?.seconds != null ? "Approximate time from the last EXP reading at the recent same-level percentage pace" : "";
  for (const id of ["exp", "recent-exp", "pace", "session-exp", "eta"]) {
    const length = elements[id].textContent.length;
    elements[id].dataset.size = length > (id === "exp" ? 16 : 8) ? "long" : "normal";
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

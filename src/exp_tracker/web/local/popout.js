// /local/overlay: the active local character's progress, for OBS Window Capture.
// It never captures the screen. Updates arrive over BroadcastChannel; IndexedDB is the source of truth
// (initial state, missed messages and a slow poll while the tracker tab is in the background).
import * as store from './store.js';
import {CHANNEL, chartSvg, compact, duration, exp, percent, summarize} from './view.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const body = document.body;
// Options: ?layout=card|bar|rates  ?theme=night|day|red|green|blue|purple  ?bg=dark|green|magenta  ?window=5|15|30|60
const pick = (name, allowed, fallback) => allowed.includes(params.get(name)) ? params.get(name) : fallback;
body.dataset.layout = pick('layout', ['card', 'bar', 'rates'], 'card');
body.dataset.theme = pick('theme', ['night', 'day', 'red', 'green', 'blue', 'purple'], 'night');
body.dataset.bg = pick('bg', ['dark', 'green', 'magenta'], 'dark');
const window_ = Number(pick('window', ['5', '15', '30', '60'], '15'));

let table = null, character = null, readings = [], loading = null;

async function load() {
  const id = await store.getSetting('activeCharacterId');
  character = id == null ? null : await store.getCharacter(id) ?? null;
  readings = character ? await store.readings(character.id, Date.now() - 3 * 3600e3) : [];
  render();
}

function refresh() {
  // Coalesce bursts of messages into one database read.
  loading ??= load().catch(() => {}).finally(() => { loading = null; });
}

function render() {
  if (!table) return;
  const now = Date.now();
  if (!character) { $('character').textContent = 'Start tracking at msxp.pages.dev/local'; return; }
  const view = summarize(table, character, readings, now, window_);
  $('character').textContent = character.name;
  $('overlay-job').textContent = character.job || '';
  $('level').textContent = view.last ? `Lv. ${view.last.level}` : 'Lv. —';
  $('progress').value = view.progress;
  $('exp').textContent = view.last ? exp(view.last.exp) : '—';
  $('percentage').textContent = view.last ? percent(view.last.bp) : '—';
  $('movement').textContent = view.recent == null ? '—' : compact(view.recent);
  $('rate-label').textContent = view.early ? 'EXP/h · so far' : `EXP/h · ${window_} min`;
  $('rate').textContent = view.perHour == null ? '—' : compact(view.perHour);
  $('pp-rate').textContent = view.percentPerHour == null ? '—' : view.percentPerHour.toFixed(2) + '%';
  $('eta').textContent = view.eta == null ? '—' : duration(view.eta);
  for (const cell of document.querySelectorAll('[data-rate-window]')) cell.textContent = compact(view.rates[cell.dataset.rateWindow]);
  $('general-chart').innerHTML = chartSvg(view.buckets.slice(-24));
  // Old readings are shown as such, never as live progress.
  const stale = view.age == null || view.age > 120;
  $('status').hidden = !stale;
  $('status').textContent = view.last ? 'Not tracking right now' : 'Waiting for EXP';
  $('age').textContent = view.last && stale ? `last reading ${duration(view.age)} ago` : '';
}

async function init() {
  table = await (await fetch('/static/local/community-exp.json')).json();
  if ('BroadcastChannel' in window) new BroadcastChannel(CHANNEL).onmessage = (event) => { if (event.data?.type === 'update') refresh(); };
  await load();
  setInterval(refresh, 30e3);
  setInterval(render, 5e3);
}

init().catch((error) => { $('character').textContent = `Local history unavailable: ${error.message}`; });

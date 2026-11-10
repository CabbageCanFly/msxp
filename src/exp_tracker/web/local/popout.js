// /local/overlay: the active local character's progress, for OBS Window Capture. Same layouts, presets,
// colours and URL options as the live overlay (/live/overlay). It never captures the screen. Updates
// arrive over BroadcastChannel; IndexedDB is the source of truth (initial state, missed messages and a
// slow poll while the tracker tab is in the background).
import * as store from './store.js';
import {CHANNEL, OVERLAY_COLORS, THEME_COLORS, duration, exp, headerInk, historyLabel, overlayOptions, percent, summarize} from './view.js';
import {drawHourChart, expText} from './charts.js';

const $ = (id) => document.getElementById(id);
let table = null, character = null, readings = [], loading = null, options = overlayOptions(location.search);

// Also called by the builder's same-origin preview as options change.
function applyOverlay(o) {
  options = o;
  Object.assign(document.body.dataset, {layout: o.layout, theme: o.theme, name: o.name, icon: o.icon, job: o.job, bg: o.bg, interval: o.interval, range: o.range});
  document.body.dataset.headerInk = headerInk(o.header ?? THEME_COLORS[o.theme].header);
  document.body.dataset.panelInk = o.background ? headerInk(o.background) : '';
  $('general-history-caption').textContent = historyLabel(o);
  $('hour-caption').textContent = `EXP per ${Number(o.interval) / 60} min · ${historyLabel(o).split(' · ')[1]}`;
  for (const key of OVERLAY_COLORS) if (/^[0-9a-f]{6}$/.test(o[key] ?? '')) document.body.style.setProperty('--' + key, '#' + o[key]); else document.body.style.removeProperty('--' + key);
  $('overlay-brand').textContent = o.title === 'site' ? 'msxp.pages.dev' : 'EXP TRACKER';
  render();
}
window.applyOverlay = applyOverlay;

async function load() {
  const id = await store.getSetting('activeCharacterId');
  character = id == null ? null : await store.getCharacter(id) ?? null;
  readings = character ? await store.readings(character.id, Date.now() - 25 * 3600e3) : [];
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
  const fresh = character.last && now - character.last.at < 120e3;
  const view = summarize(table, character, readings, now, 15, {live: fresh});
  $('character').textContent = character.name;
  $('overlay-job').textContent = character.job || '';
  $('level').textContent = view.last ? `Lv. ${view.last.level}` : 'Lv. —';
  $('progress').value = view.progress;
  $('exp').textContent = view.last ? exp(view.last.exp) : '—';
  $('percentage').textContent = view.last ? percent(view.last.bp) : '—';
  $('movement').textContent = view.recent == null ? '—' : expText(view.recent);
  $('rate-label').textContent = view.early ? 'EXP/h · so far' : 'EXP / hour';
  $('rate').textContent = view.perHour == null ? '—' : expText(view.perHour);
  $('pp-rate').textContent = view.percentPerHour == null ? '—' : view.percentPerHour.toFixed(2) + '%';
  $('eta').textContent = view.eta == null ? '—' : duration(view.eta);
  for (const id of ['exp', 'movement', 'rate', 'pp-rate', 'eta']) $(id).dataset.size = $(id).textContent.length > (id === 'exp' ? 16 : 8) ? 'long' : 'normal';
  for (const cell of document.querySelectorAll('[data-rate-window]')) cell.textContent = expText(view.rates[cell.dataset.rateWindow]);
  const chart = {anchor: now, seconds: Number(options.interval), range: Number(options.range) * 60};
  drawHourChart($('general-chart'), view.allIntervals, {...chart, labelled: false});
  const total = drawHourChart($('overlay-chart'), view.allIntervals, {...chart, labelled: true});
  $('hour-total').textContent = total == null ? '—' : `${expText(total)} EXP`;
  // Old readings are shown as such, never as live progress.
  const stale = view.age == null || view.age > 120;
  $('status').hidden = !stale;
  $('status').textContent = view.last ? 'Not tracking right now' : 'Waiting for EXP';
  $('age').textContent = view.last && stale ? `Updated ${duration(view.age)} ago` : '';
}

async function init() {
  table = await (await fetch('/static/local/community-exp.json')).json();
  if ('BroadcastChannel' in window) new BroadcastChannel(CHANNEL).onmessage = (event) => { if (event.data?.type === 'update') refresh(); };
  applyOverlay(options);
  await load();
  setInterval(refresh, 30e3);
  setInterval(render, 5e3);
}

init().catch((error) => { $('character').textContent = `Local history unavailable: ${error.message}`; });

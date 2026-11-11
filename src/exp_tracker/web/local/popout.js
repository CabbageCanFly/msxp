// /local/overlay: the active local character's progress, for OBS Window Capture. Same layouts, presets,
// colours and URL options as the live overlay (/live/overlay). It never captures the screen. Updates
// arrive over BroadcastChannel; IndexedDB is the source of truth (initial state, missed messages and a
// slow poll while the tracker tab is in the background).
import * as store from './store.js';
import {CHANNEL, OVERLAY_COLORS, THEME_COLORS, duration, exp, headerInk, historyLabel, overlayOptions, percent, summarize, summarizePickups} from './view.js';
import {drawHourChart, expText} from './charts.js';
import {liveChart, rateSeries, smooth} from './live-chart.js';
import {eta} from './exp.js';
import {loadItems} from './pickup-session.js';

const $ = (id) => document.getElementById(id);
let table = null, character = null, readings = [], pickups = [], liveWindow = 5, loading = null, icons = null, options = overlayOptions(location.search);

// Also called by the builder's same-origin preview as options change.
function applyOverlay(o) {
  options = o;
  Object.assign(document.body.dataset, {layout: o.layout, theme: o.theme, name: o.name, icon: o.icon, job: o.job, brand: o.brand, focus: o.focus, bg: o.bg, interval: o.interval, range: o.range});
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
  pickups = character ? await store.pickups(character.id, Date.now() - 24 * 3600e3) : [];
  liveWindow = (await store.getSetting('liveWindow')) ?? 5;
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
  renderLive(view, now);
  renderItems(now);
  // Old readings are shown as such, never as live progress.
  const stale = view.age == null || view.age > 120;
  $('status').hidden = !stale;
  $('status').textContent = view.last ? 'Not tracking right now' : 'Waiting for EXP';
  $('age').textContent = view.last && stale ? `Updated ${duration(view.age)} ago` : '';
}

// The Live layout mirrors the tracker page's Live rate panel: the big number is the line's latest value,
// each second's rate over the panel's window ("Last 5/10/15/30/60 min", saved as liveWindow), for EXP or
// mesos (the Live shows option); the bottom row has the other one. The time to the next level uses the
// same EXP rate, so every number on the card agrees with the line.
let liveView = {series: [], window: 5 * 60e3, unit: 'EXP / h', empty: ''};
function renderLive(view, now) {
  if (options.layout !== 'live') return;
  const window = liveWindow * 60e3, series = (rows, value) => {
    const events = rows.filter((r) => value(r) != null).map((r) => ({at: r.at, amount: value(r)}));
    return rateSeries(events, {from: now - window - 60e3, to: now, window, since: rows[0]?.at ?? now});
  };
  // The drawn (eased) values, so the numbers are exactly where the line's tip is.
  const expLine = smooth(series(readings, (r) => r.gain)), mesoLine = smooth(series(pickups.filter((r) => r.kind === 'mesos'), (r) => r.amount));
  const expRate = expLine.at(-1)?.perHour ?? null, mesoRate = mesoLine.at(-1)?.perHour ?? null, mesos = options.focus === 'mesos';
  $('live-rate').textContent = (mesos ? mesoRate : expRate) == null ? '—' : exp(mesos ? mesoRate : expRate);
  $('live-rate-label').textContent = `${mesos ? 'Mesos' : 'EXP'} / hour · last ${liveWindow} min`;
  $('live-other').textContent = (mesos ? expRate : mesoRate) == null ? '—' : exp(mesos ? expRate : mesoRate);
  $('live-other-label').textContent = mesos ? 'EXP / hour' : 'Mesos / hour';
  const left = eta(table, view.last, expRate);
  $('live-eta').textContent = left == null ? '—' : duration(left);
  $('live-eta-label').textContent = view.last ? `to Lv. ${view.last.level + 1}` : 'to next level';
  $('live-progress').value = view.progress;
  $('live-percent').textContent = view.last ? percent(view.last.bp) : '—';
  $('live-level').textContent = view.last ? `of Lv. ${view.last.level}` : 'of Lv. —';
  $('live-exp').textContent = view.last ? exp(view.last.exp) : '—';
  liveView = {series: mesos ? mesoLine : expLine, window, unit: mesos ? 'mesos / h' : 'EXP / h', empty: ''};
}

// The Items layout: what was picked up in the last 24 hours, largest counts first, with the drop list's icons.
function renderItems(now) {
  if (options.layout !== 'items') return;
  const items = summarizePickups(pickups, now).items;
  if (items.length && !icons) { icons = new Map(); loadItems().then((list) => { icons = new Map(list.map((i) => [i.id, i])); render(); }).catch(() => {}); }
  $('items-total').textContent = items.length ? `${items.reduce((sum, i) => sum + i.count, 0)} items` : '';
  $('items-grid').replaceChildren(...(items.length ? items.slice(0, 12) : [null]).map((item) => {
    const li = document.createElement('li');
    if (!item) { li.className = 'items-empty'; li.textContent = 'No items picked up yet'; return li; }
    const icon = document.createElement('span'), known = icons?.get(item.itemId);
    icon.className = 'icon'; li.title = item.name;
    if (known) icon.style.cssText = `background-image:url(/static/local/items/icons-${known.sheet}.png);background-position:-${known.cell % 16 * 32}px -${Math.floor(known.cell / 16) * 32}px`;
    li.append(icon, Object.assign(document.createElement('strong'), {textContent: `×${exp(item.count)}`}));
    return li;
  }));
}

async function init() {
  liveChart($('live-chart'), () => liveView, {axes: false});
  table = await (await fetch('/static/local/community-exp.json')).json();
  if ('BroadcastChannel' in window) new BroadcastChannel(CHANNEL).onmessage = (event) => { if (event.data?.type === 'update') refresh(); };
  applyOverlay(options);
  await load();
  setInterval(refresh, 30e3);
  setInterval(render, 5e3);
}

init().catch((error) => { $('character').textContent = `Local history unavailable: ${error.message}`; });

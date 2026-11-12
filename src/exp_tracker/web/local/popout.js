// /local/overlay: the active local character's progress, for OBS Window Capture. Same layouts, presets,
// colours and URL options as the live overlay (/live/overlay). It never captures the screen. Updates
// arrive over BroadcastChannel; IndexedDB is the source of truth (initial state, missed messages and a
// slow poll while the tracker tab is in the background).
import * as store from './store.js';
import {CHANNEL, OVERLAY_COLORS, THEME_COLORS, duration, exp, headerInk, historyLabel, overlayOptions, percent, summarize, summarizePickups} from './view.js';
import {drawHourChart, expText} from './charts.js';
import {liveChart, rateSeries, smooth} from './live-chart.js';
import {eta, requirement} from './exp.js';
import {loadItems} from './pickup-session.js';

const $ = (id) => document.getElementById(id);
let shownCounts = null;  // Item counts last drawn by the Items layout, to light up the ones that just went up.
let table = null, character = null, readings = [], pickups = [], liveWindow = 5, loading = null, again = false, wantFull = false, icons = null, options = overlayOptions(location.search);

// Also called by the builder's same-origin preview as options change.
function applyOverlay(o) {
  options = o;
  Object.assign(document.body.dataset, {layout: o.layout, theme: o.theme, name: o.name, icon: o.icon, job: o.job, title: o.title, focus: o.focus, bg: o.bg, interval: o.interval, range: o.range});
  document.body.dataset.headerInk = headerInk(o.header ?? THEME_COLORS[o.theme].header);
  document.body.dataset.panelInk = o.background ? headerInk(o.background) : '';
  $('general-history-caption').textContent = historyLabel(o);
  $('hour-caption').textContent = `EXP per ${Number(o.interval) / 60} min · ${historyLabel(o).split(' · ')[1]}`;
  for (const key of OVERLAY_COLORS) if (/^[0-9a-f]{6}$/.test(o[key] ?? '')) document.body.style.setProperty('--' + key, '#' + o[key]); else document.body.style.removeProperty('--' + key);
  $('overlay-brand').textContent = {site: 'msxp.pages.dev', tracker: 'EXP TRACKER', none: ''}[o.title];
  render();
}
window.applyOverlay = applyOverlay;

// With scans every second, every new reading triggers an update: reading 25 hours (up to ~90,000 rows)
// each time would be heavy, so updates fetch only rows newer than those held. Edits (removals, another
// character) ask for a full read, and so does the 30-second poll.
async function load(full) {
  const id = await store.getSetting('activeCharacterId'), next = id == null ? null : await store.getCharacter(id) ?? null;
  const now = Date.now(), same = !full && character && next?.id === character.id;
  character = next;
  const newer = async (held, fetch, since) => {
    if (!same || !held.length) return fetch(since);
    const tail = new Set(held.slice(-100).map((r) => r.id));
    return [...held, ...(await fetch(held.at(-1).at)).filter((r) => !tail.has(r.id))].filter((r) => r.at >= since);
  };
  readings = character ? await newer(readings, (since) => store.readings(character.id, since), now - 25 * 3600e3) : [];
  pickups = character ? await newer(pickups, (since) => store.pickups(character.id, since), now - 24 * 3600e3) : [];
  liveWindow = (await store.getSetting('liveWindow')) ?? 5;
  render();
}

function refresh(full = false) {
  // Coalesce bursts of messages into one database read at a time.
  wantFull ||= full;
  if (loading) { again = true; return; }
  const asked = wantFull; wantFull = false;
  loading = load(asked).catch(() => {}).finally(() => { loading = null; if (again) { again = false; refresh(); } });
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
  // The eased line only approaches 0: below 1 an hour it is 0 (else the time to the next level is absurd).
  const tip = (line) => { const v = line.at(-1)?.perHour; return v == null ? null : v < 1 ? 0 : v; };
  const expRate = tip(expLine), mesoRate = tip(mesoLine), mesos = options.focus === 'mesos';
  $('live-rate').textContent = (mesos ? mesoRate : expRate) == null ? '—' : exp(mesos ? mesoRate : expRate);
  $('live-rate-label').textContent = `${mesos ? 'Mesos' : 'EXP'} / hour · last ${liveWindow} min`;
  $('live-other').textContent = (mesos ? expRate : mesoRate) == null ? '—' : exp(mesos ? expRate : mesoRate);
  $('live-other-label').textContent = mesos ? 'EXP / hour' : 'Mesos / hour';
  const left = expRate ? eta(table, view.last, expRate) : null;
  $('live-eta').textContent = left == null ? '—' : duration(left);
  $('live-eta-label').textContent = view.last ? `to Lv. ${view.last.level + 1}` : 'to next level';
  $('live-progress').value = view.progress;
  // Share of the level gained per hour at the line's EXP rate; then EXP gained over the line's window.
  const need = view.last ? requirement(table, view.last.level) : null, gained = readings.filter((r) => r.at > now - window && r.gain != null);
  $('live-percent').textContent = expRate != null && need ? `${(expRate / need * 100).toFixed(2)}%` : '—';
  $('live-exp').textContent = view.last ? exp(gained.reduce((sum, r) => sum + r.gain, 0)) : '—';
  $('live-exp-label').textContent = `EXP · last ${liveWindow} min`;
  liveView = {series: mesos ? mesoLine : expLine, window, unit: mesos ? 'mesos / h' : 'EXP / h', empty: ''};
}

// The Items layout: what was picked up in the last 24 hours, largest counts first, with the drop list's icons.
function renderItems(now) {
  if (options.layout !== 'items') return;
  // The category from the item ID's first digit (the inventory tab: 1 Equip, 2 Use, 4 Etc), as on the tracker page.
  const tab = {equip: 1, use: 2, etc: 4}[options.kind], minutes = Number(options.last);
  const items = summarizePickups(pickups, now, minutes).items.filter((item) => !tab || Math.floor(item.itemId / 1e6) === tab);
  $('items-since').textContent = `${tab ? options.kind[0].toUpperCase() + options.kind.slice(1) : 'Items'} · last ${minutes === 1440 ? '24 h' : minutes + ' min'}`;
  if (items.length && !icons) { icons = new Map(); loadItems().then((list) => { icons = new Map(list.map((i) => [i.id, i])); render(); }).catch(() => {}); }
  $('items-total').textContent = items.length ? `${items.reduce((sum, i) => sum + i.count, 0)} items` : 'None yet';
  // Always 12 slots: the ones without an item are faint, so the overlay never changes size.
  const before = shownCounts;
  shownCounts = new Map(items.map((item) => [item.itemId, item.count]));
  $('items-grid').replaceChildren(...Array.from({length: 12}, (_, k) => items[k] ?? null).map((item) => {
    const li = document.createElement('li');
    if (!item) { li.className = 'items-slot'; li.setAttribute('aria-hidden', 'true'); return li; }
    // Just picked up (not on the first draw): a short glow.
    if (before && item.count > (before.get(item.itemId) ?? 0)) li.className = 'bumped';
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
  if ('BroadcastChannel' in window) new BroadcastChannel(CHANNEL).onmessage = (event) => { if (event.data?.type === 'update') refresh(event.data.full !== false); };
  applyOverlay(options);
  await load(true);
  setInterval(() => refresh(true), 30e3);
  setInterval(render, 5e3);
}

init().catch((error) => { $('character').textContent = `Local history unavailable: ${error.message}`; });

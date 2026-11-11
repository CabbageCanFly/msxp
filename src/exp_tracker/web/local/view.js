// View model and overlay options shared by the local dashboard and the pop-out overlay.
import {eta, intervals, requirement, sessionStats, windowStats} from './exp.js';

export const CHANNEL = 'msxp-local';
export const WINDOWS = [5, 10, 15, 30, 60];

const integer = new Intl.NumberFormat('en-US');
export const exp = (n) => n == null ? '—' : integer.format(Math.round(n));
export const percent = (bp) => bp == null ? '—' : (bp / 100).toFixed(2) + '%';

export function duration(seconds) {
  if (seconds == null || !isFinite(seconds)) return '—';
  const s = Math.max(0, Math.round(seconds)), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
  return h >= 24 ? `${Math.floor(h / 24)}d ${h % 24}h` : h ? `${h}h ${m}m` : m ? `${m}m` : `${s}s`;
}

export const slug = (job) => job.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
export const jobIcon = (job) => `/static/jobs/${slug(job)}.png`;
// Names and icons from data/jobs.json (Beginner, first and second jobs).
export const JOBS = ['Beginner', 'Swordsman', 'Fighter', 'Page', 'Spearman', 'Magician', 'Wizard (Fire, Poison)', 'Wizard (Ice, Lightning)',
  'Cleric', 'Archer', 'Hunter', 'Crossbowman', 'Rogue', 'Assassin', 'Bandit'];

/**
 * Everything both pages display, from a character record and its accepted readings (oldest first).
 * Rates need 80 % coverage of their window; until then the session's rate so far is shown, labelled
 * as such, while `live`. `levelOnly` counts only EXP earned at the current level (the 24h total includes all).
 */
export function summarize(table, character, readings, now, window = 15, {sessionId = null, levelOnly = false, live = false} = {}) {
  const last = character?.last ?? null, all = intervals(readings);
  const scoped = levelOnly && last ? all.filter((it) => it.level === last.level) : all;
  const current = sessionId ?? readings.at(-1)?.sessionId ?? null;
  const session = sessionStats(scoped.filter((it) => it.sessionId === current));
  const rates = Object.fromEntries(WINDOWS.map((m) => [m, windowStats(scoped, now, m * 60)]));
  const selected = rates[window] ?? rates[15];
  // "So far" only describes a session that is still running, never an old one.
  const early = live && !selected.ok && session.perHour != null;
  const perHour = selected.ok ? selected.perHour : early ? session.perHour : null;
  const total = last && requirement(table, last.level);
  const recent = windowStats(scoped, now, 300), day = windowStats(all, now, 86400);
  return {
    name: character?.name ?? '', job: character?.job ?? '', last, total,
    progress: last && total ? Math.min(100, last.exp / total * 100) : last ? last.bp / 100 : 0,
    perHour, window, covered: early ? session.covered : selected.covered, early,
    rates: Object.fromEntries(WINDOWS.map((m) => [m, rates[m].ok ? rates[m].perHour : null])),
    recent: recent.covered > 0 ? recent.gain : null,
    percentPerHour: perHour != null && total ? perHour / total * 100 : null,
    eta: eta(table, last, perHour),
    dayGain: day.covered > 0 ? day.gain : null, dayCovered: day.covered, totalGain: character?.totalGain ?? 0,
    intervals: scoped, allIntervals: all,
    age: last ? (now - last.at) / 1000 : null,
  };
}

/** Pickups for display, from stored rows: mesos and items (largest count first) of the last 24 hours. */
export function summarizePickups(rows, now) {
  const day = rows.filter((r) => r.at >= now - 86400e3);
  const items = new Map();
  for (const r of day) if (r.kind === 'item') {
    const item = items.get(r.name) ?? {name: r.name, itemId: r.itemId, count: 0};
    item.count += r.count; items.set(r.name, item);
  }
  return {mesosDay: day.reduce((sum, r) => sum + (r.kind === 'mesos' ? r.amount : 0), 0),
    items: [...items.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))};
}

/**
 * What was tracked between two times (inclusive), for removing it: EXP gained, mesos and items. Days
 * older than `detailSince` keep only a daily summary, so those count only when the range covers the
 * whole local day (`oldDays`: their summaries).
 */
export function trackedBetween(readings, pickups, from, to, days = [], detailSince = -Infinity) {
  const inside = (r) => r.at >= from && r.at <= to, gains = readings.filter((r) => inside(r) && r.gain != null);
  const found = pickups.filter(inside), items = summarizePickups(found.filter((r) => r.kind === 'item'), to).items;
  const oldDays = days.filter((d) => {
    const start = new Date(`${d.day}T00:00`), end = new Date(start);
    end.setDate(end.getDate() + 1);
    return +start >= from && +end - 1 <= to && +end <= detailSince;
  });
  return {exp: gains.reduce((sum, r) => sum + r.gain, 0) + oldDays.reduce((sum, d) => sum + (d.gain || 0), 0), expReadings: gains.length, oldDays,
    mesos: found.reduce((sum, r) => sum + (r.kind === 'mesos' ? r.amount : 0), 0), mesoPickups: found.filter((r) => r.kind === 'mesos').length, items};
}

// ---------- overlay options (ported from product.js; same URL parameters as the live overlay) ----------

// Anything unknown falls back to the first choice. 'name' has no Twitch option here; 'bg' is the
// opaque window colour around the card (OBS Window Capture cannot see transparency).
export const OVERLAY_CHOICES = {layout: ['card', 'bar', 'rates', 'chart'], title: ['site', 'tracker'], icon: ['off', 'on'], job: ['off', 'on'],
  name: ['character', 'none'], theme: ['night', 'day', 'red', 'green', 'blue', 'purple'], bg: ['dark', 'green', 'magenta'],
  interval: ['60', '300', '1800'], range: ['60', '15', '30', '720', '1440']};
export const OVERLAY_COLORS = ['background', 'header', 'graph', 'bar', 'text', 'level', 'badge', 'accent'];
export const THEME_COLORS = {night: {background: '232c3e', header: '705035', graph: 'ffc56b', bar: 'a6ef2e', text: 'ffc56b', level: 'ffc56b', badge: '2b354a'},
  day: {background: 'fff9e9', header: '8a6440', graph: 'a8520a', bar: '7fcc12', text: 'a8520a', level: 'ffb534', badge: '6e5139'},
  red: {background: '301f26', header: '8c3547', graph: 'ff9b9b', bar: 'ef6575', text: 'ffb4b4', level: 'ffd5bd', badge: '542b38'},
  green: {background: '1c3029', header: '32684e', graph: '8fe0b2', bar: '70ce82', text: 'b1ebc6', level: 'e4f3b0', badge: '294b3b'},
  blue: {background: '1d2b40', header: '335e91', graph: '8fc9ff', bar: '66b5ef', text: 'b4d9ff', level: 'd4e9ff', badge: '2b4566'},
  purple: {background: '2a233b', header: '62458c', graph: 'c4a1ff', bar: 'ad87ef', text: 'dbc4ff', level: 'f1d5ff', badge: '45335e'}};
export const OVERLAY_SIZES = {card: [500, 160], bar: [500, 160], rates: [500, 110], chart: [500, 180]};

export function overlayOptions(search) {
  const q = new URLSearchParams(search), options = {};
  for (const [key, allowed] of Object.entries(OVERLAY_CHOICES)) options[key] = allowed.includes(q.get(key)) ? q.get(key) : allowed[0];
  if (options.interval === '1800') { if (!['720', '1440'].includes(options.range)) options.range = '1440'; }
  else if (['720', '1440'].includes(options.range)) options.range = '60';
  for (const key of OVERLAY_COLORS) if (/^[0-9a-f]{6}$/i.test(q.get(key) ?? '')) options[key] = q.get(key).toLowerCase();
  return options;
}

export function overlayQuery(options) {
  const q = new URLSearchParams();
  for (const [key, allowed] of Object.entries(OVERLAY_CHOICES)) if (options[key] !== allowed[0]) q.set(key, options[key]);
  for (const key of OVERLAY_COLORS) if (options[key]) q.set(key, options[key]);
  return String(q);
}

export function headerInk(hex) {
  const rgb = hex.match(/../g).map((c) => { const s = parseInt(c, 16) / 255; return s <= .04045 ? s / 12.92 : ((s + .055) / 1.055) ** 2.4; });
  return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2] > .179 ? 'dark' : 'light';
}

export function randomOverlayColors() {
  const hue = Math.random() * 360, accent = hue + (Math.random() < .5 ? 30 : 180);
  const style = Math.floor(Math.random() * 3), light = style === 1, vibrant = style === 2, tone = Math.random();
  const hex = (h, s, l) => {
    h = (h % 360 + 360) % 360; s /= 100; l /= 100;
    const a = s * Math.min(l, 1 - l);
    return [0, 8, 4].map((n) => { const k = (n + h / 30) % 12; return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))).toString(16).padStart(2, '0'); }).join('');
  };
  // Light palettes use deep values; dark and vibrant palettes use pale values for contrast.
  return {background: hex(hue, light || vibrant ? 55 : 28, light ? 94 + tone * 3 : (vibrant ? 12 : 10) + tone * (vibrant ? 4 : 6)),
    header: hex(hue, vibrant ? 80 : 50, light ? 78 : vibrant ? 43 : 30), badge: hex(hue, vibrant ? 55 : 30, light ? 88 : 20 + tone * (vibrant ? 1 : 3)),
    graph: hex(accent, vibrant ? 95 : 80, light ? 30 : vibrant ? 76 : 72), bar: hex(accent, vibrant ? 95 : 80, light ? 40 : vibrant ? 55 : 58),
    text: hex(accent, 75, light ? 24 : 82), level: hex(accent, 85, light ? 20 : 88)};
}

export const historyLabel = (o) => `${Number(o.interval) / 60} min · ${o.range === '1440' ? '24h' : o.range === '720' ? '12h' : o.range === '60' ? 'last hour' : `last ${o.range} min`}`;

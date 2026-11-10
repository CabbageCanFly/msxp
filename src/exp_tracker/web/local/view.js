// View model and formatting shared by the local dashboard and the pop-out overlay.
import {eta, intervals, requirement, sessionStats, windowStats} from './exp.js';

export const CHANNEL = 'msxp-local';
export const WINDOWS = [5, 15, 30, 60];
export const BUCKET_MINUTES = 5;

const integer = new Intl.NumberFormat('en-US');
export const exp = (n) => n == null ? '—' : integer.format(Math.round(n));
export const percent = (bp) => bp == null ? '—' : (bp / 100).toFixed(2) + '%';
export const compact = (n) => n == null ? '—' : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 1 : 2) + 'M' : n >= 1e4 ? (n / 1e3).toFixed(1) + 'K' : integer.format(Math.round(n));

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
 * `window` is minutes or 'session'. Rates need 80% coverage of their window; the session rate
 * needs two observed minutes. Missing time is never counted as zero.
 */
export function summarize(table, character, readings, now, window = 15, sessionId = null) {
  const all = intervals(readings), last = character?.last ?? null;
  const current = sessionId ?? readings.at(-1)?.sessionId ?? null;
  const session = sessionStats(all.filter((it) => it.sessionId === current));
  const rates = Object.fromEntries(WINDOWS.map((m) => [m, windowStats(all, now, m * 60)]));
  const selected = window === 'session' ? {perHour: session.perHour, ok: session.perHour != null, covered: session.covered}
    : rates[window];
  // Until a window has 80 % coverage, show the session's rate so far, labelled as such.
  const early = !selected.ok && session.perHour != null;
  const perHour = selected.ok ? selected.perHour : early ? session.perHour : null;
  const total = last && requirement(table, last.level);
  const recent = windowStats(all, now, 300);
  return {
    name: character?.name ?? '', job: character?.job ?? '', last, total,
    progress: last && total ? Math.min(100, last.exp / total * 100) : last ? last.bp / 100 : 0,
    perHour, window, covered: early ? session.covered : selected.covered, early,
    rates: Object.fromEntries(WINDOWS.map((m) => [m, rates[m].ok ? rates[m].perHour : null])),
    recent: recent.covered > 0 ? recent.gain : null, recentCovered: recent.covered,
    percentPerHour: perHour != null && total ? perHour / total * 100 : null,
    eta: eta(table, last, perHour),
    sessionGain: session.gain, sessionCovered: session.covered, totalGain: character?.totalGain ?? 0,
    buckets: buckets(all, now, 120),
    age: last ? (now - last.at) / 1000 : null,
  };
}

// EXP per 5-minute bucket; a bucket with little observed time is null (shown as missing, not zero).
export function buckets(list, now, minutes) {
  const size = BUCKET_MINUTES * 60e3, end = Math.ceil(now / size) * size, count = minutes / BUCKET_MINUTES, out = [];
  for (let i = count - 1; i >= 0; i--) {
    const to = end - i * size, from = to - size;
    let gain = 0, covered = 0;
    for (const it of list) {
      // Gains are attributed to the bucket where their interval ends (never split between buckets).
      if (it.end > from && it.end <= to) { gain += it.gain; covered += Math.min(it.end - it.start, size); }
    }
    out.push({from, to, gain: covered >= size * .5 || (to > now && covered > 0) ? gain : null});
  }
  return out;
}

export function chartSvg(list, {width = 462, height = 76, gap = 2} = {}) {
  const max = Math.max(1, ...list.map((b) => b.gain ?? 0)), w = width / list.length;
  return list.map((b, i) => {
    const x = (i * w + gap / 2).toFixed(1), bw = Math.max(1, w - gap).toFixed(1);
    if (b.gain == null) return `<rect class="exp-column missing" x="${x}" y="${height - 2}" width="${bw}" height="2"><title>No data</title></rect>`;
    const h = Math.max(b.gain ? 2 : 1, b.gain / max * (height - 4));
    const label = `${new Date(b.from).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'})}: ${exp(b.gain)} EXP`;
    return `<rect class="exp-column" x="${x}" y="${(height - h).toFixed(1)}" width="${bw}" height="${h.toFixed(1)}"><title>${label}</title></rect>`;
  }).join('');
}

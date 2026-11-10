// Pickup messages in the bottom-right corner ("You have gained mesos (+10)", "Leather x1 earned. (Etc)").
// Pure functions shared by the browser and the Node tests. A frame is {width, height, data} (RGBA).

// Message text is light neutral grey with a near-black neutral outline (pure black in a window capture,
// dark grey in the game's own screenshots). Scenery rarely puts neutral dark right beside neutral light,
// which separates text from clouds, fences and the quick-slot panel.
// With `keep`, each line also carries `bits`, its text mask (1 = text), for reading the line.
export function messageLines(frame, keep = false) {
  const {width: w, height: h, data: d} = frame, text = new Uint8Array(w * h), rows = new Int32Array(h);
  const spread = (i) => Math.max(d[i], d[i + 1], d[i + 2]) - Math.min(d[i], d[i + 1], d[i + 2]);
  const dark = (i) => Math.max(d[i], d[i + 1], d[i + 2]) < 60 && spread(i) < 30;
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const i = (y * w + x) * 4;
    if (Math.min(d[i], d[i + 1], d[i + 2]) > 170 && spread(i) < 40 && (dark(i - 4) || dark(i + 4) || dark(i - 4 * w) || dark(i + 4 * w))) { text[y * w + x] = 1; rows[y]++; }
  }
  const lines = [];
  let start = -1;
  for (let y = 0; y <= h; y++) {
    const on = y < h && rows[y] >= 4;
    if (on && start < 0) start = y;
    if (on || start < 0) continue;
    if (y - start >= 4 && y - start <= 14) {
      let x0 = w, x1 = -1, n = 0;
      for (let yy = start; yy < y; yy++) for (let x = 0; x < w; x++) if (text[yy * w + x]) { n++; if (x < x0) x0 = x; if (x > x1) x1 = x; }
      // Messages are right-aligned at the window edge and at least a few words long.
      // An open inventory window's meso row spans the box from the left; messages never do.
      if (n > 40 && x1 > w - 30 && x1 - x0 > 80 && x0 > w * .2) {
        let key = 0;
        for (let yy = start; yy < y; yy++) for (let x = x0; x <= x1; x++) key = (key * 31 + text[yy * w + x]) | 0;
        const line = {y0: start, y1: y, x0, x1, n, key: `${x1 - x0}:${key}`};
        if (keep) {
          line.bits = new Uint8Array((x1 - x0 + 1) * (y - start));
          for (let yy = start; yy < y; yy++) line.bits.set(text.subarray(yy * w + x0, yy * w + x1 + 1), (yy - start) * (x1 - x0 + 1));
        }
        lines.push(line);
      }
    }
    start = -1;
  }
  return lines.reverse();  // Newest (bottom) first.
}

// Overlap of two line masks aligned at their right edge and top (messages are right-aligned): 0..1.
export function similarity(a, b) {
  const wa = a.x1 - a.x0 + 1, wb = b.x1 - b.x0 + 1, h = Math.min(a.y1 - a.y0, b.y1 - b.y0), w = Math.min(wa, wb);
  let both = 0, either = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const pa = a.bits[y * wa + wa - w + x], pb = b.bits[y * wb + wb - w + x];
    if (pa && pb) both++;
    if (pa || pb) either++;
  }
  return either ? both / either : 0;
}

/**
 * Counts pickup messages by following each line across frames (measured on a live recording: lines fade
 * in and out, several can appear at once, and they drift up as new ones arrive). A line that matches no
 * current track by position and shape starts a new one; it counts once it is seen on a second frame.
 * Two identical messages on screen at once are two tracks, so repeats ("+10", "+10") still count.
 * `update(lines, at)` takes lines with `bits` and returns the newly confirmed lines.
 */
export function lineTracker({forgetMs = 400} = {}) {
  let tracks = [];
  return {
    update(lines, at) {
      const used = new Set(), confirmed = [];
      // Oldest (top) lines first: each old line claims its own track before new lines are considered.
      for (const line of [...lines].sort((a, b) => a.y0 - b.y0)) {
        let best = null, score = .3;
        for (const t of tracks) {
          const dy = t.line.y0 - line.y0;  // Lines only move up, by about one line per new message.
          if (used.has(t) || dy < -2 || dy > 30 || Math.abs(t.line.x1 - line.x1) > 2 || Math.abs((t.line.x1 - t.line.x0) - (line.x1 - line.x0)) > 8) continue;
          const s = similarity(t.line, line) - Math.abs(dy) * .01;
          if (s > score) { score = s; best = t; }
        }
        if (!best) { best = {seen: 0, counted: false}; tracks.push(best); }
        used.add(best);
        Object.assign(best, {line, lastAt: at, seen: best.seen + 1});
        if (best.seen === 2 && !best.counted) { best.counted = true; confirmed.push(line); }
      }
      tracks = tracks.filter((t) => at - t.lastAt < forgetMs);
      return confirmed;
    },
  };
}

const amount = (s) => Number(s.replace(/[,.]/g, ''));

// One message line of text, or null. Item names may be cut off with "...".
export function parseMessage(text) {
  const t = text.replace(/\s+/g, ' ').trim();
  let m = /gained mesos \(\+?([\d,.]+)\)/i.exec(t);
  if (m) return {kind: 'mesos', amount: amount(m[1])};
  m = /(?:gained|received) (?:experience|exp)\w* \(\+?([\d,.]+)\)/i.exec(t);
  if (m) return {kind: 'exp', amount: amount(m[1])};
  m = /^(.+?)\s*x\s?(\d+) earned\.? \((Eqp|Equip|Use|Setup|Etc|Cash)\)$/i.exec(t);
  if (m) {
    const name = m[1].trim(), cut = /(\.\.\.|…)$/.test(name);
    return {kind: 'item', name: name.replace(/(\.\.\.|…)$/, '').trim(), cut, count: Number(m[2]), tab: m[3] === 'Eqp' ? 'Equip' : m[3]};
  }
  return null;
}

/**
 * The item a message names. Full names match exactly (case-insensitive); a cut-off name matches the one
 * item in that tab starting with it. Two candidates means no guess: the shown text is kept instead.
 */
export function resolveItem(items, {name, cut, tab}) {
  const lower = name.toLowerCase(), inTab = items.filter((item) => !tab || item.tab === tab);
  const found = cut ? inTab.filter((item) => item.name.toLowerCase().startsWith(lower)) : inTab.filter((item) => item.name.toLowerCase() === lower);
  return found.length === 1 ? found[0] : null;
}

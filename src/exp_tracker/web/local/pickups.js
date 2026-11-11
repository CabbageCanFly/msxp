// Pickup messages in the bottom-right corner ("You have gained mesos (+10)", "Leather x1 earned. (Etc)").
// Pure functions shared by the browser and the Node tests. A frame is {width, height, data} (RGBA).

// Message text is light grey (~240) with a dark drop shadow one pixel right and down, both slightly
// see-through: over grass the fill tints green (~200,240,180) and the shadow turns dark green. So a text
// pixel is a light, nearly neutral pixel whose down-right neighbour is much darker (by more than 100).
// Only that neighbour: over white clouds the fill vanishes into the cloud, and the cloud just past the
// shadow is light next to dark too (measured: any-neighbour masks drew every letter hollow there).
// With `keep`, each line also carries `bits`, its text mask (1 = text), for reading the line.
export function messageLines(frame, keep = false) {
  const {width: w, height: h, data: d} = frame, text = new Uint8Array(w * h), rows = new Int32Array(h);
  const lum = (i) => (d[i] + d[i + 1] + d[i + 2]) / 3;
  // Not the last columns: the window's own edge is a light column there (messages end ~8 px before it).
  // Bottom-up, so the down-right neighbour is decided first.
  for (let y = h - 2; y >= 1; y--) for (let x = w - 4; x >= 1; x--) {
    const p = y * w + x, i = p * 4, low = Math.min(d[i], d[i + 1], d[i + 2]);
    if (low <= 150 || Math.max(d[i], d[i + 1], d[i + 2]) - low >= 80) continue;
    // Over grass the shadow blends to dark green, so there is no colour test for it. A stroke pixel whose
    // down-right neighbour is more stroke (the corner of a "+") casts no shadow: it counts when scenery
    // up-left of it is darker, which over white clouds it never is.
    const l = lum(i);
    if (l - lum((p + w + 1) * 4) > 100 || (text[p + w + 1] && l - lum((p - w - 1) * 4) > 50)) { text[p] = 1; rows[y]++; }
  }
  const lines = [];
  const emit = (top, bottom) => {
    // The line is the right-aligned run of text: it ends at the first gap wider than a word space, so the
    // quick-slot panel or other UI further left in the same rows is not part of it.
    const cols = new Int32Array(w);
    for (let yy = top; yy < bottom; yy++) for (let x = 0; x < w; x++) cols[x] += text[yy * w + x];
    let x1 = w - 1;
    while (x1 >= 0 && !cols[x1]) x1--;
    let x0 = x1, n = 0;
    for (let x = x1; x >= 0 && x0 - x <= 16; x--) if (cols[x]) { x0 = x; n += cols[x]; }
    // Messages are right-aligned at the window edge and at least a few words long.
    // An open inventory window's meso row spans the box from the left; messages never do.
    if (n <= 40 || x1 <= w - 30 || x1 - x0 <= 80 || x0 <= w * .2) return;
    const line = {y0: top, y1: bottom, x0, x1, n};
    if (keep) {
      line.bits = new Uint8Array((x1 - x0 + 1) * (bottom - top));
      for (let yy = top; yy < bottom; yy++) line.bits.set(text.subarray(yy * w + x0, yy * w + x1 + 1), (yy - top) * (x1 - x0 + 1));
    }
    lines.push(line);
  };
  let start = -1;
  for (let y = 0; y <= h; y++) {
    const on = y < h && rows[y] >= 4;
    if (on && start < 0) start = y;
    if (on || start < 0) continue;
    // Stacked messages sit about 14 px apart and descenders touch the next line, so a block can hold
    // several lines. Each line has a dense core (its lowercase height, ~7 rows); capitals and descenders
    // are sparse. Find the cores, then pad each by a fixed margin so a line's box is the same every frame.
    const sorted = [...rows.subarray(start, y)].sort((a, b) => a - b), dense = Math.max(sorted[Math.floor(sorted.length * .75)] * .4, sorted[sorted.length - 1] * .3);
    let from = -1;
    for (let yy = start; yy <= y; yy++) {
      const core = yy < y && rows[yy] >= dense;
      if (core && from < 0) from = yy;
      if (core || from < 0) continue;
      if (yy - from >= 4 && yy - from <= 10) emit(Math.max(0, from - 2), Math.min(h, yy + 3));
      from = -1;
    }
    start = -1;
  }
  return lines.reverse();  // Newest (bottom) first.
}

// How different two line masks are, aligned at their right edge and top, allowing the line box to sit a
// pixel or two off (its top follows the text's dense rows). One-sided: the smaller of "pixels only in a"
// and "pixels only in b", so noise added behind a line, or a line fading out, counts as the same line,
// while a changed digit leaves pixels on both sides. Capped: past `cap` they are just different.
function difference(a, b, cap = 30) {
  const wa = a.x1 - a.x0 + 1, wb = b.x1 - b.x0 + 1, ha = a.y1 - a.y0, hb = b.y1 - b.y0, w = Math.max(wa, wb) + 1;
  const at = (bits, wd, ht, x, y) => (y >= 0 && y < ht && x >= 0 && x < wd ? bits[y * wd + x] : 0);
  let best = cap;
  for (let dy = -2; dy <= 2; dy++) for (let dx = -1; dx <= 1; dx++) {
    let onlyA = 0, onlyB = 0;
    for (let y = -2; y < Math.max(ha, hb) + 2 && Math.min(onlyA, onlyB) < best; y++) for (let x = 1 - w; x <= 1; x++) {
      const pa = at(a.bits, wa, ha, wa - 1 + x, y), pb = at(b.bits, wb, hb, wb - 1 + x + dx, y + dy);
      if (pa && !pb) onlyA++; else if (pb && !pa) onlyB++;
    }
    best = Math.min(best, onlyA, onlyB);
  }
  return best;
}

const PITCH = 14, MAX_SLOTS = 7;  // Measured: messages stack 14 px apart, at most 6 on screen.
// Costs of explaining a frame (tuned on two recordings against counted messages; a wide plateau of
// settings scored the same): each new message costs NEW_COST, further ones in the same frame EXTRA_COST
// (bursts bring 3-4 per frame); a remembered line costs PIXEL_COST per differing pixel, at most MATCH_CAP,
// since the same line over scrolling scenery differs by up to ~10 pixels and another line by 100+; a line
// nothing explains costs UNEXPLAINED_COST.
const NEW_COST = 30, EXTRA_COST = 30, PIXEL_COST = 3, MATCH_CAP = 30, UNEXPLAINED_COST = 100;

/**
 * Counts pickup messages as a stack (measured on a live recording): each new message appears at the
 * bottom slot and pushes every line up one slot (14 px); messages can arrive on consecutive frames, and
 * the whole stack fades out together. Each frame picks the shift (0 = nothing new) that best explains the
 * lines: a line should match the one remembered one slot lower per new message, and every new message
 * has a small cost so an unchanged stack stays unchanged. Slots are remembered for `forgetMs`, so a line
 * that is missed for a few frames is not counted again.
 * Limit: a full stack of identical lines ("+13", "+13", ...) looks the same before and after one more.
 * `update(lines, at)` takes lines with `bits` and returns the messages whose lines have left the screen:
 * {at, samples}, `samples` being the line's masks seen at different slots, for reading.
 */
export function stackTracker({forgetMs = 1500} = {}) {
  let bottom = null, slots = [];  // slots[k]: {msg, line, at} for the line k slots above the bottom.
  const votes = new Map();
  let arrived = 0, started = false;
  const retire = (entry, done) => { if (entry?.msg) done.push(entry.msg); };
  return {
    update(lines, at) {
      const done = [];
      slots = slots.map((entry) => (entry && at - entry.at > forgetMs ? (retire(entry, done), undefined) : entry));
      // The bottom slot is where the lowest line sits most often; a stray line further down is outvoted.
      const lowest = lines.reduce((y, line) => Math.max(y, line.y0), -1);
      if (lowest >= 0) votes.set(lowest, (votes.get(lowest) ?? 0) + 1);
      const voted = [...votes].reduce((top, [y, n]) => (n > (votes.get(top) ?? 0) ? y : top), bottom ?? lowest);
      if (bottom === null) bottom = lowest >= 0 ? voted : null;  // Unknown until a line is seen.
      else if (Math.abs(voted - bottom) > 3) {
        const move = Math.round((voted - bottom) / PITCH);
        bottom += move * PITCH;
        if (move > 0) slots = [...Array(move), ...slots];
        else for (const entry of slots.splice(0, -move)) retire(entry, done);
      }
      const placed = [];
      for (const line of lines) {
        const k = Math.round((bottom - line.y0) / PITCH);
        if (k >= 0 && k < MAX_SLOTS && Math.abs(bottom - k * PITCH - line.y0) <= 3) placed.push({k, line});
      }
      // Lines already on screen when tracking starts are followed, not counted.
      let shift = 0, best = Infinity;
      for (let s = 0; s < (started ? MAX_SLOTS : 1); s++) {
        let cost = s ? NEW_COST + (s - 1) * EXTRA_COST : 0;
        for (const {k, line} of placed) {
          if (k < s) continue;
          const entry = slots[k - s];
          cost += !entry ? UNEXPLAINED_COST : entry.line ? Math.min(MATCH_CAP, PIXEL_COST * difference(entry.line, line)) : 0;
        }
        if (cost < best) { best = cost; shift = s; }
      }
      started = true;
      // The lowest new slot is the newest message.
      const fresh = Array.from({length: shift}, (_, j) => ({msg: {at, samples: [], order: arrived + shift - j}, at}));
      arrived += shift;
      slots = [...fresh, ...slots];
      for (const entry of slots.splice(MAX_SLOTS)) retire(entry, done);
      for (const {k, line} of placed) {
        // An unexplained line (there before tracking began, or noise) is followed but never counted.
        const entry = slots[k] ??= {msg: null};
        Object.assign(entry, {line, at});
        // A sample unlike the message's first is another line, after a misjudged jump of several slots
        // (measured: ~15% of messages in bursts); other lines differ by 100+ pixels.
        if (entry.msg && entry.slot !== k && entry.msg.samples.length < 4 && (!entry.msg.first || difference(entry.msg.first, line, 61) <= 60)) {
          entry.slot = k;
          entry.msg.first ??= line;
          entry.msg.samples.push({width: line.x1 - line.x0 + 1, height: line.y1 - line.y0, bits: line.bits});
        }
      }
      return done.sort((a, b) => a.order - b.order).map(({at, samples}) => ({at, samples}));  // Oldest first.
    },
  };
}

// Words of a line mask ({width, height, bits}): glyphs are runs of inked columns, and a gap of 4 or more
// empty columns is a space (measured: words 4-7 apart, letters 1-2). Each word lists its glyphs' columns.
// The font is proportional: a narrow "1" is also followed by 4, so "(+13)" can split; see amountSpan.
export function lineWords({width, height, bits}) {
  const words = [];
  let glyph = null, gap = 99;
  for (let x = 0; x <= width; x++) {
    let ink = false;
    if (x < width) for (let y = 0; y < height && !ink; y++) ink = bits[y * width + x] === 1;
    if (ink) {
      if (!glyph) {
        if (gap >= 4) words.push({x0: x, x1: x, glyphs: []});
        glyph = {x0: x};
      }
      gap = 0;
      continue;
    }
    if (glyph) { glyph.x1 = x; words.at(-1).glyphs.push(glyph); words.at(-1).x1 = x; glyph = null; }
    gap++;
  }
  return words;
}

// The digits of a line ending in "(+1,250)": the glyphs between "(+" and ")", as columns [x0, x1), or null.
// Parentheses are the only glyphs reaching both the top of capitals and the bottom of descenders.
export function amountSpan(mask) {
  const glyphs = lineWords(mask).flatMap((word) => word.glyphs), {width, height, bits} = mask;
  const extent = glyphs.map(({x0, x1}) => {
    let top = height, bottom = -1;
    for (let y = 0; y < height; y++) for (let x = x0; x < x1; x++) if (bits[y * width + x]) { top = Math.min(top, y); bottom = y; }
    return [top, bottom];
  });
  const top = Math.min(...extent.map((e) => e[0])), bottom = Math.max(...extent.map((e) => e[1]));
  const tall = (i) => extent[i][0] <= top + 1 && extent[i][1] >= bottom - 1;
  const last = glyphs.length - 1;
  if (last < 3 || !tall(last)) return null;
  let open = last - 1;
  while (open >= 0 && !tall(open)) open--;
  return open >= 0 && last - open >= 3 ? [glyphs[open + 2].x0, glyphs[last - 1].x1] : null;
}

// Columns x0..x1 of a line mask, as a mask of its own.
export function span({width, height, bits}, x0, x1) {
  const out = new Uint8Array((x1 - x0) * height);
  for (let y = 0; y < height; y++) out.set(bits.subarray(y * width + x0, y * width + x1), y * (x1 - x0));
  return {width: x1 - x0, height, bits: out};
}

function editDistance(a, b) {
  let row = Array.from({length: b.length + 1}, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const next = [i];
    for (let j = 1; j <= b.length; j++) next[j] = Math.min(row[j] + 1, next[j - 1] + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    row = next;
  }
  return row[b.length];
}

const TABS = ['Equip', 'Use', 'Setup', 'Etc', 'Cash'];
// The inventory tab a "(Etc)"-style word names, from imperfect OCR ("(Eqp)" is the game's spelling).
export const tabOf = (text) => {
  const t = text.replace(/[^a-z]/gi, '').toLowerCase().replace(/^eqp$/, 'equip');
  const scored = TABS.map((tab) => [tab, editDistance(t, tab.toLowerCase())]).sort((a, b) => a[1] - b[1]);
  return scored[0][1] <= 1 && scored[0][1] < scored[1][1] ? scored[0][0] : null;
};

/**
 * The item an OCR'd name refers to: the closest name in the tab, allowing about one wrong letter in four.
 * A cut-off name ("Orange Mushro...") is compared with the same length of each name. A tie means no
 * guess, so the shown text is kept instead.
 */
export function resolveItem(items, {name, cut, tab}) {
  const norm = (text) => text.toLowerCase().replace(/[^a-z0-9]/g, ''), want = norm(name);
  if (!want) return null;
  let best = null, score = Infinity, tie = false;
  for (const item of items) {
    if (tab && item.tab !== tab) continue;
    const full = norm(item.name), d = editDistance(want, cut ? full.slice(0, want.length) : full);
    if (d < score) { best = item; score = d; tie = false; } else if (d === score) tie = true;
  }
  return best && !tie && score <= Math.max(1, Math.floor(want.length / 4)) ? best : null;
}

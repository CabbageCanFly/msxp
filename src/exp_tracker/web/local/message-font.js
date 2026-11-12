// The pickup-message font, learned on the player's own machine from lines whose text is known (read by
// OCR and confirmed, or completed from the item list). A font is
// {char: [glyph, ...]}, each glyph {w, h, bits} as seen in a line mask; scenery behind the see-through
// text changes a few pixels, so reading takes the nearest learned glyph rather than an exact match.
import {BASE_FONT} from './message-font-base.js';
import {lineWords} from './pickups.js';

const PER_CHAR = 6;  // Variants kept per character.

// Reads of exact glyph shapes per font (the same words repeat on every line); emptied when the font changes.
const caches = new WeakMap();
const cache = (font) => { if (!caches.has(font)) caches.set(font, new Map()); const seen = caches.get(font); if (seen.size > 20000) seen.clear(); return seen; };

// The shipped font (message-font-base.js), unpacked once.
let base = null;
const baseFont = () => base ??= Object.fromEntries(Object.entries(BASE_FONT).map(([char, packed]) => [char, packed.map((v) => {
  const [w, h, b64] = v.split(','), raw = atob(b64), bits = new Uint8Array(w * h);
  for (let i = 0; i < bits.length; i++) bits[i] = (raw.charCodeAt(i >> 3) >> (i & 7)) & 1;
  return {w: Number(w), h: Number(h), bits};
})]));

// Every character starts with the shipped variants (at most three, so learning keeps room for the
// player's own), then the player's learned ones; a learned variant clearly closer to another character's
// shipped one is dropped (measured: OCR misreads had taught a 6 as "8", and 6666 mesos read as 8888; a
// browser holding its own noisy 6 never got the checked one when shipped variants only filled gaps).
// Changes `font` in place.
export function seedFont(font) {
  const shipped = baseFont();
  for (const [char, variants] of Object.entries(shipped)) {
    const own = (font[char] ?? []).filter((g) => !variants.some((v) => distance(v, g) <= 1)
      && !(nearest(shipped, g, (c) => c !== char) + 2 <= nearest(shipped, g, (c) => c === char)));
    font[char] = [...variants.map((g) => ({...g})), ...own].slice(0, PER_CHAR);
  }
  caches.delete(font);
  return font;
}

// Glyphs of a line mask in order, each with the empty columns before it (a space is 4 or more).
export function glyphsOf(mask) {
  const out = [];
  let end = null;
  for (const word of lineWords(mask)) for (const {x0, x1} of word.glyphs) {
    const w = x1 - x0, bits = new Uint8Array(w * mask.height);
    for (let y = 0; y < mask.height; y++) bits.set(mask.bits.subarray(y * mask.width + x0, y * mask.width + x1), y * w);
    out.push({w, h: mask.height, bits, gap: end === null ? 0 : x0 - end, x0});
    end = x1;
  }
  return out;
}

const ink = (g) => g.bits.reduce((sum, b) => sum + b, 0);

// First and last inked rows of a glyph.
function rows(g) {
  let top = g.h, bottom = -1;
  for (let y = 0; y < g.h; y++) for (let x = 0; x < g.w; x++) if (g.bits[y * g.w + x]) { top = Math.min(top, y); bottom = y; }
  return [top, bottom];
}

// Differing pixels at the best offset (line boxes can sit a row or two apart). With `cap`, counting stops
// there: a reader only needs to know a glyph is at least that far.
function distance(a, b, cap = Infinity) {
  if (Math.abs(a.w - b.w) > 1) return Infinity;
  let best = cap;
  const H = Math.max(a.h, b.h) + 2, W = Math.max(a.w, b.w) + 1;
  for (let dy = -2; dy <= 2; dy++) for (let dx = -1; dx <= 1; dx++) {
    let n = 0;
    for (let y = -2; y < H && n < best; y++) for (let x = -1; x < W; x++) {
      const pa = y >= 0 && y < a.h && x >= 0 && x < a.w ? a.bits[y * a.w + x] : 0;
      const yb = y + dy, xb = x + dx, pb = yb >= 0 && yb < b.h && xb >= 0 && xb < b.w ? b.bits[yb * b.w + xb] : 0;
      if (pa !== pb) n++;
    }
    best = Math.min(best, n);
  }
  return best;
}

const nearest = (font, glyph, test, cap = Infinity) => Math.min(cap, ...Object.entries(font).filter(([char]) => test(char)).flatMap(([, known]) => known.map((g) => distance(g, glyph, cap))));

// Two neighbouring glyphs as one, with the empty columns between them.
export function join(a, b) {
  const w = a.w + b.gap + b.w, bits = new Uint8Array(w * a.h);
  for (let y = 0; y < a.h; y++) { bits.set(a.bits.subarray(y * a.w, (y + 1) * a.w), y * w); bits.set(b.bits.subarray(y * b.w, (y + 1) * b.w), y * w + a.w + b.gap); }
  return {w, h: a.h, bits, gap: a.gap, x0: a.x0};
}

/**
 * Pairs [glyph, char] of a line whose text is known. The text's spaces are the line's widest gaps
 * (measured: the space before "x1" can be 3 px, letters sit 1-2 apart), then each word is matched on
 * its own: equal counts pair up; one glyph too many is a character drawn in two pieces (the centre of
 * an "x" is often not seen), joined at the pair 1 px apart whose pieces span the most similar rows (the
 * halves of one letter do; a "(" next to a letter does not), then the narrowest. Other words are left out.
 */
export function alignLine(glyphs, text) {
  const words = text.trim().split(/\s+/), cuts = words.length - 1;
  const gaps = glyphs.map((g, i) => [i ? g.gap : -1, i]).sort((a, b) => b[0] - a[0]);
  if (glyphs.length < words.length || (cuts && (gaps[cuts - 1][0] < 3 || gaps[cuts - 1][0] <= gaps[cuts][0]))) return [];
  const starts = [0, ...gaps.slice(0, cuts).map(([, i]) => i).sort((a, b) => a - b), glyphs.length];
  return words.flatMap((word, k) => {
    let group = glyphs.slice(starts[k], starts[k + 1]);
    const chars = [...word];
    if (group.length === chars.length + 1) {
      const span = group.map(rows), score = (i) => Math.abs(span[i - 1][0] - span[i][0]) + Math.abs(span[i - 1][1] - span[i][1]);
      const close = group.map((g, i) => (i && g.gap <= 1 && group[i - 1].w + g.gap + g.w <= 7 ? [score(i), group[i - 1].w + g.gap + g.w, i] : null))
        .filter(Boolean).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      if (!close.length || (close[1] && close[1][0] === close[0][0] && close[1][1] === close[0][1])) return [];
      const i = close[0][2];
      group = [...group.slice(0, i - 1), join(group[i - 1], group[i]), ...group.slice(i + 1)];
    }
    return group.length === chars.length ? group.map((g, i) => [g, chars[i], k]) : [];
  });
}

/**
 * Learns the glyphs of a line whose text is known, word by word (alignLine), leaving out a word with a
 * glyph that already looks like another character (scenery can add one glyph and merge two, leaving the
 * count right but the word misaligned). Returns the number of glyphs paired.
 */
// Characters reaching the capitals' top row, and those starting lower; others (i, j, punctuation) unchecked.
const TALL = /[A-Z0-9bdfhklt()']/, SHORT = /[acemnorsuvwxz]/;

export function learnLine(font, mask, text) {
  const glyphs = glyphsOf(mask), top = Math.min(...glyphs.map((g) => rows(g)[0]));
  // A pair that cannot be right: a short glyph for a tall character or the other way round, or a width
  // unlike the character's learned ones (measured: a line missing one glyph and holding a split "x" paired
  // up evenly, teaching half an "x" as "x" and the other half as "1").
  const unlike = ([glyph, char]) => (TALL.test(char) && rows(glyph)[0] > top + 1) || (SHORT.test(char) && rows(glyph)[0] <= top + 1)
    || (font[char]?.length && !font[char].some((g) => Math.abs(g.w - glyph.w) <= 1));
  const aligned = alignLine(glyphs, text).filter((pair) => !unlike(pair));
  // A glyph that already looks like another character marks its word as misaligned; other words still teach.
  // So does one clearly closer to another character than to this one's learned variants.
  const wrong = new Set(aligned.filter(([glyph, char]) => {
    const other = nearest(font, glyph, (c) => c !== char), same = nearest(font, glyph, (c) => c === char);
    return (other <= 1 && other < same) || (Number.isFinite(same) && other + 2 <= same);
  }).map(([, , word]) => word));
  const pairs = aligned.filter(([, , word]) => !wrong.has(word));
  for (const [glyph, char] of pairs) {
    const known = font[char] ??= [];
    if (known.length < PER_CHAR && !known.some((g) => distance(g, glyph) <= 1)) { known.push({w: glyph.w, h: glyph.h, bits: glyph.bits}); caches.delete(font); }
  }
  return pairs.length;
}

/**
 * The text of a line from the learned font, "?" for a glyph that is unknown or too close to two
 * characters. Spaces come from gaps; a narrow "1" leaves a space-sized gap, so spaces between digits
 * and brackets are dropped.
 */
export function readLine(font, mask) {
  const seen = cache(font);
  const guess = (glyph) => {
    const key = `${glyph.w},${glyph.h},${glyph.bits.join('')}`;
    if (seen.has(key)) return seen.get(key);
    seen.set(key, nearestChar(glyph));
    return seen.get(key);
  };
  const nearestChar = (glyph) => {
    // Distances past the limit plus 2 cannot change the answer (the best must be within the limit and 2
    // ahead of the next), so counting stops there.
    let best = '?', d1 = Infinity, d2 = Infinity;
    const cap = Math.floor(Math.max(1, ink(glyph) * .15)) + 3;
    for (const [char, known] of Object.entries(font)) {
      const d = Math.min(...known.map((g) => distance(g, glyph, cap)));
      if (d < d1) { if (char !== best) d2 = d1; best = char; d1 = d; } else if (d < d2 && char !== best) d2 = d;
    }
    return d1 <= Math.max(1, ink(glyph) * .15) && d2 - d1 >= 2 ? best : null;
  };
  // Two characters drawn touching ("0)" in "(+10)", measured in fog) are one unknown glyph: the column
  // where both halves read as known characters splits it. Otherwise OCR guessed ")" as another digit.
  const split = (glyph) => {
    for (let c = 2; c <= glyph.w - 2; c++) {
      const part = (x0, x1) => { const w = x1 - x0, bits = new Uint8Array(w * glyph.h); for (let y = 0; y < glyph.h; y++) bits.set(glyph.bits.subarray(y * glyph.w + x0, y * glyph.w + x1), y * w); return {w, h: glyph.h, bits}; };
      const a = guess(part(0, c)), b = a && guess(part(c, glyph.w));
      if (b) return a + b;
    }
    return null;
  };
  let text = '';
  const glyphs = glyphsOf(mask);
  for (let i = 0; i < glyphs.length; i++) {
    // A character in two pieces (an "x" without its centre) reads as one when joined, tried when either
    // piece reads as nothing alone: "r" and "n" side by side also join into an "m".
    const glyph = glyphs[i], alone = guess(glyph), next = glyphs[i + 1];
    const joined = next?.gap <= 1 && (!alone || !guess(next)) ? guess(join(glyph, next)) : null;
    const char = joined ?? alone ?? split(glyph) ?? (mask.gray ? shade(font, mask, glyph) : null);
    if (joined) i++;
    text += (glyph.gap >= 4 && text ? ' ' : '') + (char ?? '?');
  }
  return text.replace(/(?<=[\d(+?])\s+(?=[\d)?,])/g, '');
}

// A glyph the mask lost strokes of, read from the line's brightness (`mask.gray`, one column and row wider):
// each learned shape predicts its strokes light and, where a stroke has no stroke down-right of it, that
// pixel dark (the drop shadow, which stays dark over white fog where the mask test fails); a text pixel of
// the mask the shape leaves unexplained costs too. Measured: see docs/local-tracker.md.
const STROKE = 60, LONE = 180;  // A stroke over its shadow: brighter by STROKE; a stroke over a stroke: LONE.
function shade(font, mask, glyph) {
  const gw = mask.width + 1, gh = mask.height + 1, at = (x, y) => (x >= 0 && y >= 0 && x < gw && y < gh ? mask.gray[y * gw + x] : -1);
  const bit = (x, y) => x >= 0 && y >= 0 && x < mask.width && y < mask.height && mask.bits[y * mask.width + x];
  let best = null, d1 = Infinity, d2 = Infinity;
  const cap = Math.floor(Math.max(1, ink(glyph) * .15)) + 3;  // As in readLine's guess.
  for (const [char, known] of Object.entries(font)) {
    let d = cap;
    for (const t of known) {
      if (Math.abs(t.w - glyph.w) > 1) continue;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -1; dx <= 1; dx++) {
        const ox = glyph.x0 + dx;
        let cost = 0;
        for (let y = 0; y < t.h && cost < d; y++) for (let x = 0; x < t.w; x++) {
          const X = ox + x, Y = dy + y;
          if (!t.bits[y * t.w + x]) { cost += bit(X, Y) ? 1 : 0; continue; }
          const v = at(X, Y), covered = x + 1 < t.w && y + 1 < t.h && t.bits[(y + 1) * t.w + x + 1];
          cost += v < 0 || (covered ? v < LONE : v - at(X + 1, Y + 1) < STROKE) ? 1 : 0;
        }
        // Text pixels of the glyph outside the shape's box.
        for (let y = 0; y < mask.height; y++) for (let x = glyph.x0; x < glyph.x0 + glyph.w; x++) {
          if ((x < ox || x >= ox + t.w || y < dy || y >= dy + t.h) && bit(x, y)) cost++;
        }
        d = Math.min(d, cost);
      }
    }
    if (d < d1) { if (char !== best) d2 = d1; best = char; d1 = d; } else if (d < d2 && char !== best) d2 = d;
  }
  return best && d1 <= Math.max(1, ink(glyph) * .15) && d2 - d1 >= 2 ? best : null;
}

// Costs for comparing a name's shapes with an item's letters (pixels that differ; see matchName).
const NAME = {cap: 12, unknown: 5, split: 1, stray: 7, missed: 7, touching: 6};

/**
 * The item a line's name shows, compared shape by shape with every item name (the way a reader knows the
 * word, not each letter): `masks` are the name parts of a message's samples. Each glyph is held against
 * each letter's learned variants; a letter in two pieces may be joined, a stray mark or a missed letter
 * costs NAME.stray / NAME.missed, a letter the font has not learned NAME.unknown. A name cut short ("...")
 * may end anywhere. Returns {item, cost, next, cut} (cost per letter of the best and the runner-up) or null.
 */
export function matchName(font, masks, items) {
  const chars = [...new Set(items.flatMap((item) => [...item.name.replace(/\s+/g, '')]))];
  const totals = new Map(), counts = new Map();
  let used = 0, anyCut = false;
  for (const mask of masks) {
    let glyphs = glyphsOf(mask);
    // Trailing dots of a cut name: narrow glyphs of a few pixels at the bottom.
    let cut = false;
    while (glyphs.length && glyphs.at(-1).w <= 2 && ink(glyphs.at(-1)) <= 4) { glyphs = glyphs.slice(0, -1); cut = true; }
    anyCut ||= cut;
    const G = glyphs.length;
    if (G < 3) continue;
    used++;
    const cost = (glyph) => Object.fromEntries(chars.map((c) => [c, font[c]?.length ? nearest(font, glyph, (x) => x === c, NAME.cap) : NAME.unknown]));
    const single = glyphs.map(cost), pair = glyphs.slice(1).map((g, i) => (g.gap <= 1 ? cost(join(glyphs[i], g)) : null));
    for (const item of items) {
      const letters = [...item.name.replace(/\s+/g, '')], C = letters.length;
      if (cut ? C < G - 3 : Math.abs(C - G) > Math.max(3, G * .3)) continue;
      const dp = Array.from({length: G + 1}, () => new Float64Array(C + 1).fill(Infinity));
      dp[0][0] = 0;
      for (let i = 0; i <= G; i++) for (let j = 0; j <= C; j++) {
        const here = dp[i][j];
        if (here === Infinity) continue;
        if (i < G && j < C) dp[i + 1][j + 1] = Math.min(dp[i + 1][j + 1], here + single[i][letters[j]]);
        if (i + 1 < G && j < C && pair[i]) dp[i + 2][j + 1] = Math.min(dp[i + 2][j + 1], here + pair[i][letters[j]] + NAME.split);
        if (i < G && j + 1 < C) dp[i + 1][j + 2] = Math.min(dp[i + 1][j + 2], here + NAME.touching);
        if (i < G) dp[i + 1][j] = Math.min(dp[i + 1][j], here + NAME.stray);
        if (j < C) dp[i][j + 1] = Math.min(dp[i][j + 1], here + NAME.missed);
      }
      // A cut name is a prefix: it may end at any letter after most of the glyphs.
      let best = dp[G][C] / C;
      if (cut) for (let j = Math.max(1, G - 3); j <= C; j++) best = Math.min(best, dp[G][j] / j);
      totals.set(item, (totals.get(item) ?? 0) + best); counts.set(item, (counts.get(item) ?? 0) + 1);
    }
  }
  // Only names compared in every sample, by their mean cost per letter.
  const ranked = [...totals].filter(([item]) => counts.get(item) === used).map(([item, total]) => [item, total / used]).sort((a, b) => a[1] - b[1]);
  return ranked.length ? {item: ranked[0][0], cost: ranked[0][1], next: ranked[1]?.[1] ?? Infinity, cut: anyCut} : null;
}

// The pickup-message font, learned on the player's own machine from lines whose text is known (read by
// OCR and confirmed, or completed from the item list). No game font data ships with msxp. A font is
// {char: [glyph, ...]}, each glyph {w, h, bits} as seen in a line mask; scenery behind the see-through
// text changes a few pixels, so reading takes the nearest learned glyph rather than an exact match.
import {lineWords} from './pickups.js';

const PER_CHAR = 6;  // Variants kept per character.

// Glyphs of a line mask in order, each with the empty columns before it (a space is 4 or more).
export function glyphsOf(mask) {
  const out = [];
  let end = null;
  for (const word of lineWords(mask)) for (const {x0, x1} of word.glyphs) {
    const w = x1 - x0, bits = new Uint8Array(w * mask.height);
    for (let y = 0; y < mask.height; y++) bits.set(mask.bits.subarray(y * mask.width + x0, y * mask.width + x1), y * w);
    out.push({w, h: mask.height, bits, gap: end === null ? 0 : x0 - end});
    end = x1;
  }
  return out;
}

const ink = (g) => g.bits.reduce((sum, b) => sum + b, 0);

// Differing pixels at the best offset (line boxes can sit a row or two apart).
function distance(a, b) {
  if (Math.abs(a.w - b.w) > 1) return Infinity;
  let best = Infinity;
  for (let dy = -2; dy <= 2; dy++) for (let dx = -1; dx <= 1; dx++) {
    let n = 0;
    for (let y = -2; y < Math.max(a.h, b.h) + 2; y++) for (let x = -1; x < Math.max(a.w, b.w) + 1; x++) {
      const pa = y >= 0 && y < a.h && x >= 0 && x < a.w ? a.bits[y * a.w + x] : 0;
      const yb = y + dy, xb = x + dx, pb = yb >= 0 && yb < b.h && xb >= 0 && xb < b.w ? b.bits[yb * b.w + xb] : 0;
      if (pa !== pb) n++;
    }
    best = Math.min(best, n);
  }
  return best;
}

const nearest = (font, glyph, test) => Math.min(Infinity, ...Object.entries(font).filter(([char]) => test(char)).flatMap(([, known]) => known.map((g) => distance(g, glyph))));

/**
 * Learns each glyph of a line whose text is known; nothing unless glyphs and characters line up, and
 * nothing if a glyph already looks like another character (scenery can add one glyph and merge two,
 * leaving the count right but the line misaligned).
 */
export function learnLine(font, mask, text) {
  const chars = [...text.replace(/\s+/g, '')], glyphs = glyphsOf(mask);
  if (glyphs.length !== chars.length) return false;
  if (glyphs.some((glyph, i) => {
    const other = nearest(font, glyph, (char) => char !== chars[i]);
    return other <= 1 && other < nearest(font, glyph, (char) => char === chars[i]);
  })) return false;
  glyphs.forEach((glyph, i) => {
    const known = font[chars[i]] ??= [];
    if (known.length < PER_CHAR && !known.some((g) => distance(g, glyph) <= 1)) known.push({w: glyph.w, h: glyph.h, bits: glyph.bits});
  });
  return true;
}

/**
 * The text of a line from the learned font, "?" for a glyph that is unknown or too close to two
 * characters. Spaces come from gaps; a narrow "1" leaves a space-sized gap, so spaces between digits
 * and brackets are dropped.
 */
export function readLine(font, mask) {
  let text = '';
  for (const glyph of glyphsOf(mask)) {
    let best = '?', d1 = Infinity, d2 = Infinity;
    for (const [char, known] of Object.entries(font)) {
      const d = Math.min(...known.map((g) => distance(g, glyph)));
      if (d < d1) { if (char !== best) d2 = d1; best = char; d1 = d; } else if (d < d2 && char !== best) d2 = d;
    }
    const sure = d1 <= Math.max(1, ink(glyph) * .15) && d2 - d1 >= 2;
    text += (glyph.gap >= 4 && text ? ' ' : '') + (sure ? best : '?');
  }
  return text.replace(/(?<=[\d(+?])\s+(?=[\d)?,])/g, '');
}

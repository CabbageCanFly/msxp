// Exact glyph templates learned on the player's own machine. A native window capture draws the HUD's
// bitmap font identically every time, so once a glyph has been seen in a confirmed reading, the same
// pixels are the same character. No game font data ships with msxp; templates live only in this browser.
import {channel, crop, otsu} from './hud.js';

// Split a field into glyphs: runs of inked columns inside the field's ink band. Keys are exact bitmaps.
export function segment(frame, box) {
  const part = crop(frame, box);
  if (part.width < 3 || part.height < 3) return null;
  const gray = channel(part, 'max'), threshold = Math.min(200, Math.max(110, otsu(gray)));
  const ink = (x, y) => gray[y * part.width + x] > threshold;
  let top = -1, bottom = -1;
  for (let y = 0; y < part.height; y++) for (let x = 0; x < part.width; x++) if (ink(x, y)) { if (top < 0) top = y; bottom = y; break; }
  if (top < 0 || bottom - top > 24) return null;
  const glyphs = [];
  let run = null;
  for (let x = 0; x <= part.width; x++) {
    let any = false;
    if (x < part.width) for (let y = top; y <= bottom; y++) if (ink(x, y)) { any = true; break; }
    if (any) { if (!run) run = {x0: x}; continue; }
    if (run) {
      const rows = [];
      for (let y = top; y <= bottom; y++) { let bits = ''; for (let c = run.x0; c < x; c++) bits += ink(c, y) ? '1' : '0'; rows.push(bits); }
      glyphs.push({key: rows.join('/'), x0: run.x0, x1: x});
      run = null;
    }
  }
  return glyphs.length && glyphs.length <= 24 ? {glyphs, height: bottom - top + 1} : null;
}

// Text from known glyphs only; any unknown or conflicted glyph means no template reading.
export function read(segmented, templates) {
  if (!segmented || !templates) return null;
  let text = '';
  for (const {key} of segmented.glyphs) {
    const char = templates[key];
    if (!char || char === '?') return null;
    text += char;
  }
  return text;
}

// The HUD's own spelling of a confirmed value: thousands commas and a two-decimal percentage.
export const displayed = (exp, bp) => ({number: exp.toLocaleString('en-US'), percent: `${Math.floor(bp / 100)}.${String(bp % 100).padStart(2, '0')}%`});

/**
 * Learn glyphs from a confirmed reading. Only when the glyph count equals the character count is each
 * glyph assigned; a bitmap ever seen as two different characters is poisoned ('?') and never used.
 * Returns the number of new templates, or null when the field cannot be aligned.
 */
export function learn(templates, segmented, text) {
  if (!segmented || segmented.glyphs.length !== text.length) return null;
  let added = 0;
  segmented.glyphs.forEach(({key}, i) => {
    const char = text[i], known = templates[key];
    if (known === undefined) { templates[key] = char; added++; }
    else if (known !== char) templates[key] = '?';
  });
  return added;
}

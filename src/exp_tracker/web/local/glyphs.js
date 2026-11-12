// Exact glyph templates. A native window capture draws the HUD's bitmap font identically every time, so
// once a glyph has been seen in a confirmed reading, the same pixels are the same character. HUD_GLYPHS
// ship with the page; templates learned on the player's machine add to them.
import {bracketColour, channel, crop, otsu} from './hud.js';

// The HUD's digits in the game's own pixels (a native window, or a stretched one read unstretched), as
// learned from confirmed readings and checked by eye: the EXP number and percentage, and the level badge's
// digits 0-9. The first scan reads with these, at any level.
export const HUD_GLYPHS = {
  '01110/10001/10001/10001/10001/10001/01110': '0', '01/11/01/01/01/01/01': '1', '01110/10001/00001/00010/00100/01000/11111': '2',
  '01110/10001/00001/00110/00001/10001/01110': '3', '00010/00110/01010/10010/11111/00010/00010': '4', '11111/10000/10000/01110/00001/10001/01110': '5',
  '01110/10001/10000/11110/10001/10001/01110': '6', '11111/00001/00001/00001/00010/00100/00100': '7', '01110/10001/10001/01110/10001/10001/01110': '8',
  '01110/10001/10001/01111/00001/10001/01110': '9', '00/00/00/00/00/01/10': ',', '0/0/0/0/0/0/1': '.', '0100001/1010010/0100100/0001000/0010010/0100101/1000010': '%',
  '011/111/011/011/011/011/000': '1', '011/111/011/011/011/011/011': '1', '11/11/11/11/11/11/11': '1',
  '0111110/1100011/0000011/0011110/0110000/1100000/1111110': '2', '0111110/1100011/0000011/0011110/0110000/1100000/1111111': '2',
  '0111110/0100011/0000011/0011110/0110000/1100000/1111110': '2',
  // The rest of the badge digits, learned on levels 3 to 10 and checked by eye.
  '0111110/1100011/1100011/1100011/1100011/1100011/0111110': '0', '0111110/1100011/0000011/0001110/0000011/0100011/0011110': '3',
  '0001110/0011110/0110110/1100110/1111111/0000110/0000110': '4', '1111100/1100000/1100000/0111110/0000011/0100011/0011110': '5',
  '0111110/1100010/1100000/1111110/1100011/1100011/0111110': '6', '111111/000011/000110/001100/001100/011000/011000': '7',
  '0111110/1100011/1100011/0111110/1100011/1100011/0111110': '8', '0111110/1100011/1100011/0111111/0000011/0100011/0011110': '9',
  // EXP digits in a box one row taller (an empty bottom row).
  '01/11/01/01/01/01/01/00': '1', '01110/10001/10001/01110/10001/10001/01110/00000': '8', '00/00/00/00/00/01/10/00': ',',
  '11111/10000/10000/01110/00001/10001/01110/00000': '5',
};

// Split a field into glyphs: runs of inked columns inside the field's ink band. Keys are exact bitmaps.
// 'max' suits white text and green brackets on the dark bar; 'min' keeps only white digits on orange tiles.
export function segment(frame, box, mode = 'max') {
  const part = crop(frame, box);
  if (part.width < 3 || part.height < 3) return null;
  const gray = channel(part, mode), threshold = mode === 'min' ? 170 : Math.min(200, Math.max(110, otsu(gray))), d = part.data;
  const green = (i) => bracketColour(d[i * 4], d[i * 4 + 1], d[i * 4 + 2]);
  const ink = (x, y) => gray[y * part.width + x] > threshold && !green(y * part.width + x);
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

// One exact bitmap for a whole text line (a name or job): identity by pixels, not by OCR.
export function lineKey(frame, box) {
  const part = crop(frame, box), gray = channel(part, 'min'), rows = [];
  for (let y = 0; y < part.height; y++) { let bits = ''; for (let x = 0; x < part.width; x++) bits += gray[y * part.width + x] > 170 ? '1' : '0'; rows.push(bits); }
  return `${part.width}x${part.height}:` + rows.join('/');
}

// Without blank top and bottom rows: compares a digit seen in a name line with one learned from EXP.
export const trimKey = (key) => key.split('/').filter((row) => row.includes('1')).join('/');

// Letters of the panel font, learned from verified text: a typed rename (authoritative: it replaces a
// conflicting letter) or a job line that matched the known job list (a conflict poisons the bitmap).
// Spaces are gaps, not glyphs. Nothing is learned unless glyph and character counts match.
export function learnLetters(letters, keys, text, {authoritative = false} = {}) {
  const chars = [...text.replace(/\s+/g, '')];
  if (!keys || keys.length !== chars.length) return 0;
  let changed = 0;
  keys.forEach((key, i) => {
    const known = letters[key], char = chars[i];
    if (known === char) return;
    letters[key] = known === undefined || authoritative ? char : '?';
    changed++;
  });
  return changed;
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

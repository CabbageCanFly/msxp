// Small-field OCR of the located HUD. `engine.read(bytes, field)` returns {text, confidence};
// the browser passes a tesseract.js worker, the Node fixture check passes its own.
import {binarize, brackets, channel, crop, inkRows, labelEnd, magnification, orangeBox, otsu, panelLines, pgm} from './hud.js';
import {parseExp, parseLevel} from './exp.js';
import {lineKey, read as readGlyphs, segment, trimKey} from './glyphs.js';

// The thin 1-pixel brackets confuse Tesseract ('[' reads as '1'), so they are located by colour and
// the number and percentage on either side are read separately.
export const PARAMS = {
  number: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: '0123456789,.'},
  percent: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: '0123456789.%'},
  level: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: '0123456789'},
  name: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'},
  job: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz (),'},
};

// Two binarized variants per field at neighbouring magnifications; both must agree for EXP.
export function variants(frame, box, field, smooth = false) {
  const part = crop(frame, box);
  if (part.width < 4 || part.height < 4) return [];
  const level = field === 'level';
  const gray = channel(part, level ? 'min' : 'max');
  const scale = magnification(part.height * (level ? .7 : .8)), threshold = Math.max(otsu(gray), level ? 120 : 110);
  return [scale, scale + 1].map((s) => ({threshold, scale: s, image: binarize(gray, part.width, part.height, threshold, s, 8, smooth)}));
}

// Fit the calibrated boxes to this frame: orange tiles for the level, the two brackets for EXP.
export function fieldBoxes(frame, regions) {
  const out = {exp: null, number: null, percent: null, level: null};
  if (regions.exp) {
    // Without both brackets the field is hidden, covered or clipped: never read a partial line.
    const found = brackets(frame, regions.exp);
    if (found) {
      const [open, close] = found, {y0, y1} = regions.exp, pad = Math.max(1, Math.round((y1 - y0) * .1));
      // Skip the EXP label if the box holds it: digits start after its last column above the digit band.
      const band = inkRows(frame, {x0: open.x1, y0, x1: close.x0, y1});
      const label = band && labelEnd(frame, {x0: regions.exp.x0, x1: open.x0}, band.top);
      const x0 = label === null || label === undefined ? regions.exp.x0 : label + 1;
      if (open.x0 - x0 >= 4) {
        out.number = {x0, y0, x1: open.x0, y1};
        out.percent = {x0: open.x1, y0, x1: close.x0, y1};
        out.exp = {x0: regions.exp.x0, y0, x1: close.x1 + pad, y1};
      }
    }
  }
  if (regions.level) {
    const b = orangeBox(frame, regions.level);
    if (b) {
      out.level = {x0: b.x0 - 1, y0: b.y0 - 1, x1: b.x1 + 1, y1: b.y1 + 1};
      // The job and name lines sit at a fixed place beside the badge.
      Object.assign(out, panelLines(frame, b) ?? {});
    }
  }
  return out;
}

async function readField(engine, frame, box, field, raw, smooth) {
  const texts = [];
  for (const {threshold, scale, image} of variants(frame, box, field, smooth)) {
    const {text, confidence} = await engine.read(pgm(image), field);
    const clean = text.replace(/\s+/g, '');
    raw.push({field, smooth, threshold, scale, text: clean, confidence});
    texts.push(clean);
  }
  return texts;
}

// One EXP pair from one preprocessing pass, or a reason. Both magnifications must parse identically.
async function readExp(engine, frame, boxes, raw, smooth) {
  const numbers = await readField(engine, frame, boxes.number, 'number', raw, smooth);
  const percents = await readField(engine, frame, boxes.percent, 'percent', raw, smooth);
  // Brackets were seen in pixels; digits come from OCR.
  const values = numbers.map((number, i) => parseExp(`${number}[${percents[i]}]`));
  if (!values.some(Boolean)) return {reason: 'cannot_parse_exp'};
  if (values.some((v) => !v) || new Set(values.map((v) => `${v.exp}/${v.bp}`)).size > 1) return {reason: 'exp_variants_disagree'};
  return {value: values[0]};
}

/**
 * Read EXP and level. Learned glyph templates first (exact pixels, no OCR); otherwise a crisp (native)
 * Tesseract pass, then a smooth pass for scaled HUDs. Within a pass, variants must agree; a disagreement
 * is never resolved by picking the higher score. The level badge is read by Tesseract; a missing level
 * stays null for the EXP table to judge. `segments` are returned so a confirmed reading can teach glyphs.
 */
export async function readHud(engine, frame, regions, templates = null) {
  const boxes = fieldBoxes(frame, regions), raw = {exp: [], level: []};
  const result = {status: 'ok', raw, boxes, exp: null, bp: null, level: null, source: null, segments: null};
  if (!boxes.exp) return {...result, status: 'no_hud', reason: 'exp_brackets_not_visible'};
  const segments = result.segments = {number: segment(frame, boxes.number), percent: segment(frame, boxes.percent)};
  let read = null, smooth = false;
  const number = readGlyphs(segments.number, templates), percent = readGlyphs(segments.percent, templates);
  if (number !== null && percent !== null) {
    const value = parseExp(`${number}[${percent}]`);
    raw.exp.push({field: 'glyphs', text: `${number}[${percent}]`});
    if (value) { read = {value}; result.source = 'glyphs'; }
  }
  if (!read) {
    for (smooth of [false, true]) {
      read = await readExp(engine, frame, boxes, raw.exp, smooth);
      if (read.value) break;
    }
    result.source = 'ocr';
  }
  if (!read.value) return {...result, status: read.reason === 'cannot_parse_exp' ? 'unreadable' : 'ambiguous', reason: read.reason};
  const value = read.value;
  if (value.exp === 0 && value.bp !== 0) return {...result, status: 'invalid', reason: 'zero_exp_with_nonzero_percentage'};
  result.exp = value.exp; result.bp = value.bp; result.smooth = smooth;
  // Name and job are compared as exact bitmaps every scan (well under a millisecond); OCR runs only
  // when a new bitmap needs a label (readIdentity).
  const glyphKeys = (box) => segment(frame, box, 'min')?.glyphs.map((g) => trimKey(g.key)) ?? null;
  result.identity = boxes.name ? {nameKey: lineKey(frame, boxes.name), nameGlyphs: glyphKeys(boxes.name),
    jobKey: boxes.job ? lineKey(frame, boxes.job) : null, jobGlyphs: boxes.job ? glyphKeys(boxes.job) : null} : null;
  if (boxes.level) {
    const levelSegments = result.levelSegments = segment(frame, boxes.level, 'min');
    const known = parseLevel(readGlyphs(levelSegments, templates) ?? '');
    if (known !== null) { result.level = known; result.levelSource = 'glyphs'; return result; }
    const levels = new Set((await readField(engine, frame, boxes.level, 'level', raw.level, smooth)).map(parseLevel).filter((v) => v !== null));
    if (levels.size > 1) return {...result, status: 'ambiguous', reason: 'conflicting_level_variants'};
    result.level = levels.size ? [...levels][0] : null;
    result.levelSource = 'ocr';
  }
  return result;
}

// OCR text of one panel line at several native magnifications: the text at least two agree on (and, when
// given, with exactly `length` characters), else null.
async function lineText(engine, frame, box, field, length = null) {
  const part = crop(frame, {x0: box.x0 - 2, y0: box.y0 - 2, x1: box.x1 + 2, y1: box.y1 + 2}), gray = channel(part, 'min'), votes = new Map();
  for (const scale of [3, 4, 2, 5]) {
    const text = (await engine.read(pgm(binarize(gray, part.width, part.height, 170, scale)), field)).text.trim().replace(/\s+/g, ' ');
    if (!text || length !== null && text.length !== length) continue;
    votes.set(text, (votes.get(text) || 0) + 1);
    if (votes.get(text) >= 2) return text;
  }
  return null;
}

// A name read at four magnifications. Pixel-identical glyphs are the same letter, so votes are pooled
// per glyph bitmap across every reading with the right length: one OCR slip (b read as h in a name
// with two b's) is outvoted. Needs at least two readings of the right length.
async function votedName(engine, frame, box, glyphs) {
  const part = crop(frame, {x0: box.x0 - 2, y0: box.y0 - 2, x1: box.x1 + 2, y1: box.y1 + 2}), gray = channel(part, 'min');
  const votes = new Map();
  let readings = 0;
  for (const scale of [3, 4, 2, 5]) {
    const text = (await engine.read(pgm(binarize(gray, part.width, part.height, 170, scale)), 'name')).text.replace(/\s+/g, '');
    if (text.length !== glyphs.length) continue;
    readings++;
    [...text].forEach((char, i) => {
      const tally = votes.get(glyphs[i].key) ?? new Map();
      tally.set(char, (tally.get(char) || 0) + 1); votes.set(glyphs[i].key, tally);
    });
  }
  if (readings < 2) return null;
  return glyphs.map((g) => [...votes.get(g.key)].sort((a, b) => b[1] - a[1])[0][0]).join('');
}

const letters = (s) => s.toLowerCase().replace(/[^a-z]/g, '');
function distance(a, b) {
  const row = Array.from({length: b.length + 1}, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let previous = row[0]; row[0] = i;
    for (let j = 1; j <= b.length; j++) { const kept = row[j]; row[j] = Math.min(row[j] + 1, row[j - 1] + 1, previous + (a[i - 1] === b[j - 1] ? 0 : 1)); previous = kept; }
  }
  return row[b.length];
}

// The closest known job (letters only, at most two edits), or null when two jobs are equally close.
export function matchJob(text, jobs) {
  if (!text) return null;
  const ranked = jobs.map((job) => [distance(letters(text), letters(job)), job]).sort((a, b) => a[0] - b[0]);
  return ranked[0][0] <= 2 && ranked[0][0] < (ranked[1]?.[0] ?? Infinity) ? ranked[0][1] : null;
}

/**
 * Labels for a new name or job bitmap. Known glyphs come first: letters learned from renames and job
 * lines, and digits learned from the EXP bar. A name whose glyphs are all known needs no OCR; otherwise
 * the pooled OCR vote fills the unknown ones, and an OCR '0' that is not the learned zero is the letter O.
 */
export async function readIdentity(engine, frame, boxes, templates, jobs, letters = {}) {
  const out = {name: null, job: null};
  if (boxes.name) {
    const glyphs = segment(frame, boxes.name, 'min')?.glyphs;
    const known = {};
    for (const [key, char] of Object.entries(templates ?? {})) if (/^\d$/.test(char)) known[trimKey(key)] = char;
    Object.assign(known, letters);  // A taught letter wins over a digit with the same pixels.
    const fixed = glyphs?.map((g) => { const char = known[trimKey(g.key)]; return char && char !== '?' ? char : null; });
    let name = fixed?.every(Boolean) ? fixed.join('') : glyphs ? await votedName(engine, frame, boxes.name, glyphs) : null;
    if (name && glyphs?.length === name.length) {
      const zero = Object.values(known).includes('0');
      name = [...name].map((char, i) => fixed[i] ?? (char === '0' && zero ? 'O' : char)).join('');
    }
    out.name = name && /^[A-Za-z0-9]{2,13}$/.test(name) ? name : null;
  }
  if (boxes.job) out.job = matchJob(await lineText(engine, frame, boxes.job, 'job'), jobs);
  return out;
}

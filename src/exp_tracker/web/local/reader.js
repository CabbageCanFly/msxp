// Small-field OCR of the located HUD. `engine.read(bytes, field)` returns {text, confidence};
// the browser passes a tesseract.js worker, the Node fixture check passes its own.
import {binarize, bracketColour, brackets, channel, crop, inkRows, labelEnd, magnification, orangeBox, otsu, panelLines, pgm} from './hud.js';
import {consistency, parseExp, parseLevel, parsePercent} from './exp.js';
import {lineKey, read as readGlyphs, readSoftField, segment, trimKey} from './glyphs.js';

// The thin 1-pixel brackets confuse Tesseract ('[' reads as '1'), so they are located by colour and
// the number and percentage on either side are read separately.
export const PARAMS = {
  number: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: '0123456789,.'},
  percent: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: '0123456789.%'},
  percentGlyph: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: '0123456789.%'},
  numberWord: {tessedit_pageseg_mode: '8', tessedit_char_whitelist: '0123456789,.'},
  percentWord: {tessedit_pageseg_mode: '8', tessedit_char_whitelist: '0123456789.%'},
  amount: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: '0123456789,.()+'},
  level: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: '0123456789'},
  // A lone badge digit: line mode reads nothing, single-word mode reads it (measured live: "4" at 4 of 5 scales).
  levelWord: {tessedit_pageseg_mode: '8', tessedit_char_whitelist: '0123456789'},
  name: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'},
  job: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz (),'},
  // Pickup messages: "You have gained mesos (+10)", "Orange Mushro... x1 earned. (Etc)".
  message: {tessedit_pageseg_mode: '7', tessedit_char_whitelist: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,()+:'-"},
  messageWord: {tessedit_pageseg_mode: '8', tessedit_char_whitelist: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,()+:'-"},
};

// Two binarized variants per field at neighbouring magnifications; both must agree for EXP.
export function variants(frame, box, field, smooth = false, {scale: scaleOverride = null, threshold: thresholdOverride = null, soft = false} = {}) {
  const part = crop(frame, box);
  if (part.width < 4 || part.height < 4) return [];
  const level = field.startsWith('level');
  const gray = channel(part, level ? 'min' : 'max');
  const scale = scaleOverride ?? magnification(part.height * (level ? .7 : .8));
  // Safari (`soft`): a softened decimal is lost when the smooth pass reuses the digit-heavy Otsu threshold. Not
  // elsewhere: on Twitch frames 125 made the smooth pass misread (65.59% as "65.594.") where Otsu read it.
  const threshold = thresholdOverride ?? (soft && !level && smooth ? 125 : Math.max(otsu(gray), level ? 120 : 110));
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
      // Cut both fields to the digit row itself: a box that is a few pixels too tall (after a re-detect)
      // would otherwise take in the panel's border and stop matching the learned glyphs.
      const top = band ? band.top - 1 : y0, bottom = band ? band.bottom + 2 : y1;
      // No room before "[" is a percentage-only field (no number box); readHud checks the box's ink otherwise.
      out.number = open.x0 - x0 >= 4 ? {x0, y0: top, x1: open.x0, y1: bottom} : null;
      out.percent = {x0: open.x1, y0: top, x1: close.x0, y1: bottom};
      out.exp = {x0: regions.exp.x0, y0, x1: close.x1 + pad, y1};
      out.band = band;
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

async function readField(engine, frame, box, field, raw, smooth, word = false, options = {}) {
  const texts = [];
  for (const {threshold, scale, image} of variants(frame, box, field, smooth, options)) {
    const {text, confidence} = await engine.read(pgm(image), word ? `${field}Word` : field);
    const clean = text.replace(/\s+/g, '');
    raw.push({field, smooth, word, threshold, scale, text: clean, confidence});
    texts.push(clean);
  }
  return texts;
}

// One EXP pair from one preprocessing pass, or a reason. Both magnifications must parse identically,
// unless `fits` (the EXP table, for a known level) can pick: then the number and percentage reads that
// fit it, in any pairing. Measured on a stretched 1920x1080 HUD: one pass read "7.358" twice but the
// percentage as "30.15%" and "0.15%"; the next read "2.358" twice. Only 7,358 fits 30.15% at its level.
async function readExp(engine, frame, boxes, raw, smooth, fits = null, word = false, options = {}) {
  const numbers = options.knownNumber != null ? [options.knownNumber, options.knownNumber]
    : await readField(engine, frame, boxes.number, 'number', raw, smooth, word, options);
  const percents = options.knownPercent != null ? [options.knownPercent, options.knownPercent]
    : await readField(engine, frame, boxes.percent, 'percent', raw, smooth, word, options);
  // Both passes saw this same frame: a number from one can fit a percentage from the other.
  return fits ? pickExp(raw.filter((r) => r.field === 'number').map((r) => r.text),
    raw.filter((r) => r.field === 'percent').map((r) => r.text), fits) : pickExp(numbers, percents);
}

// Keep exact known digits when Safari's whole-line OCR drops one; two agreeing reads label each unknown.
async function readPercentGlyphs(engine, frame, box, segmented, templates, raw) {
  const chars = segmented?.glyphs.map((g) => templates?.[g.key]);
  if (!chars?.some((c) => /^\d$/.test(c ?? ''))) return null;
  for (let i = 0; i < chars.length; i++) {
    if (chars[i] === '?') return null;
    if (chars[i]) continue;
    const glyph = segmented.glyphs[i], part = {...box, x0: box.x0 + glyph.x0, x1: box.x0 + glyph.x1};
    for (const smooth of [false, true]) {
      const texts = await readField(engine, frame, part, 'percentGlyph', raw, smooth, false, {soft: true});
      if (texts.length === 2 && texts[0] === texts[1] && /^[0-9.%]$/.test(texts[0])) { chars[i] = texts[0]; break; }
    }
    if (!chars[i]) return null;
  }
  return chars.join('');
}

// The EXP pair from one pass's OCR texts (number and percentage, one per magnification), or a reason.
export function pickExp(numbers, percents, fits = null) {
  // Brackets were seen in pixels; digits come from OCR.
  if (fits) {
    const pairs = numbers.flatMap((number) => percents.map((percent) => parseExp(`${number}[${percent}]`))).filter(Boolean);
    if (!pairs.length) return {reason: 'cannot_parse_exp'};
    const valid = new Map(pairs.filter((v) => fits(v.exp, v.bp)).map((v) => [`${v.exp}/${v.bp}`, v]));
    if (valid.size > 1) return {reason: 'exp_variants_disagree'};
    return valid.size ? {value: valid.values().next().value} : {reason: 'exp_disagrees_with_table'};
  }
  const values = numbers.map((number, i) => parseExp(`${number}[${percents[i]}]`));
  if (!values.some(Boolean)) return {reason: 'cannot_parse_exp'};
  if (values.some((v) => !v) || new Set(values.map((v) => `${v.exp}/${v.bp}`)).size > 1) return {reason: 'exp_variants_disagree'};
  return {value: values[0]};
}

/**
 * Read EXP and level. Learned glyph templates first (exact pixels, no OCR); otherwise a crisp (native)
 * Tesseract pass, then a smooth pass and word-mode fallback for scaled HUDs. Within a pass, variants must agree, unless the EXP
 * table (`table`) can judge them against the level read from the badge or `previousLevel`: then only a
 * reading that fits it is taken. A disagreement is never resolved by picking the higher score. A missing
 * level stays null for the EXP table to judge. `segments` are returned so a confirmed reading can teach glyphs.
 */
export async function readHud(engine, frame, regions, templates = null, {table = null, previousLevel = null, safari = false} = {}) {
  const boxes = fieldBoxes(frame, regions), raw = {exp: [], level: []};
  const result = {status: 'ok', raw, boxes, exp: null, bp: null, level: null, source: null, segments: null};
  if (!boxes.exp) return {...result, status: 'no_hud', reason: 'exp_brackets_not_visible'};
  const segments = result.segments = {number: boxes.number && segment(frame, boxes.number), percent: segment(frame, boxes.percent)};
  let read = null, smooth = false, early = null;
  if (!boxes.number || boxes.band && !hasDigits(frame, boxes.number, boxes.band)) {
    // A percentage-only HUD ("EXP. [78.63%]", common at high levels): its level comes from the badge alone.
    read = await readPercentOnly(engine, frame, boxes.percent, segments.percent, templates, raw.exp, safari);
    result.percentOnly = true; result.source = read.source ?? null; smooth = read.smooth ?? false;
  } else {
    const first = segments.number?.glyphs[0], next = segments.number?.glyphs[1];
    const trimmedNumber = boxes.number.x0 > regions.exp.x0 && first?.x0 === 0 && next
      && first.key.split('/').slice(Math.ceil(segments.number.height / 2)).every((row) => !row.includes('1'))
      ? {...boxes.number, x0: boxes.number.x0 + next.x0} : null;
    let number = readGlyphs(segments.number, templates);
    let percent = readGlyphs(segments.percent, templates);
    if (safari) {
      const softNumber = readSoftField(frame, trimmedNumber ?? boxes.number, boxes.band, 'number', templates);
      const softPercent = readSoftField(frame, boxes.percent, boxes.band, 'percent', templates);
      if (softNumber?.ambiguous || softPercent?.ambiguous) return {...result, status: 'ambiguous', reason: 'conflicting_font_variants'};
      number = softNumber?.text ?? number;
      percent = softPercent?.text ?? percent;
    }
    if (safari && number === null && trimmedNumber) {
      // The label fragment changes the ink band and threshold; re-segment before giving up on exact glyphs.
      const clean = segment(frame, trimmedNumber);
      const known = readGlyphs(clean, templates);
      if (known !== null) {
        number = known; segments.number = clean; smooth = true;
        percent ??= await readPercentGlyphs(engine, frame, boxes.percent, segments.percent, templates, raw.exp);
      }
    }
    if (number !== null && percent !== null) {
      const value = parseExp(`${number}[${percent}]`);
      raw.exp.push({field: 'glyphs', text: `${number}[${percent}]`});
      if (value) { read = {value}; result.source = raw.exp.some((r) => r.field === 'percentGlyph') ? 'ocr' : 'glyphs'; }
    }
    if (!read) {
      // Exact Safari glyphs are stronger evidence than whole-field OCR; read only unknown fields.
      const options = {soft: safari, knownNumber: safari ? number : null, knownPercent: safari ? percent : null};
      if (options.knownNumber !== null) raw.exp.push({field: 'number', text: number, glyphs: true});
      if (options.knownPercent !== null) raw.exp.push({field: 'percent', text: percent, glyphs: true});
      // The badge first, so the EXP table can choose among the OCR readings.
      early = table && boxes.level ? await readLevelBadge(engine, frame, boxes.level, templates, raw.level, false) : null;
      const levels = [early?.level, previousLevel].filter((level) => level != null);
      const fits = levels.length ? (exp, bp) => levels.some((level) => consistency(table, level, exp, bp) === 'consistent') : null;
      for (smooth of [false, true]) {
        read = await readExp(engine, frame, boxes, raw.exp, smooth, fits, false, options);
        if (read.value) break;
      }
      // Safari's soft, touching digits can make line mode drop a leading digit; word mode keeps the whole field.
      // Safari only: elsewhere these extra passes cost 4-8 OCR calls on every failing scan.
      if (!read.value && safari) read = await readExp(engine, frame, boxes, raw.exp, true, fits, true, options);
      // A blurred EXP label can leave a short upper fragment at the number's left edge.
      if (!read.value && safari && trimmedNumber) {
        // Smaller images keep softened, touching digits apart; preserve all earlier accepted reads.
        read = await readExp(engine, frame, {...boxes, number: trimmedNumber}, raw.exp, true, fits, false, {...options, scale: 3});
      }
      if (!read.value && safari) {
        const percent = options.knownPercent ?? await readPercentGlyphs(engine, frame, boxes.percent, segments.percent, templates, raw.exp);
        if (percent !== null) {
          raw.exp.push({field: 'percent', text: percent, glyphs: true});
          if (fits) read = pickExp(raw.exp.filter((r) => r.field === 'number').map((r) => r.text),
            raw.exp.filter((r) => r.field === 'percent').map((r) => r.text), fits);
          else for (smooth of [false, true]) {
            const numbers = number !== null ? [number, number]
              : await readField(engine, frame, boxes.number, 'number', raw.exp, smooth, false, {soft: true});
            read = pickExp(numbers, [percent, percent]);
            if (read.value) break;
          }
        }
      }
      if (!read.value && safari && fits && number === null) {
        // A firmer mask separates blurred digit tops; the usual unique table match still judges both reads.
        await readField(engine, frame, boxes.number, 'number', raw.exp, false, false, {threshold: 150});
        read = pickExp(
          raw.exp.filter((r) => r.field === 'number').map((r) => r.text),
          raw.exp.filter((r) => r.field === 'percent').map((r) => r.text), fits);
      }
      result.source = 'ocr';
    }
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
    let badge = early?.level != null ? early : await readLevelBadge(engine, frame, boxes.level, templates, raw.level, smooth);
    if (safari && badge.level === null && !badge.ambiguous) badge = await readLevelBadge(engine, frame, boxes.level, templates, raw.level, !smooth);
    result.levelSegments = badge.segments;
    if (badge.ambiguous) return {...result, status: 'ambiguous', reason: 'conflicting_level_variants'};
    result.level = badge.level; result.levelSource = badge.source;
  }
  // A percentage alone is no EXP without its level (production's rule too).
  if (result.percentOnly && result.level === null) return {...result, status: 'unreadable', reason: 'level_unreadable'};
  return result;
}

// Does the box before "[" hold digits? Ink must span most of the digit band: the EXP label's dot (its bottom
// rows) does not. Dim ink counts (Safari blurs a lone 7's stroke to 110-170), except the column touching "[",
// where stream frames show a dim bracket outline (measured on percentage-only stream frames).
export function hasDigits(frame, box, band) {
  if (!box) return false;
  let rows = 0;
  for (let y = band.top; y <= band.bottom; y++) {
    for (let x = Math.max(0, Math.floor(box.x0)); x < Math.min(frame.width, Math.ceil(box.x1) - 1); x++) {
      const i = (y * frame.width + x) * 4, r = frame.data[i], g = frame.data[i + 1], b = frame.data[i + 2];
      if (Math.max(r, g, b) > 110 && !bracketColour(r, g, b)) { rows++; break; }
    }
  }
  return rows >= .6 * (band.bottom - band.top + 1);
}

// A percentage-only field: exact glyphs, else two OCR variants that agree on one percentage.
async function readPercentOnly(engine, frame, box, segmented, templates, raw, safari) {
  let text = readGlyphs(segmented, templates), source = 'glyphs';
  if (text === null && safari) { text = await readPercentGlyphs(engine, frame, box, segmented, templates, raw); source = 'ocr'; }
  const known = text === null ? null : parsePercent(text);
  if (known !== null) { raw.push({field: 'glyphs', text}); return {value: {exp: null, bp: known}, source}; }
  const crisp = [];
  for (const smooth of [false, true]) {
    const values = (await readField(engine, frame, box, 'percent', raw, smooth, false, {soft: safari})).map(parsePercent);
    // The smooth pass can agree on a leading 7 as 2 (stream frames: 79.88% as 29.88% twice) while the crisp pass
    // read it right once: a smooth value must not contradict every valid crisp read.
    const contradicted = smooth && crisp.length && !crisp.includes(values[0]);
    if (values.length === 2 && values[0] !== null && values[0] === values[1] && !contradicted) return {value: {exp: null, bp: values[0]}, source: 'ocr', smooth};
    crisp.push(...values.filter((v) => v !== null));
  }
  return {reason: 'cannot_parse_exp'};
}

// The level badge: learned glyphs, else OCR at two magnifications that must agree ({ambiguous} if not); line
// mode first, single-word mode when it reads nothing (a lone digit).
async function readLevelBadge(engine, frame, box, templates, raw, smooth) {
  const segments = segment(frame, box, 'min');
  let known = parseLevel(readGlyphs(segments, templates) ?? '');
  if (known !== null) return {level: known, source: 'glyphs', segments};
  // The game draws its cursor into the capture. A pointer at the badge edge can add white pixels below the digits.
  const interior = segment(frame, {...box, y1: box.y1 - 2}, 'min');
  known = parseLevel(readGlyphs(interior, templates) ?? '');
  if (known !== null) return {level: known, source: 'glyphs', segments: interior};
  let levels = new Set((await readField(engine, frame, box, 'level', raw, smooth)).map(parseLevel).filter((v) => v !== null));
  if (!levels.size) levels = new Set((await readField(engine, frame, box, 'levelWord', raw, smooth)).map(parseLevel).filter((v) => v !== null));
  return {level: levels.size === 1 ? [...levels][0] : null, source: 'ocr', segments, ambiguous: levels.size > 1};
}

// OCR text of one panel line at several native magnifications: the text at least two agree on (and, when
// given, with exactly `length` characters), else null.
async function lineText(engine, frame, box, field, length = null, smooth = false) {
  const part = crop(frame, {x0: box.x0 - 2, y0: box.y0 - 2, x1: box.x1 + 2, y1: box.y1 + 2}), gray = channel(part, 'min'), votes = new Map();
  for (const scale of [3, 4, 2, 5]) {
    const text = (await engine.read(pgm(binarize(gray, part.width, part.height, smooth ? 125 : 170, scale, 8, smooth)), field)).text.trim().replace(/\s+/g, ' ');
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
  if (readings >= 2) return glyphs.map((g) => [...votes.get(g.key)].sort((a, b) => b[1] - a[1])[0][0]).join('');
  // Blur can damage glyphs without changing their count; require two identical whole-line reads.
  const whole = new Set();
  for (const scale of [2, 3, 4]) {
    const image = binarize(gray, part.width, part.height, 125, scale, 8, true);
    const text = (await engine.read(pgm(image), 'name')).text.trim();
    if (!/^[A-Za-z0-9]{2,13}$/.test(text)) continue;
    if (whole.has(text)) return text;
    whole.add(text);
  }
  return null;
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
  if (boxes.job) {
    out.job = matchJob(await lineText(engine, frame, boxes.job, 'job'), jobs);
    if (!out.job) out.job = matchJob(await lineText(engine, frame, boxes.job, 'job', null, true), jobs);
  }
  return out;
}

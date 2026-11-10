// Pure HUD image helpers shared by the browser tracker and the Node fixture check.
// A frame is {width, height, data} with RGBA bytes (ImageData's shape). No DOM here.

export function crop(frame, box) {
  const x0 = Math.max(0, Math.floor(box.x0)), y0 = Math.max(0, Math.floor(box.y0));
  const x1 = Math.min(frame.width, Math.ceil(box.x1)), y1 = Math.min(frame.height, Math.ceil(box.y1));
  const width = Math.max(0, x1 - x0), height = Math.max(0, y1 - y0);
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    const from = ((y0 + y) * frame.width + x0) * 4;
    data.set(frame.data.subarray(from, from + width * 4), y * width * 4);
  }
  return {width, height, data};
}

// 'max' keeps the green EXP brackets; 'min' keeps only near-white digits (drops orange level tiles).
export function channel(frame, mode) {
  const out = new Uint8Array(frame.width * frame.height), d = frame.data;
  for (let i = 0, j = 0; j < out.length; i += 4, j++) {
    const r = d[i], g = d[i + 1], b = d[i + 2];
    out[j] = mode === 'max' ? Math.max(r, g, b) : mode === 'min' ? Math.min(r, g, b) : (r * 299 + g * 587 + b * 114) / 1000;
  }
  return out;
}

export function otsu(gray) {
  const histogram = new Array(256).fill(0);
  for (const v of gray) histogram[v]++;
  let sum = 0;
  for (let i = 0; i < 256; i++) sum += i * histogram[i];
  let below = 0, belowSum = 0, best = 0, threshold = 127;
  for (let t = 0; t < 256; t++) {
    below += histogram[t];
    if (!below || below === gray.length) continue;
    belowSum += t * histogram[t];
    const a = belowSum / below, b = (sum - belowSum) / (gray.length - below);
    const score = below * (gray.length - below) * (a - b) ** 2;
    if (score > best) { best = score; threshold = t; }
  }
  return threshold;
}

// Integer upscale of a gray plane, then threshold: dark text on white, padded. Nearest-neighbour keeps
// the game's 1-pixel bitmap font crisp in a native window capture (bilinear made Tesseract flip 9/8);
// bilinear (smooth) suits a scaled, blurred HUD, as in the Python reader.
export function binarize(gray, width, height, threshold, scale = 1, pad = 8, smooth = false) {
  const w = width * scale, h = height * scale, W = w + 2 * pad, H = h + 2 * pad;
  const data = new Uint8Array(W * H).fill(255);
  for (let y = 0; y < h; y++) {
    const fy = Math.min(height - 1, Math.max(0, (y + .5) / scale - .5)), y0 = Math.floor(fy), y1 = Math.min(height - 1, y0 + 1), wy = fy - y0;
    const row = Math.floor(y / scale) * width;
    for (let x = 0; x < w; x++) {
      let v;
      if (!smooth) v = gray[row + Math.floor(x / scale)];
      else {
        const fx = Math.min(width - 1, Math.max(0, (x + .5) / scale - .5)), x0 = Math.floor(fx), x1 = Math.min(width - 1, x0 + 1), wx = fx - x0;
        v = (gray[y0 * width + x0] * (1 - wx) + gray[y0 * width + x1] * wx) * (1 - wy) + (gray[y1 * width + x0] * (1 - wx) + gray[y1 * width + x1] * wx) * wy;
      }
      if (v > threshold) data[(y + pad) * W + x + pad] = 0;
    }
  }
  return {width: W, height: H, data};
}

// Binary PGM: Leptonica inside tesseract.js decodes it directly, with no PNG encoding step.
export function pgm(image) {
  const header = new TextEncoder().encode(`P5\n${image.width} ${image.height}\n255\n`);
  const out = new Uint8Array(header.length + image.data.length);
  out.set(header); out.set(image.data, header.length);
  return out;
}

// Integer magnification giving Tesseract roughly 40 px tall text.
export const magnification = (textHeight) => Math.max(3, Math.min(5, Math.round(36 / Math.max(1, textHeight))));

// Orange level tiles: strongly red-over-blue pixels. Returns their bounding box inside frame coordinates.
export function orangeBox(frame, box) {
  const part = crop(frame, box), d = part.data;
  let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1, count = 0;
  for (let y = 0; y < part.height; y++) for (let x = 0; x < part.width; x++) {
    const i = (y * part.width + x) * 4, r = d[i], g = d[i + 1], b = d[i + 2];
    if (r > 170 && r - b > 110 && g > 60 && g < r - 30) {
      count++; x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
    }
  }
  if (count < 12 || y1 - y0 < 4) return null;
  const bx = Math.floor(box.x0), by = Math.floor(box.y0);
  return {x0: bx + x0, y0: by + y0, x1: bx + x1 + 1, y1: by + y1 + 1};
}

// The job (top) and name (bottom) lines beside the orange level badge, found in pixels. Rows that are
// mostly ink are panel borders. Returns {job, name} boxes in frame coordinates, or null.
export function panelLines(frame, badge) {
  const th = badge.y1 - badge.y0;
  const box = {x0: badge.x1 + 3, y0: Math.max(0, badge.y0 - .6 * th), x1: Math.min(frame.width, badge.x1 + 9.2 * th), y1: Math.min(frame.height, badge.y1 + .5 * th)};
  const part = crop(frame, box), gray = channel(part, 'min'), ink = (x, y) => gray[y * part.width + x] > 170;
  const runs = [];
  let run = null;
  for (let y = 0; y <= part.height; y++) {
    let count = 0, x0 = Infinity, x1 = -1;
    if (y < part.height) for (let x = 0; x < part.width; x++) if (ink(x, y)) { count++; x0 = Math.min(x0, x); x1 = x; }
    const text = count > 0 && count < part.width * .5;
    if (text) { if (!run) runs.push(run = {y0: y, y1: y + 1, x0, x1: x1 + 1}); else { run.y1 = y + 1; run.x0 = Math.min(run.x0, x0); run.x1 = Math.max(run.x1, x1 + 1); } }
    else run = null;
  }
  const lines = runs.filter((r) => r.y1 - r.y0 >= .35 * th && r.y1 - r.y0 <= 1.2 * th && r.x1 - r.x0 <= .8 * part.width);
  if (lines.length !== 2) return null;
  const left = Math.floor(box.x0), top = Math.floor(box.y0);
  const [job, name] = lines.map((r) => ({x0: left + r.x0, y0: top + r.y0, x1: left + r.x1, y1: top + r.y1}));
  return {job, name};
}

// Columns containing text-bright pixels; trims a generous EXP box to the text it holds.
export function brightBox(frame, box, threshold = 150) {
  const part = crop(frame, box), gray = channel(part, 'max');
  let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
  for (let y = 0; y < part.height; y++) for (let x = 0; x < part.width; x++) {
    if (gray[y * part.width + x] > threshold) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  }
  if (x1 < 0) return null;
  const bx = Math.floor(box.x0), by = Math.floor(box.y0);
  return {x0: bx + x0, y0: by + y0, x1: bx + x1 + 1, y1: by + y1 + 1};
}

// Olive-green bracket fill and outline, e.g. 160,185,130 and 60,85,30 (the yellow EXP gauge has red above 200).
export const bracketColour = (r, g, b) => g > r + 12 && g > b + 20 && g > 70 && r < 200;

// The olive-green [ and ] around the percentage, found in pixels (fill and outline; the yellow
// EXP gauge has red above 200). Exactly two bracket column runs, or null: never guessed.
export function brackets(frame, box) {
  const part = crop(frame, box), d = part.data, runs = [];
  let run = null;
  for (let x = 0; x < part.width; x++) {
    let count = 0;
    for (let y = 0; y < part.height; y++) {
      const i = (y * part.width + x) * 4, r = d[i], g = d[i + 1], b = d[i + 2];
      if (bracketColour(r, g, b)) count++;
    }
    if (count >= 3) { if (run && x - run.x1 <= 1) run.x1 = x + 1; else runs.push(run = {x0: x, x1: x + 1}); }
  }
  if (runs.length !== 2 || runs[1].x0 - runs[0].x1 < 4) return null;
  const left = Math.floor(box.x0);
  return runs.map((r) => ({x0: left + r.x0, x1: left + r.x1}));
}

// Rows holding bright text inside a box (the digit band), or null.
// Text rows are partly bright; a panel border caught by a loose box is a near-solid bright row. So the
// band is the longest run of partly-bright rows.
export function inkRows(frame, box, threshold = 170) {
  const part = crop(frame, box), gray = channel(part, 'max');
  let best = null, start = -1;
  for (let y = 0; y <= part.height; y++) {
    let count = 0;
    if (y < part.height) for (let x = 0; x < part.width; x++) if (gray[y * part.width + x] > threshold) count++;
    const text = count > 0 && count < part.width * .8;
    if (text && start < 0) start = y;
    if (!text && start >= 0) { if (!best || y - start > best.bottom - best.top + 1) best = {top: start, bottom: y - 1}; start = -1; }
  }
  return best && {top: Math.floor(box.y0) + best.top, bottom: Math.floor(box.y0) + best.bottom};
}

// The EXP label is taller than the digits: the last column with ink in the two rows above the digit
// band is the label's right edge (its dot included). Null when no label is inside the box.
export function labelEnd(frame, box, top, threshold = 170) {
  let end = null;
  for (let x = Math.max(0, Math.floor(box.x0)); x < Math.min(frame.width, Math.ceil(box.x1)); x++) {
    for (let y = Math.max(0, top - 2); y < top; y++) {
      const i = (y * frame.width + x) * 4;
      if (Math.max(frame.data[i], frame.data[i + 1], frame.data[i + 2]) > threshold) { end = x; break; }
    }
  }
  return end;
}

// Word boxes from a tesseract.js result with {blocks: true}.
export function words(data) {
  const out = [];
  for (const block of data?.blocks || []) for (const paragraph of block.paragraphs || [])
    for (const line of paragraph.lines || []) for (const word of line.words || [])
      if (word.text.trim()) out.push({text: word.text.trim(), confidence: word.confidence / 100, ...word.bbox});
  return out;
}

const label = (t) => t.text.toUpperCase().replace(/[^A-Z]/g, '');

/**
 * Bind EXP/LV labels to one status bar (the Python discover_regions geometry, simplified).
 * Words are in frame pixels. Returns {exp, level} boxes or a reason; ambiguity is a failure.
 */
export function locate(found, frame) {
  const exps = found.filter((t) => /^EXP/.test(label(t)) && label(t).length <= 4);
  const hps = found.filter((t) => label(t).startsWith('HP')), mps = found.filter((t) => label(t).startsWith('MP'));
  const lvs = found.filter((t) => label(t) === 'LV');
  const candidates = [];
  for (const exp of exps) {
    const h = exp.y1 - exp.y0;
    let step = null;
    for (const mp of mps) for (const hp of hps) {
      const s = mp.x0 - hp.x0, dx = exp.x0 - mp.x0;
      if (s > 3 * h && Math.abs(mp.y0 - exp.y0) < h && Math.abs(hp.y0 - exp.y0) < h && dx > .65 * s && dx < 1.5 * s) step = s;
    }
    if (step === null && exps.length > 1) continue;  // Several EXP labels need the HP/MP geometry to choose.
    const span = step ?? 12 * h;
    const level = lvs.filter((lv) => {
      const dx = exp.x0 - lv.x0;
      return dx > 1.5 * span && dx < 4.5 * span && Math.abs(lv.y0 - exp.y0) < 2.5 * h;
    });
    candidates.push({exp, h, span, level: level.length === 1 ? level[0] : null});
  }
  if (!candidates.length) return {reason: exps.length ? 'hud_geometry_unclear' : 'exp_label_not_found'};
  if (candidates.length > 1) return {reason: 'multiple_huds'};
  const {exp, h, span, level} = candidates[0];
  // The EXP digits are the words after the label on the same row; their height sets the text band.
  const digits = found.filter((t) => /\d/.test(t.text) && t.x0 >= exp.x0 + .5 * (exp.x1 - exp.x0) && t.x0 < exp.x0 + span
    && Math.abs((t.y0 + t.y1) / 2 - (exp.y0 + exp.y1) / 2) < .6 * h);
  if (!digits.length) return {reason: 'exp_digits_not_found'};
  const top = Math.min(...digits.map((t) => t.y0)), bottom = Math.max(...digits.map((t) => t.y1)), th = bottom - top;
  // The box keeps the EXP label: OCR word boxes vary, so each scan trims the label in pixels (labelEnd).
  // Room to the right for longer numbers; each scan cuts at the green closing bracket.
  const expBox = {x0: exp.x0 - .2 * h, y0: top - .3 * th, x1: Math.min(frame.width, exp.x0 + 1.15 * span, Math.max(...digits.map((t) => t.x1)) + 3 * th), y1: bottom + .3 * th};
  // The orange tiles are found in pixels each scan; LV. only narrows the search when it was recognised.
  const lh = level ? level.y1 - level.y0 : h;
  const levelBox = level ? {x0: level.x1, y0: level.y0 - .6 * lh, x1: level.x1 + 4 * lh, y1: level.y1 + .6 * lh}
    : {x0: Math.max(0, exp.x0 - 4.5 * span), y0: exp.y0 - 1.2 * h, x1: Math.max(0, exp.x0 - 2.1 * span), y1: Math.min(frame.height, exp.y1 + 1.6 * h)};
  return {exp: expBox, level: levelBox};
}

export const normalize = (box, frame) => box && ({x0: box.x0 / frame.width, y0: box.y0 / frame.height, x1: box.x1 / frame.width, y1: box.y1 / frame.height});
export const denormalize = (box, frame) => box && ({x0: box.x0 * frame.width, y0: box.y0 * frame.height, x1: box.x1 * frame.width, y1: box.y1 * frame.height});

// The bottom of the window, where the status bar lives; detection OCR never scans the whole frame.
export function stripBox(frame) {
  return {x0: 0, y0: Math.floor(frame.height * .78), x1: frame.width, y1: frame.height};
}

export function stripImage(frame) {
  const box = stripBox(frame), part = crop(frame, box);
  const scale = frame.height >= 1000 ? 2 : 3;
  return {box, scale, image: binarize(channel(part, 'luma'), part.width, part.height, 160, scale, 0)};
}

export function mapWords(list, box, scale) {
  return list.map((w) => ({...w, x0: w.x0 / scale + box.x0, x1: w.x1 / scale + box.x0, y0: w.y0 / scale + box.y0, y1: w.y1 / scale + box.y0}));
}

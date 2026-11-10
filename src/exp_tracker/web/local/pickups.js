// Pickup messages in the bottom-right corner ("You have gained mesos (+10)", "Leather x1 earned. (Etc)").
// Pure functions shared by the browser and the Node tests. A frame is {width, height, data} (RGBA).

// Message text is light neutral grey with a near-black neutral outline (pure black in a window capture,
// dark grey in the game's own screenshots). Scenery rarely puts neutral dark right beside neutral light,
// which separates text from clouds, fences and the quick-slot panel.
export function messageLines(frame) {
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
      if (n > 40 && x1 > w - 30 && x1 - x0 > 80) {
        let key = 0;
        for (let yy = start; yy < y; yy++) for (let x = x0; x <= x1; x++) key = (key * 31 + text[yy * w + x]) | 0;
        lines.push({y0: start, y1: y, x0, x1, n, key: `${x1 - x0}:${key}`});
      }
    }
    start = -1;
  }
  return lines.reverse();  // Newest (bottom) first.
}

/**
 * How many lines are new at the bottom of the stack since the previous frame. Messages only appear at
 * the bottom and push older ones up one line height; lines only vanish from the top. So `shift` new
 * lines means every remaining old line reappears `shift` line heights higher with the same pixels.
 * That counts repeated identical messages ("+10", "+10") and several arrivals in one frame.
 */
export function newLines(previous, current) {
  if (!current.length) return 0;
  if (!previous.length) return current.length;
  const gaps = [current, previous].flatMap((stack) => stack.slice(1).map((line, k) => stack[k].y0 - line.y0)).sort((x, y) => x - y);
  const step = gaps.length ? gaps[gaps.length >> 1] : 12;
  for (let shift = 0; shift <= current.length; shift++) {
    if (current.length - shift > previous.length) continue;  // Extra lines at the top cannot appear.
    let same = true;
    for (let k = 0; shift + k < current.length && same; k++) {
      const line = current[shift + k], old = previous[k];
      same = line.key === old.key && Math.abs(line.y0 - (old.y0 - shift * step)) <= 2;
    }
    if (same) return shift;
  }
  return current.filter((line) => !previous.some((p) => p.key === line.key)).length;
}

const amount = (s) => Number(s.replace(/[,.]/g, ''));

// One message line of text, or null. Item names may be cut off with "...".
export function parseMessage(text) {
  const t = text.replace(/\s+/g, ' ').trim();
  let m = /gained mesos \(\+?([\d,.]+)\)/i.exec(t);
  if (m) return {kind: 'mesos', amount: amount(m[1])};
  m = /gained (?:experience|exp)\w* \(\+?([\d,.]+)\)/i.exec(t);
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

// Pickup tracking for a running capture: raises the share to 15 fps, runs pickup-worker.js on the
// frames, and reads each finished message with the shared OCR engine (queued so it never runs in the
// middle of an EXP scan). Reports {at, text, parsed, item} per message.
import {binarize, pgm} from './hud.js';
import {learnLine, matchName, readLine} from './message-font.js';
import {amountSpan, countSpan, lineWords, resolveItem, span, tabOf} from './pickups.js';

let items = null;
export const loadItems = () => items ??= fetch('/static/local/items/items.json').then((r) => r.json())
  .then((d) => d.items.map(([name, tab, id, monsters, sheet, cell]) => ({name, tab, id, monsters, sheet, cell})));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const SHAPE_COST = 1.5, SHAPE_LEAD = .5;
// The right part of the window above the status bar, past the quick-slot panel.
export const REGION = {x0: .75, y0: .45, y1: .89};  // Same box the tracker was tuned on (live recording).

// OCR of a mask, padded and magnified. A background job: waits while an EXP scan holds or wants the engine.
async function ocr(engine, mask, field, scale) {
  const pad = 4, width = mask.width + pad * 2, height = mask.height + pad * 2, gray = new Uint8Array(width * height);
  // Masks have 1-px strokes; Tesseract reads them far better thickened to 2x2 (measured: digits went from
  // garbled to right on most lines).
  const on = (x, y) => x >= 0 && y >= 0 && mask.bits[y * mask.width + x];
  for (let y = 0; y < mask.height; y++) for (let x = 0; x < mask.width; x++) {
    gray[(y + pad) * width + x + pad] = on(x, y) || on(x - 1, y) || on(x, y - 1) || on(x - 1, y - 1) ? 255 : 0;
  }
  for (;;) {
    const result = await engine.exclusive(() => engine.read(pgm(binarize(gray, width, height, 127, scale)), field), {background: true});
    if (result) return result.text.replace(/\s+/g, ' ').trim();
    await sleep(100);
  }
}

// The value read most often: {value, agreed} once two reads agree, else the best after every read.
// Measured: whole-line OCR misreads digits, while OCR of just the digits, over a few samples, reads them.
async function vote(reads) {
  const count = new Map();
  for (const read of reads) {
    const value = await read();
    if (value === null) continue;
    count.set(value, (count.get(value) ?? 0) + 1);
    if (count.get(value) === 2) return {value, agreed: true, values: [...count.keys()]};
  }
  return {value: [...count].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null, agreed: false, values: [...count.keys()]};
}

// Unconfirmed digit reads, rounded down to what they agree on: "23" and "28" make 20, a lone "23" also
// 20. Meso totals are approximate by design (a sense of the rate), so a near amount beats no amount.
// The length most reads have wins, the shorter on a tie: a ")" read as a digit turns "13" into "132"
// (measured live: four EXP lines counted 100 each).
export function rounded(values) {
  const strings = values.map(String), count = (n) => strings.filter((s) => s.length === n).length;
  const length = strings.map((s) => s.length).sort((a, b) => count(b) - count(a) || a - b)[0];
  const same = strings.filter((s) => s.length === length);
  if (!same.length) return null;
  let prefix = same[0].slice(0, same.length > 1 ? length : 1);
  for (const s of same) while (!s.startsWith(prefix)) prefix = prefix.slice(0, -1);
  return prefix ? Number(prefix.padEnd(length, '0')) : null;
}

// Thin strokes often turn "earned" into "eamed" or "seamed".
const kindOf = (text) => (/earn|eam|amed\./i.test(text) ? 'item' : /mes[oa]s|gained/i.test(text) ? 'mesos' : /EXP|rece/i.test(text) ? 'exp' : null);

// A number read from the learned font; unknown trailing digits ("2?") round down, as above.
const fontNumber = (digits) => {
  const plain = digits.replace(/,/g, ''), known = plain.match(/^\d+/)?.[0];
  return known ? {amount: Number(known.padEnd(plain.length, '0')), approx: known.length < plain.length} : null;
};

// A whole line read with the learned font, or null. Fixed words must read exactly.
function parseFont(text, list) {
  // Messages are right-aligned: anything left of "You" (a monster's name tag in the same rows) is not part of it.
  let m = /(?:^|[ ?])You have gained mesos \(\+([\d,?]+)\)$/.exec(text) ?? /(?:^|[ ?])You received EXP \(\+([\d,?]+)\)$/.exec(text);
  if (m) {
    const n = fontNumber(m[1]);
    return n && {text: text.slice(text.indexOf('You ', m.index)), parsed: {kind: m[0].includes('mesos') ? 'mesos' : 'exp', ...n}, item: null};
  }
  m = /^(.+) x([\d?]+) earned\. \((\w+)\)$/.exec(text);
  const n = m && fontNumber(m[2]), tab = m && tabOf(m[3]);
  if (!n || !tab) return null;
  const cut = /\.\.\.$/.test(m[1]), name = m[1].replace(/\.+$/, '');
  return {text, parsed: {kind: 'item', name, cut, count: n.amount, approx: n.approx, tab}, item: resolveItem(list, {name, cut, tab})};
}

// The text a confirmed message shows, for learning its glyphs; null when part of it is not known
// exactly (a cut-off name, an equipment tab whose spelling is unconfirmed).
function shown({parsed, item}) {
  if (!parsed || parsed.approx) return null;
  // Meso amounts show no thousands comma ("(+1500)", reported live).
  if (parsed.kind === 'mesos') return `You have gained mesos (+${parsed.amount})`;
  if (parsed.kind === 'exp') return `You received EXP (+${parsed.amount.toLocaleString('en-US')})`;
  return item && !parsed.cut && parsed.tab !== 'Equip' ? `${item.name} x${parsed.count} earned. (${parsed.tab})` : null;
}

/**
 * Reads one message from its masks. With a learned `font`, a line it reads completely settles it.
 * Otherwise OCR: the kind from the whole line, then only the parts that matter: the digits in the
 * closing "(+1,250)" for mesos and EXP; the count in "x3", the tab in "(Etc)" and the name, matched
 * against the item list, for items. A confirmed reading teaches the font every glyph of its lines.
 */
export async function readMessage(engine, samples, list, font = null) {
  // The first sample is the bottom slot, where scenery is busiest: read it last.
  const order = [...samples.slice(1), ...samples.slice(0, 1)].map((mask) => ({mask, words: lineWords(mask)}));
  let result = null, confirmed = false;
  if (font) for (const {mask} of order) {
    result = parseFont(readLine(font, mask), list) ?? result;
    // An item name confirms only when it names a known item ("Snaii Sheii" may be a font mix-up).
    if (result && !result.parsed.approx && (result.parsed.kind !== 'item' || result.item)) { confirmed = true; break; }
  }
  if (!confirmed) {
    // Partial font reads ("?ree ?ra??h x1 ...") still carry the glyphs the font knows, digits above all.
    const read = await readByOcr(engine, order, list, font ? order.map(({mask}) => readLine(font, mask)) : [], font);
    confirmed = read.confirmed;
    if (!result || read.result.parsed) result = read.result;
  }
  const text = confirmed && font ? shown(result) : null;
  if (text) for (const {mask} of order) learnLine(font, mask, text);
  return result;
}

// The parts a whole-line read shows, or nulls: "... (+1 6)" gives amount 16; "Tree Branch x1 seamed. (Etc)"
// gives name, count and tab. A font read leaves "?" for glyphs it does not know: "?ree ?ra??h ?1 ..."
// still gives the count, but never a name.
export function lineParts(text) {
  // One bracket may be lost ("+17)", "(+17"), not both: "+121" is often "(+12)" with ")" read as a 1.
  const amount = (/\(\s*\+?\s*(\d[\d,. ]*)\)?\s*$/.exec(text) ?? /\+\s*(\d[\d,. ]*)\)\s*$/.exec(text))?.[1].replace(/\D/g, '');
  // "x1" can also come out as ":1" or ":x1", glued to the name ("Leather:1 eamed.").
  const item = /^(.*?)(?:\s+[x×?]\s?|\s*:\s*[x×]?)(\d+)\s/.exec(text), tab = /\(\s*([A-Za-z]{2,5})\W*$/.exec(text)?.[1];
  const name = item?.[1].includes('?') ? null : item?.[1].replace(/[^A-Za-z0-9' .:-]/g, '').trim();
  return {amount: amount ? Number(amount) : null, name: name || null, count: item ? Number(item[2]) : null, tab: item && tab ? tabOf(tab) : null};
}

async function readByOcr(engine, order, list, fontTexts, font = null) {
  // Every sample is read whole first: with clean masks those reads carry the digits too (measured), and
  // the separate reads of just the digits, the tab or the name only add votes when they disagree.
  const texts = [];
  for (const {mask} of order) texts.push(await ocr(engine, mask, 'message', 3));
  const kind = (await vote([...fontTexts, ...texts].map((t) => async () => kindOf(t)))).value;
  const text = texts.find((t) => kindOf(t) === kind) ?? texts[0] ?? '';
  const parts = [...fontTexts, ...texts].filter((t) => kindOf(t) === kind).map(lineParts);
  const fromLines = (field) => parts.map((p) => async () => p[field]);
  // Digit reads of a span of each sample (columns [x0, x1) or null), at two magnifications.
  const digits = async (field, spanOf) => {
    const votes = await vote([...fromLines(field), ...order.flatMap(({mask, words}) => {
      const at = spanOf(mask, words);
      return at ? [3, 5].map((scale) => async () => {
        const read = (await ocr(engine, span(mask, ...at), 'number', scale)).replace(/[,.]/g, '');
        return /^\d+$/.test(read) ? Number(read) : null;
      }) : [];
    })]);
    return votes.agreed ? {amount: votes.value, approx: false} : votes.values.length ? {amount: rounded(votes.values), approx: true} : null;
  };
  const none = {result: {text, parsed: null, item: null}, confirmed: false};
  if (kind === 'mesos' || kind === 'exp') {
    // EXP comes from the EXP bar, never from messages: its digits get no reads of their own.
    const n = await digits('amount', kind === 'exp' ? () => null : amountSpan);
    return n?.amount ? {result: {text, parsed: {kind, ...n}, item: null}, confirmed: !n.approx} : none;
  }
  if (kind !== 'item') return none;
  // "Arrows for Bows x3 earned. (Use)": the count is the third word from the end, after its "x".
  const n = await digits('count', (mask) => countSpan(mask)?.count ?? null);
  const tab = await vote([...fromLines('tab'), ...order.map(({mask, words}) => async () => (words.length >= 4 ? tabOf(await ocr(engine, span(mask, words.at(-1).x0, words.at(-1).x1), 'message', 3)) : null))]);
  // The name compared shape by shape with every item name (matchName), when it is clearly one item: close
  // (SHAPE_COST pixels per letter) and ahead of the runner-up (SHAPE_LEAD). Measured on 63 saved item lines:
  // the 42 OCR had matched all agreed, and 20 it could not match were found ("Biff Feather": Stiff, not Soft).
  const spans = order.map(({mask}) => { const at = countSpan(mask)?.name; return at ? span(mask, at[0], at[1] + 1) : null; }).filter(Boolean);
  const shaped = font && spans.length ? matchName(font, spans, tab.value ? list.filter((i) => i.tab === tab.value) : list) : null;
  if (shaped && shaped.cost <= SHAPE_COST && shaped.next - shaped.cost >= SHAPE_LEAD) {
    const item = shaped.item, count = n?.amount ? n : {amount: 1, approx: true};
    return {result: {text, parsed: {kind, name: item.name, cut: shaped.cut, count: count.amount, approx: count.approx, tab: tab.value ?? item.tab}, item},
      confirmed: !count.approx && (tab.agreed || tab.value === null)};
  }
  const name = (await vote([...fromLines('name'), ...order.map(({mask, words}) => async () => {
    const at = countSpan(mask)?.name ?? (words.length >= 4 ? [words[0].x0, words.at(-4).x1] : null);
    if (!at) return null;
    const read = await ocr(engine, span(mask, ...at), 'message', 3);
    return read.replace(/[^A-Za-z0-9' .:-]/g, '').trim() || null;
  })])).value;
  if (!name) return none;
  const cut = /\.\s*\.$/.test(name), named = name.replace(/[\s.]+$/, ''), item = resolveItem(list, {name: named, cut, tab: tab.value});
  // A known item whose count is unreadable ("Leather:1") counts as 1, approximate: at least one was picked up.
  if (!n?.amount && !item) return none;
  const count = n?.amount ? n : {amount: 1, approx: true};
  // An unread tab ("(Etc)" often comes out "Ex)") is the named item's own; a misread one never confirms.
  return {result: {text, parsed: {kind, name: named, cut, count: count.amount, approx: count.approx, tab: tab.value ?? item?.tab ?? null}, item},
    confirmed: !count.approx && Boolean(item) && (tab.agreed || tab.value === null)};
}

// `font` is the message font learned so far (saved by the page); reading adds to it in place.
export async function startPickups({track, engine, font = {}, onMessage, onStats, onError}) {
  const list = await loadItems();
  if (!('MediaStreamTrackProcessor' in window)) throw new Error('This browser cannot stream frames to a worker (needs Chrome or Edge)');
  await track.applyConstraints({frameRate: {ideal: 15, max: 15}});
  const clone = track.clone(), processor = new MediaStreamTrackProcessor({track: clone});
  const worker = new Worker(new URL('./pickup-worker.js', import.meta.url), {type: 'module'});
  const queue = [];
  let draining = false, stopped = false;
  const drain = async () => {
    if (draining) return;
    draining = true;
    while (queue.length && !stopped) {
      const message = queue.shift();
      // Far behind (a flood of messages): count the oldest unread rather than starve EXP scans of OCR.
      const read = queue.length > 50 ? {text: '', parsed: null, item: null} : await readMessage(engine, message.samples, list, font);
      // The masks stay with the message (memory only) so a debug session can inspect what was read.
      onMessage({at: message.at, ...read, samples: message.samples});
    }
    draining = false;
  };
  worker.onmessage = ({data}) => {
    // Every message is counted; reading waits its turn (the worker only reports finished messages).
    if (data.type === 'message') { queue.push(data); drain(); }
    else if (data.type === 'stats') onStats?.({...data, queued: queue.length});
    else if (data.type === 'error') onError?.(data.message);
  };
  worker.postMessage({type: 'start', stream: processor.readable, region: REGION}, [processor.readable]);
  return {
    // How a stretched window is undone (the EXP reader finds out which way the game stretches; see app.js scan).
    setStretch(mode) { worker.postMessage({type: 'stretch', mode}); },
    async stop() {
      stopped = true;
      worker.postMessage({type: 'stop'}); worker.terminate(); clone.stop();
      await track.applyConstraints({frameRate: {ideal: 5, max: 5}}).catch(() => {});
    },
  };
}

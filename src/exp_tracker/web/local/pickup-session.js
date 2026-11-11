// Pickup tracking for a running capture: raises the share to 15 fps, runs pickup-worker.js on the
// frames, and reads each finished message with the shared OCR engine (queued so it never runs in the
// middle of an EXP scan). Reports {at, text, parsed, item} per message.
import {binarize, pgm} from './hud.js';
import {learnLine, readLine} from './message-font.js';
import {amountSpan, lineWords, resolveItem, span, tabOf} from './pickups.js';

let items = null;
export const loadItems = () => items ??= fetch('/static/local/items/items.json').then((r) => r.json())
  .then((d) => d.items.map(([name, tab, id, monsters, sheet, cell]) => ({name, tab, id, monsters, sheet, cell})));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// The right part of the window above the status bar, past the quick-slot panel.
export const REGION = {x0: .75, y0: .45, y1: .89};  // Same box the tracker was tuned on (live recording).

// OCR of a mask, padded and magnified. Waits while an EXP scan holds the engine.
async function ocr(engine, mask, field, scale) {
  const pad = 4, width = mask.width + pad * 2, height = mask.height + pad * 2, gray = new Uint8Array(width * height);
  for (let y = 0; y < mask.height; y++) for (let x = 0; x < mask.width; x++) gray[(y + pad) * width + x + pad] = mask.bits[y * mask.width + x] ? 255 : 0;
  for (;;) {
    const result = await engine.exclusive(() => engine.read(pgm(binarize(gray, width, height, 127, scale)), field));
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
export function rounded(values) {
  const strings = values.map(String), length = strings[0]?.length;
  const same = strings.filter((s) => s.length === length);
  if (!same.length) return null;
  let prefix = same[0].slice(0, same.length > 1 ? length : 1);
  for (const s of same) while (!s.startsWith(prefix)) prefix = prefix.slice(0, -1);
  return prefix ? Number(prefix.padEnd(length, '0')) : null;
}

const kindOf = (text) => (/earn/i.test(text) ? 'item' : /mes[oa]s|gained/i.test(text) ? 'mesos' : /EXP|rece/i.test(text) ? 'exp' : null);

// A number read from the learned font; unknown trailing digits ("2?") round down, as above.
const fontNumber = (digits) => {
  const plain = digits.replace(/,/g, ''), known = plain.match(/^\d+/)?.[0];
  return known ? {amount: Number(known.padEnd(plain.length, '0')), approx: known.length < plain.length} : null;
};

// A whole line read with the learned font, or null. Fixed words must read exactly.
function parseFont(text, list) {
  let m = /^You have gained mesos \(\+([\d,?]+)\)$/.exec(text) ?? /^You received EXP \(\+([\d,?]+)\)$/.exec(text);
  if (m) {
    const n = fontNumber(m[1]);
    return n && {text, parsed: {kind: text.startsWith('You have') ? 'mesos' : 'exp', ...n}, item: null};
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
  if (parsed.kind === 'mesos') return `You have gained mesos (+${parsed.amount.toLocaleString('en-US')})`;
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
    if (result && !result.parsed.approx) { confirmed = true; break; }
  }
  if (!confirmed) {
    const read = await readByOcr(engine, order, list);
    confirmed = read.confirmed;
    if (!result || read.result.parsed) result = read.result;
  }
  const text = confirmed && font ? shown(result) : null;
  if (text) for (const {mask} of order) learnLine(font, mask, text);
  return result;
}

async function readByOcr(engine, order, list) {
  const texts = [];
  const kind = (await vote(order.map(({mask}) => async () => { const text = await ocr(engine, mask, 'message', 3); texts.push(text); return kindOf(text); }))).value;
  const text = texts.find((t) => kindOf(t) === kind) ?? texts[0] ?? '';
  // Digit reads of a span of each sample (columns [x0, x1) or null), at two magnifications.
  const digits = async (spanOf) => {
    const votes = await vote(order.flatMap(({mask, words}) => {
      const at = spanOf(mask, words);
      return at ? [3, 5].map((scale) => async () => {
        const read = (await ocr(engine, span(mask, ...at), 'number', scale)).replace(/[,.]/g, '');
        return /^\d+$/.test(read) ? Number(read) : null;
      }) : [];
    }));
    return votes.agreed ? {amount: votes.value, approx: false} : votes.values.length ? {amount: rounded(votes.values), approx: true} : null;
  };
  const none = {result: {text, parsed: null, item: null}, confirmed: false};
  if (kind === 'mesos' || kind === 'exp') {
    const n = await digits(amountSpan);
    return n?.amount ? {result: {text, parsed: {kind, ...n}, item: null}, confirmed: !n.approx} : none;
  }
  if (kind !== 'item') return none;
  // "Arrows for Bows x3 earned. (Use)": the count is the third word from the end, after its "x".
  const n = await digits((mask, words) => { const g = words.at(-3)?.glyphs; return g?.length > 1 ? [g[1].x0, g.at(-1).x1] : null; });
  const tab = await vote(order.map(({mask, words}) => async () => (words.length >= 4 ? tabOf(await ocr(engine, span(mask, words.at(-1).x0, words.at(-1).x1), 'message', 3)) : null)));
  const name = (await vote(order.map(({mask, words}) => async () => {
    if (words.length < 4) return null;
    const read = await ocr(engine, span(mask, words[0].x0, words.at(-4).x1), 'message', 3);
    return read.replace(/[^A-Za-z0-9' .:-]/g, '').trim() || null;
  }))).value;
  if (!n?.amount || !name) return none;
  const cut = /\.\s*\.$/.test(name), named = name.replace(/[\s.]+$/, ''), item = resolveItem(list, {name: named, cut, tab: tab.value});
  return {result: {text, parsed: {kind, name: named, cut, count: n.amount, approx: n.approx, tab: tab.value}, item},
    confirmed: !n.approx && tab.agreed && Boolean(item)};
}

export async function startPickups({track, engine, onMessage, onStats, onError}) {
  const list = await loadItems();
  if (!('MediaStreamTrackProcessor' in window)) throw new Error('This browser cannot stream frames to a worker (needs Chrome or Edge)');
  await track.applyConstraints({frameRate: {ideal: 15, max: 15}});
  const clone = track.clone(), processor = new MediaStreamTrackProcessor({track: clone});
  const worker = new Worker(new URL('./pickup-worker.js', import.meta.url), {type: 'module'});
  const queue = [], font = {};  // The message font, learned during this test (memory only).
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
    async stop() {
      stopped = true;
      worker.postMessage({type: 'stop'}); worker.terminate(); clone.stop();
      await track.applyConstraints({frameRate: {ideal: 5, max: 5}}).catch(() => {});
    },
  };
}

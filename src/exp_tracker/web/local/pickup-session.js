// Pickup tracking for a running capture: raises the share to 15 fps, runs pickup-worker.js on the
// frames, and reads each finished message with the shared OCR engine (queued so it never runs in the
// middle of an EXP scan). Reports {at, text, parsed, item} per message.
import {binarize, pgm} from './hud.js';
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

// The value read most often, once two reads agree (or the best after every read). Measured: whole-line
// OCR misreads digits, while OCR of just the digits, over a few samples, reads them right.
async function vote(reads) {
  const count = new Map();
  for (const read of reads) {
    const value = await read();
    if (value === null) continue;
    count.set(value, (count.get(value) ?? 0) + 1);
    if (count.get(value) === 2) return value;
  }
  return [...count].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}

const kindOf = (text) => (/earn/i.test(text) ? 'item' : /mes[oa]s|gained/i.test(text) ? 'mesos' : /EXP|rece/i.test(text) ? 'exp' : null);

/**
 * Reads one message from its masks: the kind from whole-line OCR, then only the parts that matter.
 * Mesos and EXP: the digits in the closing "(+1,250)". Items: the count in "x3", the tab in "(Etc)"
 * and the name, matched against the item list.
 */
export async function readMessage(engine, samples, list) {
  // The first sample is the bottom slot, where scenery is busiest: read it last.
  const order = [...samples.slice(1), ...samples.slice(0, 1)].map((mask) => ({mask, words: lineWords(mask)}));
  const texts = [];
  const kind = await vote(order.map(({mask}) => async () => { const text = await ocr(engine, mask, 'message', 3); texts.push(text); return kindOf(text); }));
  const text = texts.find((t) => kindOf(t) === kind) ?? texts[0] ?? '';
  // Digit reads of a span of each sample (columns [x0, x1) or null), at two magnifications.
  const digits = (spanOf) => order.flatMap(({mask, words}) => {
    const at = spanOf(mask, words);
    return at ? [3, 5].map((scale) => async () => {
      const read = (await ocr(engine, span(mask, ...at), 'number', scale)).replace(/[,.]/g, '');
      return /^\d+$/.test(read) ? Number(read) : null;
    }) : [];
  });
  if (kind === 'mesos' || kind === 'exp') {
    const amount = await vote(digits(amountSpan));
    return {text, parsed: amount === null ? null : {kind, amount}, item: null};
  }
  if (kind !== 'item') return {text, parsed: null, item: null};
  // "Arrows for Bows x3 earned. (Use)": the count is the third word from the end, after its "x".
  const count = await vote(digits((mask, words) => { const g = words.at(-3)?.glyphs; return g?.length > 1 ? [g[1].x0, g.at(-1).x1] : null; }));
  const tab = await vote(order.map(({mask, words}) => async () => (words.length >= 4 ? tabOf(await ocr(engine, span(mask, words.at(-1).x0, words.at(-1).x1), 'message', 3)) : null)));
  const name = await vote(order.map(({mask, words}) => async () => {
    if (words.length < 4) return null;
    const read = await ocr(engine, span(mask, words[0].x0, words.at(-4).x1), 'message', 3);
    return read.replace(/[^A-Za-z0-9' .:-]/g, '').trim() || null;
  }));
  if (count === null || !name) return {text, parsed: null, item: null};
  const cut = /\.\s*\.$/.test(name), shown = name.replace(/[\s.]+$/, '');
  return {text, parsed: {kind, name: shown, cut, count, tab}, item: resolveItem(list, {name: shown, cut, tab})};
}

export async function startPickups({track, engine, onMessage, onStats, onError}) {
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
      const read = queue.length > 50 ? {text: '', parsed: null, item: null} : await readMessage(engine, message.samples, list);
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

// Pickup tracking for a running capture: raises the share to 15 fps, runs pickup-worker.js on the
// frames, and reads each new message line once with the shared OCR engine (queued so it never runs
// in the middle of an EXP scan). Reports {at, text, parsed, item} per message.
import {binarize, pgm} from './hud.js';
import {parseMessage, resolveItem} from './pickups.js';

let items = null;
export const loadItems = () => items ??= fetch('/static/local/items/items.json').then((r) => r.json())
  .then((d) => d.items.map(([name, tab, id, monsters, sheet, cell]) => ({name, tab, id, monsters, sheet, cell})));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// The right part of the window above the status bar, past the quick-slot panel.
export const REGION = {x0: .75, y0: .45, y1: .89};  // Same box the tracker was tuned on (live recording).

async function readLine(engine, line) {
  const gray = new Uint8Array(line.bits.length);
  for (let i = 0; i < gray.length; i++) gray[i] = line.bits[i] ? 255 : 0;
  let text = '';
  for (const scale of [3, 4]) {
    text = (await engine.read(pgm(binarize(gray, line.width, line.height, 127, scale)), 'message')).text.replace(/\s+/g, ' ').trim();
    const parsed = parseMessage(text);
    if (parsed) return {text, parsed};
  }
  return {text, parsed: null};
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
      const result = await engine.exclusive(() => readLine(engine, queue[0]));
      if (result === null) { await sleep(100); continue; }  // An EXP scan is reading; try again shortly.
      const line = queue.shift(), item = result.parsed?.kind === 'item' ? resolveItem(list, result.parsed) : null;
      // The line's mask stays with the message (memory only) so a debug session can inspect what was read.
      onMessage({at: line.at, ...result, item, line: {width: line.width, height: line.height, bits: line.bits}});
    }
    draining = false;
  };
  worker.onmessage = ({data}) => {
    // A flood of lines (noise) must never starve EXP scans of the shared OCR engine: keep the newest 30.
    if (data.type === 'line') { queue.push(data); if (queue.length > 30) queue.splice(0, queue.length - 30); drain(); }
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

// Pickup message watcher, off the page's main thread. It receives the shared window's frames as a stream
// (MediaStreamTrackProcessor), copies only the message corner, finds message lines and posts each new
// line's text mask to the page for reading. Frames are closed at once; nothing is kept.
import {messageLines, newLines} from './pickups.js';

let reader = null;

onmessage = async ({data}) => {
  if (data.type === 'stop') { reader?.cancel().catch(() => {}); reader = null; return; }
  if (data.type !== 'start') return;
  reader = data.stream.getReader();
  const canvas = new OffscreenCanvas(1, 1), context = canvas.getContext('2d', {willReadFrequently: true});
  let previous = [], frames = 0, busy = 0, since = performance.now();
  while (reader) {
    const {value: frame, done} = await reader.read().catch(() => ({done: true}));
    if (done) break;
    const started = performance.now();
    try {
      const W = frame.displayWidth, H = frame.displayHeight;
      // Right of the quick-slot panel, above the status bar: where pickup messages stack up.
      const x = Math.floor(W * data.region.x0), y = Math.floor(H * data.region.y0), w = W - x, h = Math.floor(H * data.region.y1) - y;
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      context.drawImage(frame, x, y, w, h, 0, 0, w, h);
      frame.close();
      const lines = messageLines(context.getImageData(0, 0, w, h), true), fresh = newLines(previous, lines);
      for (let k = fresh - 1; k >= 0; k--) {
        const line = lines[k];
        postMessage({type: 'line', at: Date.now(), width: line.x1 - line.x0 + 1, height: line.y1 - line.y0, bits: line.bits}, [line.bits.buffer]);
      }
      previous = lines.map(({bits, ...rest}) => rest);
    } catch (error) {
      frame.close?.();
      postMessage({type: 'error', message: String(error)});
    }
    frames++; busy += performance.now() - started;
    if (performance.now() - since >= 2000) {
      postMessage({type: 'stats', fps: frames * 1000 / (performance.now() - since), msPerFrame: busy / frames});
      frames = 0; busy = 0; since = performance.now();
    }
  }
};

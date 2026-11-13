// Pickup message watcher, off the page's main thread. It receives the shared window's frames as a stream
// (MediaStreamTrackProcessor), copies only the message corner, follows the message stack and posts each
// message, with its line masks, once it has left the screen. Frames are closed at once.
import {captureScale, messageLines, stackTracker, unstretch} from './pickups.js';
import {readLine, seedFont} from './message-font.js';

// The shipped font reads each line's number while the stack is followed (see stackTracker's `read`).
const font = seedFont({}), read = (mask) => readLine(font, mask);

let reader = null, stretch = 'bilinear';  // The game's default stretch; the page passes its sharper filter's.

onmessage = async ({data}) => {
  if (data.type === 'stop') { reader?.cancel().catch(() => {}); reader = null; return; }
  if (data.type === 'stretch') { stretch = data.mode; return; }
  if (data.type !== 'start') return;
  reader = data.stream.getReader();
  const canvas = new OffscreenCanvas(1, 1), context = canvas.getContext('2d', {willReadFrequently: true});
  let tracker = stackTracker({read}), cache = {}, size = '', scale;
  let frames = 0, busy = 0, since = performance.now();
  while (reader) {
    const {value: frame, done} = await reader.read().catch(() => ({done: true}));
    if (done) break;
    const started = performance.now();
    try {
      const W = frame.displayWidth, H = frame.displayHeight;
      // A resized window (e.g. to fullscreen) moves every line: count afresh, or the slots voted for the
      // old size keep winning and every line lands in the wrong one (measured live).
      if (`${W}x${H}` !== size) { size = `${W}x${H}`; tracker = stackTracker({read}); cache = {}; scale = captureScale(W, H); }
      // Right of the quick-slot panel, above the status bar: where pickup messages stack up.
      const x = Math.max(0, Math.floor(Math.min(W * data.region.x0, W - data.region.minWidth))), y = Math.floor(H * data.region.y0), w = W - x, h = Math.floor(H * data.region.y1) - y;  // As regionBox.
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      context.drawImage(frame, x, y, w, h, 0, 0, w, h);
      frame.close();
      const image = context.getImageData(0, 0, w, h);
      const {sx, sy, mode} = scale;
      const corner = sx > 1 ? unstretch(image, sx, sy, x, y, cache, mode ?? stretch) : image;
      for (const {at, samples} of tracker.update(messageLines(corner, true), Date.now())) {
        postMessage({type: 'message', at, samples}, samples.flatMap((sample) => (sample.gray ? [sample.bits.buffer, sample.gray.buffer] : [sample.bits.buffer])));
      }
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

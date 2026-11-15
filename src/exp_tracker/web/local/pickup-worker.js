// Pickup message watcher, off the page's main thread. It receives the shared window's frames as a stream
// (Chrome) or opens a transferred track (Safari), copies only the message corner, follows the stack and posts each
// message, with its line masks, once it has left the screen. Frames are closed at once.
import {captureScale, messageLines, stackTracker, unstretch} from './pickups.js';
import {readLine, seedFont} from './message-font.js';

// The shipped font reads each line's number while the stack is followed (see stackTracker's `read`).
const font = seedFont({}), read = (mask) => readLine(font, mask);

let reader = null, track = null, stretch = 'bilinear';  // The game's default stretch; the page passes its sharper filter's.
let snapshot = false;

onmessage = async ({data}) => {
  if (data.type === 'stop') { reader?.cancel().catch(() => {}); reader = null; track?.stop(); track = null; return; }
  if (data.type === 'stretch') { stretch = data.mode; return; }
  if (data.type === 'snapshot') { snapshot = true; return; }
  if (data.type !== 'start') return;
  track = data.track ?? null;
  try {
    const stream = data.stream ?? new MediaStreamTrackProcessor({track}).readable;
    reader = stream.getReader();
  } catch (error) {
    track?.stop(); track = null;
    postMessage({type: 'error', message: `Cannot open pickup frames: ${error.message}`});
    return;
  }
  const canvas = new OffscreenCanvas(1, 1), context = canvas.getContext('2d', {willReadFrequently: true});
  postMessage({type: 'ready'});
  let tracker = stackTracker({read}), cache = {}, size = '', scale;
  let frames = 0, busy = 0, since = performance.now();
  let detectedFrames = 0, reported = 0;
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
      // Safari ignores the source crop on VideoFrame drawImage and squeezes the whole window into it.
      // Draw at full size there, then crop the canvas pixels instead.
      const full = Boolean(data.track), cw = full ? W : w, ch = full ? H : h;
      if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
      if (full) context.drawImage(frame, 0, 0, W, H);
      else context.drawImage(frame, x, y, w, h, 0, 0, w, h);
      frame.close();
      const image = context.getImageData(full ? x : 0, full ? y : 0, w, h);
      const {sx, sy, mode} = scale;
      const corner = sx > 1 ? unstretch(image, sx, sy, x, y, cache, mode ?? stretch) : image;
      // shortcut: unscaled worker tracks use the Safari-calibrated mask; revisit for other browsers on this path.
      const soft = Boolean(data.track) && sx === 1, lines = messageLines(corner, true, soft);
      if (lines.length) detectedFrames++;
      for (const {at, samples} of tracker.update(lines, Date.now())) {
        reported++;
        postMessage({type: 'message', at, samples, soft}, samples.flatMap((sample) => (sample.gray ? [sample.bits.buffer, sample.gray.buffer] : [sample.bits.buffer])));
      }
      if (snapshot) {
        snapshot = false;
        postMessage({type: 'snapshot', width: corner.width, height: corner.height, data: corner.data, frameSize: size}, [corner.data.buffer]);
      }
    } catch (error) {
      frame.close?.();
      postMessage({type: 'error', message: String(error)});
    }
    frames++; busy += performance.now() - started;
    if (performance.now() - since >= 2000) {
      postMessage({type: 'stats', fps: frames * 1000 / (performance.now() - since), msPerFrame: busy / frames, frameSize: size, detectedFrames, reported});
      frames = 0; busy = 0; since = performance.now();
    }
  }
};

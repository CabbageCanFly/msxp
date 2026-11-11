// Pickup message watcher, off the page's main thread. It receives the shared window's frames as a stream
// (MediaStreamTrackProcessor), copies only the message corner, follows the message stack and posts each
// message, with its line masks, once it has left the screen. Frames are closed at once.
import {GAME_HEIGHT, GAME_WIDTH, messageLines, stackTracker, unstretch} from './pickups.js';

let reader = null;

onmessage = async ({data}) => {
  if (data.type === 'stop') { reader?.cancel().catch(() => {}); reader = null; return; }
  if (data.type !== 'start') return;
  reader = data.stream.getReader();
  const canvas = new OffscreenCanvas(1, 1), context = canvas.getContext('2d', {willReadFrequently: true});
  const tracker = stackTracker(), cache = {};
  let frames = 0, busy = 0, since = performance.now();
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
      // A window wider than the game's screen shows it stretched: read the game's own pixels.
      // shortcut: assumes the window shows only the game (fullscreen or borderless); a stretched window with
      // a title bar shifts the rows. Measure the title bar if such windows turn up.
      const image = context.getImageData(0, 0, w, h);
      const corner = W / GAME_WIDTH > 1.03 ? unstretch(image, W / GAME_WIDTH, H / GAME_HEIGHT, x, y, cache) : image;
      for (const {at, samples} of tracker.update(messageLines(corner, true), Date.now())) {
        postMessage({type: 'message', at, samples}, samples.map((sample) => sample.bits.buffer));
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

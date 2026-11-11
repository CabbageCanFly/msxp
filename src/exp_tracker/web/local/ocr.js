// One persistent tesseract.js worker. Every runtime file is served from this site (no CDN):
// worker script, SIMD/LSTM WebAssembly core and English LSTM data under /static/local/vendor/.
import Tesseract from './vendor/tesseract.esm.min.js';
import {PARAMS} from './reader.js';
import {mapWords, pgm, stripImage, words} from './hud.js';
import {readerLock} from './lock.js';

const VENDOR = new URL('./vendor/', import.meta.url).href;

export async function createEngine() {
  const worker = await Tesseract.createWorker('eng', Tesseract.OEM.LSTM_ONLY, {
    workerPath: VENDOR + 'worker.min.js',
    corePath: VENDOR + 'tesseract-core-simd-lstm.js',
    langPath: VENDOR.replace(/\/$/, ''),
    workerBlobURL: false,  // Same-origin worker script: no blob: URL needed in the CSP.
    cacheMethod: 'none',   // The HTTP cache already holds the language file; keep IndexedDB for history only.
    gzip: true,
  });
  let mode = null;
  const setMode = async (next, params) => {
    if (mode !== next) { await worker.setParameters(params); mode = next; }
  };
  const engine = {
    stats: {calls: 0, ms: 0},
    async read(bytes, field) {
      await setMode(field, PARAMS[field]);
      const started = performance.now();
      const {data} = await worker.recognize(bytes);
      engine.stats.calls++; engine.stats.ms += performance.now() - started;
      return {text: data.text, confidence: data.confidence / 100};
    },
    // One sparse-text pass over the bottom of the window to find the status bar labels.
    async labels(frame) {
      await setMode('labels', {tessedit_pageseg_mode: '11', tessedit_char_whitelist: ''});
      const {box, scale, image} = stripImage(frame);
      const {data} = await worker.recognize(pgm(image), {}, {blocks: true, text: false});
      return mapWords(words(data), box, scale);
    },
    exclusive: readerLock(),
    terminate: () => worker.terminate(),
  };
  return engine;
}

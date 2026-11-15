// Offline replay of private Safari captures through the browser tracker's production readers, on the page's own
// OCR engine: the vendored tesseract.js-core 7.0.0 WebAssembly and English data, driven with the calls its worker
// makes. Results match the browser on every machine; an installed Tesseract (5.4.0, 5.5.3...) reads differently.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {gunzipSync} from 'node:zlib';
import {HUD_GLYPHS, displayed, learn} from '../src/exp_tracker/web/local/glyphs.js';
import {PARAMS, readHud, readIdentity} from '../src/exp_tracker/web/local/reader.js';
import {messageLines, stackTracker} from '../src/exp_tracker/web/local/pickups.js';
import {readMessage} from '../src/exp_tracker/web/local/pickup-session.js';
import {readLine, seedFont} from '../src/exp_tracker/web/local/message-font.js';
import {JOBS} from '../src/exp_tracker/web/local/view.js';

const spec = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const table = JSON.parse(readFileSync('src/exp_tracker/data/community-exp-v2.json', 'utf8'));
// As ocr.js: createWorker('eng', OEM.LSTM_ONLY), then each field's parameters when the field changes.
const vendor = new URL('../src/exp_tracker/web/local/vendor/', import.meta.url);
const core = await createRequire(import.meta.url)(fileURLToPath(new URL('tesseract-core-simd-lstm.js', vendor)))({});
core.FS.writeFile('/eng.traineddata', gunzipSync(readFileSync(new URL('eng.traineddata.gz', vendor))));
const api = new core.TessBaseAPI();
assert.equal(api.Init(null, 'eng', 1), 0, 'OCR engine failed to start');
let mode = null;
const engine = {exclusive: (fn) => fn(), async read(bytes, field) {
  if (mode !== field) { for (const [key, value] of Object.entries(PARAMS[field])) api.SetVariable(key, value); mode = field; }
  core.FS.writeFile('/input', bytes);
  assert.notEqual(api.SetImageFile(1, 0), 1, 'OCR could not read the image');
  api.Recognize(null);
  return {text: api.GetUTF8Text(), confidence: api.MeanTextConf() / 100};
}};

// Measured on the browser engine (2026-11-15): two of the twelve HUD strips (h10, h12) are skipped as unreadable,
// and c05 misses one item; Tesseract 5.5.3 read them. A skip keeps the last accepted state; a wrong
// reading never passes, and more skips than these fail.
const HUD_SKIPS = 2, ITEM_MISSES = 1;

if (spec.kind === 'hud') {
  for (const learning of [false, true]) {
    const templates = {...HUD_GLYPHS}, reads = {first: 0, continuing: 0};
    for (const c of spec.cases) {
      const frame = {width: c.width, height: c.height, data: new Uint8ClampedArray(readFileSync(c.rgba))};
      let result;
      // A first scan has no previous level for the EXP table to judge OCR variants by; a continuing scan has one.
      for (const [scan, previousLevel] of [['first', null], ['continuing', c.expected.level]]) {
        result = await readHud(engine, frame, c.regions, templates, {table, previousLevel, safari: true});
        if (result.status !== 'ok') continue;
        assert.deepEqual([result.level, result.exp, result.bp], [c.expected.level, c.expected.exp, c.expected.bp],
          `${c.id}, ${scan} scan, learning=${learning}`);
        reads[scan]++;
      }
      if (c.expected.job || c.expected.name) {
        const identity = await readIdentity(engine, frame, result.boxes, templates, JOBS);
        for (const field of ['job', 'name']) if (c.expected[field]) assert.equal(identity[field], c.expected[field], `${c.id} ${field}`);
      }
      if (learning && result.status === 'ok') {
        const text = displayed(result.exp, result.bp);
        learn(templates, result.segments.number, text.number);
        learn(templates, result.segments.percent, text.percent);
        if (result.levelSegments) learn(templates, result.levelSegments, String(result.level));
      }
    }
    for (const scan of ['first', 'continuing']) {
      assert.ok(reads[scan] >= spec.cases.length - HUD_SKIPS, `${scan} scans read ${reads[scan]} of ${spec.cases.length}, learning=${learning}`);
    }
    console.log(`learning=${learning}: first scans read ${reads.first}, continuing ${reads.continuing} of ${spec.cases.length}, none wrong.`);
  }
} else if (spec.kind === 'pickups') {
  const font = seedFont({}), tracker = stackTracker({read: (mask) => readLine(font, mask)});
  const raw = readFileSync(spec.rgba), bytes = spec.width * spec.height * 4, messages = [];
  assert.equal(raw.length, spec.index.frames.length * bytes);
  for (const [i, frame] of spec.index.frames.entries()) {
    const data = new Uint8ClampedArray(raw.buffer, raw.byteOffset + i * bytes, bytes);
    messages.push(...tracker.update(messageLines({width: spec.width, height: spec.height, data}, true, true), frame.at));
  }
  messages.push(...tracker.update([], spec.index.frames.at(-1).at + 2000));
  const items = JSON.parse(readFileSync('src/exp_tracker/web/local/items/items.json', 'utf8')).items
    .map(([name, tab, id]) => ({name, tab, id}));
  const found = {}, mesos = [], unmatched = [];
  for (const m of messages) {
    const result = await readMessage(engine, m.samples, items, font, true);
    if (result.parsed?.kind === 'item' && result.item) found[result.item.name] = (found[result.item.name] ?? 0) + result.parsed.count;
    else if (result.parsed?.kind === 'item') unmatched.push(result.text);
    if (result.parsed?.kind === 'mesos') { assert.equal(result.parsed.approx, false); mesos.push(result.parsed.amount); }
  }
  // Never an item that was not picked up, nor more of one; an unmatched name is shown as read, not counted.
  for (const [name, count] of Object.entries(found)) assert.ok(count <= (spec.expected.items[name] ?? 0), `${spec.id}: ${count} x ${name}`);
  const missed = Object.entries(spec.expected.items).reduce((sum, [name, count]) => sum + count - (found[name] ?? 0), 0);
  assert.ok(missed <= ITEM_MISSES, `${spec.id}: ${missed} items missed (${unmatched.join(' | ')})`);
  assert.deepEqual(mesos.sort((a, b) => a - b), [...spec.expected.mesos].sort((a, b) => a - b), `${spec.id} mesos`);
  console.log(`Passed ${spec.id}: ${spec.index.frames.length} frames, exact meso amounts, ${missed} item(s) missed${unmatched.length ? ` (shown as read: ${unmatched.join(' | ')})` : ''}.`);
} else throw new Error(`Unknown replay kind: ${spec.kind}`);

// Offline replay of private Safari captures through the browser tracker's production readers.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {dirname, join} from 'node:path';
import {HUD_GLYPHS, displayed, learn} from '../src/exp_tracker/web/local/glyphs.js';
import {PARAMS, readHud, readIdentity} from '../src/exp_tracker/web/local/reader.js';
import {messageLines, stackTracker} from '../src/exp_tracker/web/local/pickups.js';
import {readMessage} from '../src/exp_tracker/web/local/pickup-session.js';
import {readLine, seedFont} from '../src/exp_tracker/web/local/message-font.js';
import {JOBS} from '../src/exp_tracker/web/local/view.js';

const spec = JSON.parse(readFileSync(process.argv[2], 'utf8')), temporary = dirname(process.argv[2]);
const table = JSON.parse(readFileSync('src/exp_tracker/data/community-exp-v2.json', 'utf8'));
const cache = new Map();
const engine = {exclusive: (fn) => fn(), async read(bytes, field) {
  const key = createHash('sha256').update(bytes).update(field).digest('hex');
  if (!cache.has(key)) {
    const path = join(temporary, 'ocr.pgm');
    writeFileSync(path, bytes);
    const params = PARAMS[field];
    const text = execFileSync(spec.tesseract, [path, 'stdout', '--tessdata-dir', spec.tessdata, '-l', 'eng',
      '--psm', params.tessedit_pageseg_mode, '-c', `tessedit_char_whitelist=${params.tessedit_char_whitelist}`],
    {encoding: 'utf8', timeout: 30000, stdio: ['ignore', 'pipe', 'pipe']}).trim();
    cache.set(key, text);
  }
  return {text: cache.get(key)};
}};

if (spec.kind === 'hud') {
  for (const learning of [false, true]) {
    const templates = {...HUD_GLYPHS};
    for (const c of spec.cases) {
      const frame = {width: c.width, height: c.height, data: new Uint8ClampedArray(readFileSync(c.rgba))};
      const result = await readHud(engine, frame, c.regions, templates,
        {table, previousLevel: c.expected.level, safari: true});
      assert.deepEqual([result.status, result.level, result.exp, result.bp],
        ['ok', c.expected.level, c.expected.exp, c.expected.bp], `${c.id}, learning=${learning}`);
      if (c.expected.job || c.expected.name) {
        const identity = await readIdentity(engine, frame, result.boxes, templates, JOBS);
        for (const field of ['job', 'name']) if (c.expected[field]) assert.equal(identity[field], c.expected[field], `${c.id} ${field}`);
      }
      if (learning) {
        const text = displayed(result.exp, result.bp);
        learn(templates, result.segments.number, text.number);
        learn(templates, result.segments.percent, text.percent);
        if (result.levelSegments) learn(templates, result.levelSegments, String(result.level));
      }
    }
  }
  console.log(`Passed ${spec.cases.length} HUD captures with fresh and learned glyphs.`);
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
  const found = {}, mesos = [];
  for (const m of messages) {
    const result = await readMessage(engine, m.samples, items, font, true);
    if (result.parsed?.kind === 'item' && result.item) found[result.item.name] = (found[result.item.name] ?? 0) + result.parsed.count;
    if (result.parsed?.kind === 'mesos') { assert.equal(result.parsed.approx, false); mesos.push(result.parsed.amount); }
  }
  assert.deepEqual(found, spec.expected.items, `${spec.id} items`);
  assert.deepEqual(mesos.sort((a, b) => a - b), [...spec.expected.mesos].sort((a, b) => a - b), `${spec.id} mesos`);
  console.log(`Passed ${spec.id}: ${spec.index.frames.length} frames, exact items and meso amounts.`);
} else throw new Error(`Unknown replay kind: ${spec.kind}`);

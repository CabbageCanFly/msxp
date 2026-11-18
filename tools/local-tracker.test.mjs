// Unit tests for the browser-only local tracker (/local): parsing, EXP-table checks, tracking and stats.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const web = new URL('../src/exp_tracker/web/local/', import.meta.url);
const E = await import(new URL('exp.js', web));
const H = await import(new URL('hud.js', web));
const V = await import(new URL('view.js', web));
const table = JSON.parse(readFileSync(new URL('../src/exp_tracker/data/community-exp-v2.json', import.meta.url)));
const at = (s) => Date.UTC(2026, 0, 1) + s * 1000;
// Synthetic readings from the published requirement, so tests never hold real character data.
const pair = (level, exp) => ({level, exp, bp: Math.floor(exp * 10000 / table.to_next[level])});
const r = (s, level, exp) => ({at: at(s), ...pair(level, exp)});

// Run the capture entry point and frame copy with synthetic browser frames, without OCR or storage.
const app = readFileSync(new URL('app.js', web), 'utf8');
const pickupSession = readFileSync(new URL('pickup-session.js', web), 'utf8');
const pickupWorker = readFileSync(new URL('pickup-worker.js', web), 'utf8').replace(/^import .*;\n/gm, '');

test('Safari HUD workarounds exclude Chrome, Edge and Firefox user agents', () => {
  const flag = app.match(/^const safari = .*;$/m)[0];
  for (const [userAgent, expected] of [
    ['Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Version/26.1 Safari/605.1.15', true],
    ['Mozilla/5.0 (iPhone) Version/18.0 Mobile/15E148 Safari/604.1', true],
    ['Mozilla/5.0 (Macintosh) Chrome/140.0.0.0 Safari/537.36', false],
    ['Mozilla/5.0 (Windows NT 10.0) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0', false],
    ['Mozilla/5.0 (Macintosh) Gecko/20100101 Firefox/140.0', false],
    ['Mozilla/5.0 (iPhone) CriOS/140.0.0.0 Mobile/15E148 Safari/604.1', false],
    ['Mozilla/5.0 Version/26.1 Safari/605.1.15 OPR/120.0', false],
  ]) assert.equal(vm.runInNewContext(`${flag}\nsafari`, {navigator: {userAgent}}), expected, userAgent);
});

test('Safari restores shipped HUD shapes over stale learned conflicts without changing other browsers', async () => {
  const G = await import(new URL('glyphs.js', web));
  const six = Object.keys(G.HUD_GLYPHS).find((k) => G.HUD_GLYPHS[k] === '6');
  const learned = {[six]: '?', extra: '4'};
  for (const safari of [true, false]) {
    const context = vm.createContext({safari, GAME_WIDTH: 1368, HUD_GLYPHS: G.HUD_GLYPHS, safariGlyphs: G.safariGlyphs,
      settings: {glyphs: {game: learned, '2000x1000': learned}}});
    vm.runInContext(app.slice(app.indexOf('const glyphSize ='), app.indexOf('async function teachLetters(')), context);
    const native = vm.runInContext('templatesFor({full: {width: 1366, height: 796}})', context);
    assert.equal(native[six], safari ? '6' : '?'); assert.equal(native.extra, '4');
    const stretched = vm.runInContext('templatesFor({full: {width: 2000, height: 1000}})', context);
    assert.equal(stretched[six], '?'); assert.equal(learned[six], '?');
  }
});

for (const mode of ['native folder', 'native downloads', 'video downloads']) {
  test(`pickup recorder preserves its frame/index pair: ${mode}`, async () => {
    const downloads = [], blobs = new Map(), files = new Map(), constraints = [];
    let click, clock = 0, closed = 0, cloneStopped = 0;
    const frame = () => ({displayWidth: 800, displayHeight: 600, close() { closed++; }});
    const clone = {stop() { cloneStopped++; }}, video = {videoWidth: 800};
    const current = {video, track: {clone: () => clone, async applyConstraints(c) { constraints.push(c.frameRate.max); }}};
    const folder = {name: 'test recording', async getFileHandle(name) { return {async createWritable() {
      return {async write(data) { files.set(name, data); }, async close() {}};
    }}; }};
    const window = {}, context = vm.createContext({window, capture: current, Blob, ReadableStream, TextEncoder,
      document: {createElement(tag) { return tag === 'button' ? {addEventListener(_, fn) { click = fn; }} : {click() { downloads.push(this); }}; }},
      performance: {now() { const at = clock; clock += 10000; return at; }},
      setTimeout(fn) { queueMicrotask(fn); }, setStatus() {}, regionBox: () => ({x: 500, y: 270, w: 300, h: 264}),
      URL: {createObjectURL(blob) { const key = String(blobs.size); blobs.set(key, blob); return key; }, revokeObjectURL() {}},
      OffscreenCanvas: class { getContext() { return {drawImage(source, ...args) {
        assert.equal(source === video, mode === 'video downloads');
        assert.deepEqual(args, [500, 270, 300, 264, 0, 0, 300, 264]);
      }}; } async convertToBlob() { return new Blob([new Uint8Array([1, 2, 3])]); } },
      VideoFrame: class { constructor(input) { assert.equal(input, video); return frame(); } },
      ...(mode === 'native folder' ? {showDirectoryPicker: async () => ({getDirectoryHandle: async () => folder})} : {}),
    });
    if (mode.startsWith('native')) {
      context.MediaStreamTrackProcessor = window.MediaStreamTrackProcessor = class {
        constructor({track}) {
          assert.equal(track, clone); let sent = false;
          this.readable = new ReadableStream({pull(controller) {
            if (sent) controller.close(); else { sent = true; controller.enqueue(frame()); }
          }}, {highWaterMark: 0});
        }
      };
    }
    vm.runInContext(app.slice(app.indexOf('function recordingArchive('), app.indexOf('function setupDebug()')), context);
    vm.runInContext('recordButton()', context);
    await click();
    for (let i = 0; i < 20 && current.recording; i++) await new Promise(setImmediate);
    assert.equal(current.recording, null);
    let index, binary;
    if (mode === 'native folder') { index = JSON.parse(files.get('index.json')); binary = files.get('frames.bin'); }
    else {
      assert.equal(downloads.length, 1); assert.match(downloads[0].download, /\.tar$/);
      const archive = new Uint8Array(await blobs.get(downloads[0].href).arrayBuffer()), entries = {};
      const text = (bytes) => new TextDecoder().decode(bytes).replace(/\0.*$/s, '');
      let offset = 0;
      for (let i = 0; i < 2; i++) {
        const header = archive.slice(offset, offset + 512), size = parseInt(text(header.subarray(124, 136)), 8);
        const checksum = parseInt(text(header.subarray(148, 156)), 8);
        header.fill(32, 148, 156);
        assert.equal(header.reduce((sum, byte) => sum + byte, 0), checksum);
        assert.equal(text(header.subarray(257, 263)), 'ustar');
        entries[text(header.subarray(0, 100))] = archive.slice(offset + 512, offset + 512 + size);
        offset += 512 + Math.ceil(size / 512) * 512;
      }
      assert.equal(archive.length - offset, 1024); assert.ok(archive.subarray(offset).every((b) => b === 0));
      index = JSON.parse(text(entries['index.json'])); binary = new Blob([entries['frames.bin']]);
    }
    assert.equal(index.frame, '800x600'); assert.equal(index.frames.length, 1);
    assert.equal(index.frames[0].offset, 0); assert.equal(index.frames[0].size, binary.size);
    assert.deepEqual(index.region, {x: 500, y: 270, w: 300, h: 264});
    assert.equal(closed, mode === 'video downloads' ? 2 : 1);
    assert.equal(cloneStopped, mode.startsWith('native') ? 1 : 0);
    assert.deepEqual(constraints, [15, 5]);
  });
}

test('failed HUD crops persist separately, deduplicate, respect the disk cap and export together', async () => {
  const values = new Map([['unrelated-history-setting', 'keep']]);
  const storage = vm.createContext({TextEncoder, getSetting: async (key) => structuredClone(values.get(key)),
    result: async (v) => v, run: async (_, __, body) => body({objectStore: () => ({
      get: (key) => structuredClone(values.get(key)), put: (value, key) => values.set(key, structuredClone(value)),
      delete: (key) => values.delete(key),
    })}),
  });
  const source = readFileSync(new URL('store.js', web), 'utf8');
  vm.runInContext(source.slice(source.indexOf('export const HUD_DEBUG_LIMIT'), source.indexOf('export const characters')).replaceAll('export ', ''), storage);
  const store = vm.runInContext('({HUD_DEBUG_LIMIT, hudIssueIndex, saveHudIssue, clearHudIssues, getSetting})', storage);
  const buttons = {}, downloads = [], blobs = [], copied = [];
  let encoded = 0;
  const context = vm.createContext({store, hudRecording: null, safari: true, crypto, Blob, TextEncoder, Date,
    $: (id) => buttons[id] ??= {}, templatesFor: () => ({glyph: '2'}), setStatus() {}, setTimeout() {},
    document: {createElement: () => ({click() { downloads.push(this); }})},
    URL: {createObjectURL(blob) { blobs.push(blob); return String(blobs.length); }, revokeObjectURL() {}},
    ImageData: class {}, OffscreenCanvas: class {
      constructor(w, h) { assert.deepEqual([w, h], [40, 10]); }
      getContext() { return {putImageData(_, x, y) { copied.push([x, y]); }}; }
      async convertToBlob() { encoded++; return new Blob([new Uint8Array([1, 2, 3])]); }
    },
  });
  vm.runInContext(app.slice(app.indexOf('function recordingArchive('), app.indexOf('function recordButton()')) +
    app.slice(app.indexOf('async function renderHudIssues('), app.indexOf('function setupDebug()')), context);
  const scan = {status: 'ambiguous', reason: 'unclear', at: 10, previousLevel: 7,
    frame: {width: 100, height: 30, data: new Uint8ClampedArray(12000), top: 300, full: {width: 100, height: 400}},
    regions: {exp: {x0: 20, y0: 10, x1: 60, y1: 20}}, raw: {exp: [{text: 'bad'}]}};
  context.scan = scan;
  await vm.runInContext('startHudRecording();', context);
  await vm.runInContext("recordHudScan({...scan, status: 'ok'})", context);
  assert.equal(encoded, 0);
  await vm.runInContext('recordHudScan(scan)', context);
  await vm.runInContext('recordHudScan({...scan, at: 20})', context);
  assert.equal(downloads.length, 0);  // A failed scan never triggers its own download.
  let index = await store.hudIssueIndex();
  assert.equal(index.keys.length, 1);
  const saved = await store.getSetting('debug-hud-' + index.keys[0]);
  assert.deepEqual(JSON.parse(JSON.stringify(saved.scan.origin)), {x: 20, y: 310});
  assert.equal(saved.scan.regions.exp.x0, 0); assert.equal(saved.scan.regions.exp.y0, 0);
  assert.equal(saved.scan.repeats, 2); assert.equal(saved.scan.lastAt, 20);
  assert.equal(saved.scan.previousLevel, 7); assert.equal(saved.scan.templates.glyph, '2');
  assert.deepEqual(copied, [[-20, -10], [-20, -10]]);
  // Starting another page/session finds the stored crops; no PNG array is retained in recording state.
  await vm.runInContext('startHudRecording()', context);
  assert.match(buttons['hud-save-issues'].textContent, /\(1 /);
  assert.equal(vm.runInContext('hudRecording.chunks', context), undefined);
  await vm.runInContext('downloadHudIssues()', context);
  assert.equal(downloads.length, 1); assert.match(downloads[0].download, /^msxp-exp-.*\.tar$/);
  const tar = new Uint8Array(await blobs[0].arrayBuffer());
  const text = (b) => new TextDecoder().decode(b).replace(/\0.*$/s, '');
  assert.equal(text(tar.subarray(0, 100)), 'frames.bin');
  assert.deepEqual([...tar.subarray(512, 515)], [1, 2, 3]);
  assert.equal(text(tar.subarray(1024, 1124)), 'index.json');
  const length = parseInt(text(tar.subarray(1148, 1160)), 8);
  const manifest = JSON.parse(new TextDecoder().decode(tar.subarray(1536, 1536 + length)));
  assert.equal(manifest.frames[0].offset, 0); assert.equal(manifest.frames[0].size, 3);
  assert.equal(manifest.frames[0].repeats, 2);
  assert.equal((await store.hudIssueIndex()).keys.length, 1);  // Download attempts never erase the originals.
  scan.frame.data[(10 * 100 + 20) * 4] = 255;
  await vm.runInContext('recordHudScan({...scan, at: 30})', context);
  assert.equal((await store.hudIssueIndex()).keys.length, 2);  // Changed EXP pixels count even if PNG bytes match.
  scan.frame.data[0] = 255;
  await vm.runInContext('recordHudScan({...scan, at: 40})', context);
  index = await store.hudIssueIndex();
  assert.equal(index.keys.length, 2);  // Pixels outside the actual regions do not consume another slot.
  const full = {...index, bytes: store.HUD_DEBUG_LIMIT};
  values.set('debug-hud-index', full);
  assert.equal((await store.saveHudIssue('new', new Blob(['data']), {at: 30})).full, true);
  assert.equal(values.has('debug-hud-new'), false);
  await store.clearHudIssues();
  assert.equal((await store.hudIssueIndex()).keys.length, 0);
  assert.equal(values.get('unrelated-history-setting'), 'keep');
});

for (const mode of ['page processor', 'worker processor', 'transfer failure', 'worker failure', 'startup timeout']) {
  test(`pickup session opens and releases its cloned track: ${mode}`, async () => {
    const constraints = [], sent = [];
    let stopped = 0, terminated = 0;
    const clone = {stop() { stopped++; }}, track = {clone: () => clone, async applyConstraints(c) { constraints.push(c.frameRate.max); }};
    const readable = {}, window = {};
    class MediaStreamTrackProcessor {
      constructor(options) { assert.equal(options.track, clone); this.readable = readable; }
    }
    if (mode === 'page processor') window.MediaStreamTrackProcessor = MediaStreamTrackProcessor;
    class Worker {
      constructor() { context.worker = this; }
      postMessage(data, transfers) {
        sent.push({data, transfers});
        if (data.type !== 'start') return;
        if (mode === 'transfer failure') throw new Error('transfer failed');
        if (mode === 'worker failure') this.onerror({message: 'worker failed'});
        else if (mode !== 'startup timeout') this.onmessage({data: {type: 'ready'}});
      }
      terminate() { terminated++; }
    }
    const context = vm.createContext({window, MediaStreamTrackProcessor, Worker, URL, setTimeout, clearTimeout,
      loadItems: async () => [], REGION: {}, track, engine: {},
      ...(mode === 'startup timeout' ? {setTimeout(fn) { queueMicrotask(fn); }} : {}),
    });
    vm.runInContext(pickupSession.slice(pickupSession.indexOf('export async function startPickups'))
      .replace('export async', 'async').replace('import.meta.url', JSON.stringify(new URL('pickup-session.js', web).href)), context);
    const start = vm.runInContext('startPickups({track, engine, onMessage() {}})', context);
    if (mode.endsWith('failure') || mode === 'startup timeout') {
      await assert.rejects(start, /failed|did not start/);
    } else {
      const session = await start, message = sent[0];
      assert.equal(message.transfers[0], mode === 'page processor' ? readable : clone);
      assert.equal(message.data.stream, mode === 'page processor' ? readable : undefined);
      assert.equal(message.data.track, mode === 'worker processor' ? clone : undefined);
      session.setStretch('area'); assert.equal(sent[1].data.mode, 'area');
      const snapshot = session.snapshot();
      assert.equal(sent[2].data.type, 'snapshot');
      await assert.rejects(session.snapshot(), /already pending/);
      context.worker.onmessage({data: {type: 'snapshot', width: 2, height: 1, data: new Uint8ClampedArray(8), frameSize: '800x600'}});
      assert.equal((await snapshot).frameSize, '800x600');
      const cancelled = session.snapshot(), rejected = assert.rejects(cancelled, /has stopped/);
      await session.stop(); await rejected;
      assert.equal(sent[4].data.type, 'stop');
      await assert.rejects(session.snapshot(), /has stopped/);
    }
    assert.equal(stopped, 1); assert.equal(terminated, 1);
    assert.deepEqual(constraints, [15, 5]);
  });
}

for (const mode of ['stream', 'track', 'scaled track', 'unsupported']) {
  test(`pickup worker reads frames and reports startup: ${mode}`, async () => {
    const posted = [], copies = [], pixels = new Uint8ClampedArray(300 * 264 * 4);
    let closed = 0, stopped = 0, processed = 0;
    const track = {stop() { stopped++; }};
    const frame = {displayWidth: 800, displayHeight: 600, close() { closed++; }};
    const frames = [frame], stream = {getReader: () => ({async read() { const value = frames.shift(); return {value, done: !value}; }, async cancel() {}})};
    const context = vm.createContext({postMessage: (data) => posted.push(data), performance: {now: () => closed ? 2001 : 0},
      seedFont: (font) => font, readLine() {}, captureScale: () => mode === 'scaled track' ? {sx: 2, sy: 2} : {sx: 1, sy: 1}, unstretch: (image) => image,
      messageLines: (_, keep, soft) => {
        assert.equal(keep, true); assert.equal(soft, mode === 'track');
        return mode === 'stream' || mode === 'track' ? [{}] : [];
      },
      stackTracker: () => ({update: (lines) => lines.length ? [{at: 123, samples: [{bits: new Uint8Array([1])}]}] : []}),
      OffscreenCanvas: class { getContext() { return {
        drawImage(...args) { copies.push(args); }, getImageData: (...args) => {
          assert.deepEqual(args, mode === 'stream' ? [0, 0, 300, 264] : [500, 270, 300, 264]);
          return {width: 300, height: 264, data: pixels};
        },
      }; } },
      ...(mode !== 'unsupported' ? {MediaStreamTrackProcessor: class {
        constructor(options) { assert.equal(options.track, track); processed++; this.readable = stream; }
      }} : {}),
    });
    vm.runInContext(pickupWorker, context);
    await context.onmessage({data: {type: 'snapshot'}});
    await context.onmessage({data: {type: 'start', ...(mode === 'stream' ? {stream} : {track}),
      region: {x0: .75, y0: .45, y1: .89, minWidth: 300}}});
    if (mode === 'unsupported') {
      assert.equal(posted[0].type, 'error'); assert.match(posted[0].message, /Cannot open pickup frames/);
      assert.equal(stopped, 1); assert.equal(closed, 0);
    } else {
      assert.equal(posted[0].type, 'ready'); assert.equal(closed, 1);
      const stats = posted.find((m) => m.type === 'stats');
      assert.equal(stats.detectedFrames, mode === 'scaled track' ? 0 : 1);
      assert.equal(stats.reported, mode === 'scaled track' ? 0 : 1);
      assert.equal(stats.frameSize, '800x600');
      const snapshot = posted.find((m) => m.type === 'snapshot');
      assert.equal(snapshot.data, pixels); assert.equal(snapshot.width, 300); assert.equal(snapshot.height, 264);
      assert.equal(posted.filter((m) => m.type === 'message').length, stats.reported);
      for (const message of posted.filter((m) => m.type === 'message')) assert.equal(message.soft, mode === 'track');
      assert.equal(processed, mode === 'stream' ? 0 : 1);
      assert.deepEqual(copies[0].slice(1), mode === 'stream' ? [500, 270, 300, 264, 0, 0, 300, 264] : [0, 0, 800, 600]);
      await context.onmessage({data: {type: 'stop'}});
      assert.equal(stopped, mode === 'stream' ? 0 : 1);
    }
  });
}

for (const mode of ['no ImageCapture', 'ImageCapture without grabFrame', 'ImageCapture with grabFrame']) {
  test(`capture reads full frames and HUD bands: ${mode}`, async () => {
    let played = 0, grabbed = 0, closed = 0;
    const copies = [], track = {addEventListener() {}}, stream = {getVideoTracks: () => [track]};
    const video = {videoWidth: 800, videoHeight: 600, async play() { played++; }};
    const bitmap = {width: 800, height: 600, close() { closed++; }};
    class ImageCapture {
      constructor(input) { assert.equal(input, track); }
    }
    if (mode === 'ImageCapture with grabFrame') ImageCapture.prototype.grabFrame = async () => { grabbed++; return bitmap; };
    const window = {addEventListener() {}};
    if (mode !== 'no ImageCapture') window.ImageCapture = ImageCapture;
    const context = vm.createContext({window, ImageCapture, capture: null, character: {id: 1}, debug: false,
      navigator: {userAgent: 'test browser', mediaDevices: {getDisplayMedia: async () => stream}},
      document: {body: {dataset: {}}, createElement(tag) { assert.equal(tag, 'video'); return video; }},
      $: () => ({}), setStatus() {}, acquireLock: async () => true, beginSession: async () => {},
      getEngine: async () => {}, store: {prune: async () => {}}, scan() {}, startPickupTracking() {},
      guardUnload() {}, setInterval() {}, setTimeout() {}, captureScale: () => ({sx: 1, sy: 1}),
      OffscreenCanvas: class {
        getContext() { return {
          drawImage(...args) { copies.push(args); },
          getImageData: () => ({data: new Uint8ClampedArray(this.width * this.height * 4)}),
        }; }
      },
    });
    vm.runInContext(app.slice(app.indexOf('let starting ='), app.indexOf('async function beginSession()')) +
      app.slice(app.indexOf('async function grab('), app.indexOf('const isFull =')), context);
    await vm.runInContext('start()', context);
    assert.equal(context.capture.stream, stream);
    assert.equal(played, mode === 'ImageCapture with grabFrame' ? 0 : 1);
    const full = await vm.runInContext('grab()', context);
    assert.equal(full.width, 800); assert.equal(full.height, 600); assert.equal(full.top, 0);
    const band = await vm.runInContext('grab({y0: 500, y1: 560})', context);
    assert.equal(band.width, 800); assert.equal(band.height, 60); assert.equal(band.top, 500);
    assert.equal(band.full.height, 600);
    assert.equal(copies[0][0], played ? video : bitmap);
    assert.deepEqual(copies[1].slice(1), [0, 500, 800, 60, 0, 0, 800, 60]);
    assert.equal(grabbed, played ? 0 : 2); assert.equal(closed, grabbed);
    if (played) {
      assert.equal(video.srcObject, stream); assert.equal(video.muted, true); assert.equal(video.playsInline, true);
      video.videoWidth = 0;
      await assert.rejects(vm.runInContext('grab()', context), /no_frame/);
    }
  });
}

test('strict EXP parsing never invents punctuation', () => {
  assert.deepEqual(E.parseExp('5,477[27.09%]'), {exp: 5477, bp: 2709});
  assert.deepEqual(E.parseExp('5.477[27.09%]'), {exp: 5477, bp: 2709});
  assert.deepEqual(E.parseExp('EXP.641,122[65.59%]'), {exp: 641122, bp: 6559});
  for (const bad of ['5477127.09%]', '5,477[27.09%', '5,477[27.9%]', '54,77[27.09%]', '.5.477[27.09%]', '5,477[127.09%]', '']) {
    assert.equal(E.parseExp(bad), null, bad);
  }
  assert.equal(E.parseLevel('20'), 20);
  assert.equal(E.parseLevel('LV.56'), 56);
  for (const bad of ['0', '201', '2O', '']) assert.equal(E.parseLevel(bad), null, bad);
});

test('EXP table consistency accepts either rounding and rejects disagreement', () => {
  const total = table.to_next['20'];
  const exp = Math.floor(total * .2709) + 1;
  assert.equal(E.consistency(table, 20, exp, Math.floor(exp * 10000 / total)), 'consistent');
  assert.equal(E.consistency(table, 20, exp, Math.floor(exp * 10000 / total) + 7), 'inconsistent');
  assert.equal(E.consistency(table, 20, total, 0), 'inconsistent');
  assert.equal(E.consistency(table, 150, 1, 0), 'unknown');  // No published requirement: never extrapolated.
});

test('level resolution needs OCR and table to agree, or continuity with the previous level (or the next)', () => {
  const {exp, bp} = pair(20, 5000);
  assert.deepEqual(E.resolveLevel(table, 20, exp, bp, null), {level: 20, evidence: 'ocr_and_table'});
  assert.equal(E.resolveLevel(table, 26, exp, bp, null).level, null);  // Misread badge, no history.
  assert.deepEqual(E.resolveLevel(table, null, exp, bp, 20), {level: 20, evidence: 'table_continuity'});
  assert.equal(E.resolveLevel(table, null, exp, bp, null).reason, 'level_unreadable');
  // An unread badge after a level-up: the next level when the pair fits it exactly; never two levels on.
  assert.deepEqual(E.resolveLevel(table, null, exp, bp, 19), {level: 20, evidence: 'table_levelup'});
  assert.equal(E.resolveLevel(table, null, exp, bp, 18).level, null);
  assert.equal(E.resolveLevel(table, 100, 123, 0, null).evidence, 'ocr_only');  // The cap has no requirement.
  assert.equal(E.resolveLevel(table, 150, 123, 0, null).reason, 'level_unreadable');  // Above the cap: a misread.
  assert.deepEqual(E.resolveLevel(table, 120, exp, bp, 20), {level: 20, evidence: 'table_continuity'});  // "20" read as "120".
});

function run(readings, state = {last: null, pending: null}) {
  const out = [];
  for (const reading of readings) {
    const result = E.step(table, state, reading);
    state = result.state;
    out.push(result);
  }
  return {state, out, accepted: out.flatMap((o) => o.accept)};
}

test('first reading waits for confirmation, then gains are endpoint differences', () => {
  const {out, accepted} = run([r(0, 20, 5000), r(20, 20, 5100), r(40, 20, 5100), r(60, 20, 5400)]);
  assert.deepEqual(out.map((o) => o.status), ['pending', 'accepted', 'accepted', 'accepted']);
  assert.deepEqual(accepted.map((a) => [a.kind, a.gain]), [['baseline', null], ['gain', 100], ['gain', 0], ['gain', 300]]);
});

test('a one-off misread neither counts nor replaces the accepted state', () => {
  // 5,100 then a bogus 4,100 then back on track: the bogus value is pending and then dropped.
  const {out, accepted, state} = run([r(0, 20, 5000), r(20, 20, 5100), r(40, 20, 4100), r(60, 20, 5200)]);
  assert.equal(out[2].status, 'pending');
  assert.equal(out[3].status, 'accepted');
  assert.equal(state.pending, null);
  assert.deepEqual(accepted.map((a) => a.gain), [null, 100, 100]);
});

test('EXP loss (death) is confirmed as a new baseline and never counted', () => {
  const {out, accepted} = run([r(0, 20, 5000), r(20, 20, 5100), r(40, 20, 4900), r(60, 20, 4950)]);
  assert.deepEqual(out.map((o) => o.reason), ['awaiting_confirmation', 'first_baseline', 'exp_decrease_pending', 'new_baseline']);
  assert.deepEqual(accepted.map((a) => a.gain), [null, 100, null, 50]);
});

test('a confirmed +1 level-up counts the EXP across the boundary', () => {
  const total = table.to_next['20'];
  const {accepted} = run([r(0, 20, total - 300), r(20, 20, total - 200), r(40, 21, 50), r(60, 21, 80)]);
  assert.deepEqual(accepted.map((a) => [a.kind, a.gain]), [['baseline', null], ['gain', 100], ['level_up', 250], ['gain', 30]]);
});

test('percentage-only: parsed and estimated as the Twitch tracker; misreads and badge errors never overcount', () => {
  // The cases of docs/percentage-only-level51.md (brackets are found in pixels, so the field is the inside).
  assert.deepEqual(['70.51%', '0.00%', '100.00%', ' 7.05% '].map(E.parsePercent), [7051, 0, 10000, 705]);
  for (const bad of ['70.5%', '100.01%', '7 0.51%', '70.51', '70.51%1', '.12%']) assert.equal(E.parsePercent(bad), null, bad);
  const total = E.requirement(table, 71);
  assert.equal(E.estimateExp(table, 71, 7863), Math.floor((7863 * total + 5000) / 10000));  // Half up.
  assert.equal(E.estimateExp(table, 100, 5000), null);  // No published requirement: no EXP.
  const est = (s, level, bp) => ({at: at(s), level, bp, exp: E.estimateExp(table, level, bp), estimated: true});
  const gains = (readings) => run(readings).accepted.reduce((sum, a) => sum + (a.gain ?? 0), 0);
  assert.equal(gains([est(0, 71, 7863), est(5, 71, 7863), est(10, 71, 7866), est(15, 71, 7870)]), est(0, 71, 7870).exp - est(0, 71, 7863).exp);
  // A blurred 7 read as 2 once (78.63 -> 72.63), or the same misread twice in a row: never counted.
  const truth = est(0, 71, 7870).exp - est(0, 71, 7863).exp;
  assert.ok(gains([est(0, 71, 7863), est(5, 71, 7863), est(10, 71, 7263), est(15, 71, 7863), est(20, 71, 7870)]) <= truth);
  assert.ok(gains([est(0, 71, 7863), est(5, 71, 7863), est(10, 71, 8863), est(15, 71, 8863), est(20, 71, 7870), est(25, 71, 7870)]) <= truth);
  // A real level-up counts across the boundary; a badge misread as the next level at the same percentage does not.
  const up = run([est(0, 71, 9990), est(5, 71, 9995), est(10, 72, 10), est(15, 72, 12)]).accepted;
  assert.deepEqual(up.map((a) => a.kind), ['baseline', 'gain', 'level_up', 'gain']);
  assert.equal(up[2].gain, total - est(0, 71, 9995).exp + est(0, 72, 10).exp);
  assert.ok(!run([est(0, 71, 7863), est(5, 71, 7863), est(10, 72, 7863), est(15, 72, 7863)]).accepted.some((a) => a.kind === 'level_up'));
});

test('Free play: another name on screen for three scans starts a fresh baseline; fades never do', async () => {
  const source = app.match(/^async function identifyFree\(current, outcome, at\) \{[\s\S]*?^\}$/m)[0];
  let evidence = 'ocr_and_table';
  const identifyFree = vm.runInNewContext(`(${source.replace('async function identifyFree', 'async function')})`, {asReading: () => ({evidence})});
  const scan = (key) => ({identity: key ? {nameKey: key} : null});
  const current = {tracker: {last: r(0, 20, 5000), pending: null, reference: null}};
  assert.equal(await identifyFree(current, scan('A'), 0), null);  // The first name is adopted at once.
  assert.equal(current.tracker.last.exp, 5000);
  assert.equal(await identifyFree(current, scan('A'), 1), null);
  assert.equal(await identifyFree(current, scan(null), 2), null);  // No name line: carry on.
  evidence = 'none';  // A logout fade: never counts toward a change.
  assert.equal(await identifyFree(current, scan('B'), 3), 'name_confirming');
  evidence = 'ocr_and_table';
  assert.equal(await identifyFree(current, scan('B'), 4), 'name_confirming');
  assert.equal(await identifyFree(current, scan('B'), 5), 'name_confirming');
  assert.equal(current.tracker.last.exp, 5000);  // Not yet: the previous character's state is kept.
  assert.equal(await identifyFree(current, scan('B'), 6), null);
  assert.equal(JSON.stringify(current.tracker), '{"last":null,"pending":null,"reference":null}');  // Fresh baseline: no jump counted.
  // The next readings start that baseline: the first waits, the second is a baseline with no gain.
  const {accepted} = run([r(10, 35, 100), r(11, 35, 120)], current.tracker);
  assert.deepEqual(accepted.map((a) => [a.kind, a.gain]), [['baseline', null], ['gain', 20]]);
});

test('a percentage-only HUD reads its percentage; a dot before "[" is not a number', async () => {
  const R = await import(new URL('reader.js', web));
  const read = async (digit, percents = null) => {
    const width = 100, height = 24, frame = {width, height, data: new Uint8ClampedArray(width * height * 4)};
    const paint = (x, y, rgb) => frame.data.set([...rgb, 255], (y * width + x) * 4);
    for (const x of [30, 80]) for (let y = 5; y < 15; y++) paint(x, y, [160, 185, 130]);
    for (let y = 7; y < 14; y++) for (const x of [40, 41, 50, 51, 60, 61]) paint(x, y, [255, 255, 255]);
    for (let y = 5; y < 7; y++) paint(8, y, [255, 255, 255]);  // The EXP label, above the digit band.
    for (let y = 12; y < 14; y++) for (const x of [10, 11]) paint(x, y, [255, 255, 255]);  // Its dot.
    for (let y = 6; y < 15; y++) paint(29, y, [140, 140, 140]);  // A dim bracket outline touching "[".
    if (digit) for (let y = 7; y < 14; y++) paint(20, y, digit === 'dim' ? [140, 140, 140] : [255, 255, 255]);
    const engine = {read: async (_, field) => ({text: field.startsWith('percent') ? (percents ? percents.shift() : '78.63%') : field.startsWith('number') ? '1' : ''})};
    return R.readHud(engine, frame, {exp: {x0: 0, y0: 0, x1: 98, y1: 21}}, null, {table, previousLevel: 71});
  };
  const only = await read(false);
  assert.equal(only.percentOnly, true); assert.equal(only.bp, 7863); assert.equal(only.exp, null);
  // Without a level badge there is no EXP to estimate: never a reading.
  assert.equal(only.status, 'unreadable'); assert.equal(only.reason, 'level_unreadable');
  assert.equal((await read(true)).percentOnly, undefined);  // A full-height glyph is a number: the usual path.
  assert.equal((await read('dim')).percentOnly, undefined);  // Safari blurs a lone 7's stroke to 110-170.
  // Crisp pass, then smooth: a smooth agreement that contradicts a valid crisp read is refused (a 7 read as 2).
  assert.equal((await read(false, ['79.88%', '79.883', '29.88%', '29.88%'])).bp, null);
  assert.equal((await read(false, ['.19%', '.19%', '26.19%', '26.19%'])).bp, 2619);  // Nothing valid to contradict.
});

test('long gaps and level jumps start baselines; different characters pause for the user', () => {
  const gap = run([r(0, 20, 5000), r(20, 20, 5100), r(500, 20, 6000), r(520, 20, 6050)]);
  assert.deepEqual(gap.accepted.map((a) => a.gain), [null, 100, null, 50]);
  // Another character's readings must agree on SUSPECT_SCANS scans before tracking pauses; fewer are skipped.
  const other = run([r(0, 20, 5000), r(20, 20, 5100), r(40, 35, 100), r(60, 35, 200), r(80, 35, 300), r(100, 35, 400), r(120, 35, 500)]);
  assert.deepEqual(other.out.slice(2).map((o) => o.status), ['pending', 'pending', 'pending', 'pending', 'identity_check']);
  assert.equal(other.state.last.level, 20);  // The accepted state is preserved.
  // A new session keeps the previous reading only as a reference for this check.
  const fresh = run([1000, 1020, 1040, 1060, 1080].map((t, i) => r(t, 35, 100 + i * 100)), {last: null, pending: null, reference: r(0, 20, 5000)});
  assert.equal(fresh.out.at(-1).status, 'identity_check');
  assert.deepEqual(E.acceptBaseline(fresh.out.at(-1).suspect).accept[0].kind, 'baseline');
});

test('rates use observed time only and need coverage; gaps are not zeros', async () => {
  const readings = [];
  for (let s = 0; s <= 600; s += 20) readings.push({...r(s, 20, 5000 + s), sessionId: 1, gain: s ? 20 : null});
  const list = E.intervals(readings);
  const five = E.windowStats(list, at(600), 300);
  assert.equal(five.ok, true);
  assert.equal(Math.round(five.perHour), 3600);
  assert.equal(E.windowStats(list, at(600), 3600).ok, false);
  // Readings in another session never form an interval with this one.
  assert.equal(E.intervals([{...readings[0], sessionId: 1}, {...readings[1], sessionId: 2}]).length, 0);
  const C = await import(new URL('charts.js', web));
  const chart = C.bucketHistory(list, at(600), 300, 3600);  // 5-minute bars over the last hour.
  assert.ok(chart.bins.some((b) => b.state === 'missing' && b.value === null));  // Unobserved time is missing, not zero.
  assert.equal(Math.round(chart.bins.reduce((sum, b) => sum + (b.value ?? 0), 0)), 600);  // Every gain is drawn exactly once.
  // "So far" rates describe only a running session.
  const character = {last: readings.at(-1), totalGain: 600};
  assert.equal(V.summarize(table, character, readings, at(600), 30, {live: false}).perHour, null);
  assert.equal(Math.round(V.summarize(table, character, readings, at(600), 30, {live: true}).perHour), 3600);
});

test('the local Level % chart keeps the full hour trace with fewer inspection targets', async () => {
  const {drawPercentChart} = await import(new URL('charts.js', web));
  const element = (tag) => ({tag, attrs: {}, dataset: {}, children: [],
    setAttribute(key, value) { this.attrs[key] = value; },
    append(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
    addEventListener() {},
  });
  const svg = Object.assign(element('svg'), {clientWidth: 960});
  const priorDocument = globalThis.document;
  globalThis.document = {createElementNS: (_, tag) => element(tag)};
  try {
    const points = Array.from({length: 3601}, (_, i) => ({
      ...r(i, i < 3005 ? 20 : 21, i < 3005 ? 5000 + i : i - 3005),
      gain: i === 0 || i === 3203 ? null : 1, sessionId: i < 3307 ? 1 : 2,
    }));
    const targets = () => svg.children.filter((node) => node.attrs.class === 'point-hit');
    drawPercentChart(svg, points, {anchor: at(3600), minutes: 60});
    const path = svg.children.find((node) => node.tag === 'path');
    assert.equal(path.attrs.d.match(/M/g).length, 3);
    assert.equal(path.attrs.d.match(/L/g).length, 3598);
    assert.ok(targets().length < 200);
    const keys = new Set(targets().map((node) => node.dataset.tipKey));
    for (const i of [0, 3004, 3005, 3202, 3203, 3306, 3307, 3600]) assert.ok(keys.has(`point:${at(i)}`));
    assert.ok(svg.children.some((node) => node.attrs.class === 'level-transition-label' && node.textContent === 'Level 21!'));

    drawPercentChart(svg, points.filter((_, i) => i % 20 === 0), {anchor: at(3600), minutes: 60});
    assert.equal(targets().length, 181);
  } finally {
    globalThis.document = priorDocument;
  }
});

test('HUD geometry: labels bind to one status bar; brackets are found by colour', () => {
  const frame = {width: 1368, height: 800};
  const w = (text, x0, y0, x1, y1) => ({text, x0, y0, x1, y1});
  const words = [w('HP(223', 504, 769, 542, 778), w('MP!', 613, 769, 634, 778), w('EXP', 725, 769, 747, 778),
    w('5.477127.09%1', 750, 771, 824, 778), w('LV.', 297, 775, 315, 788)];
  const found = H.locate(words, frame);
  assert.equal(Math.round(found.exp.x0), 723);  // The label stays in the box; each scan trims it in pixels.
  // Only the first digits read ("z17" of "217 [12.65%]"): the box still spans the bar, past the percentage.
  const short = H.locate([...words.filter((t) => t.text[0] !== '5'), w('z17', 750, 771, 767, 778)], frame);
  assert.ok(short.exp.x1 >= 840, `box ends at ${short.exp.x1}`);
  // No digits read at all: HP and MP still place the bar; without them, no guess.
  const bare = words.filter((t) => t.text[0] !== '5');
  assert.ok(H.locate(bare, frame).exp.x1 >= 840);
  assert.equal(H.locate(bare.filter((t) => !t.text.startsWith('MP')), frame).reason, 'exp_digits_not_found');
  assert.equal(found.level.x0, 297);
  assert.ok(H.locate(words.filter((t) => t.text !== 'LV.'), frame).level.x1 < 504);  // Orange-tile search left of HP.
  // LV. and a leading digit can be one sparse OCR word; colour must still find both tiles.
  const badgeFrame = {...frame, data: new Uint8ClampedArray(frame.width * frame.height * 4)};
  for (let y = 775; y < 788; y++) for (let x = 329; x < 352; x++) {
    if (x !== 340) badgeFrame.data.set([240, 130, 30, 255], (y * frame.width + x) * 4);
  }
  for (const x of [333, 345]) badgeFrame.data.set([255, 255, 255, 255], (780 * frame.width + x) * 4);
  for (const x of [334, 346]) badgeFrame.data.set([255, 255, 255, 255], (781 * frame.width + x) * 4);
  for (const [text, right] of [['LV.', 315], ['LV.2', 340], ['LV.23', 352]]) {
    const labels = [...words.slice(0, -1), w(text, 297, 775, right, 788)];
    for (const options of [{safari: true}, {safari: false}]) {
      const located = H.locate(labels, frame, options);
      assert.deepEqual(H.orangeBox(badgeFrame, located.level), {x0: 329, y0: 775, x1: 352, y1: 788});
    }
    assert.equal(H.locate(labels, frame).level.x0, 297);  // Chrome also keeps merged leading digits.
  }
  assert.equal(H.locate(words.filter((t) => t.text !== 'EXP'), frame).reason, 'exp_label_not_found');
  assert.equal(H.locate([...words, ...words.map((t) => ({...t, y0: t.y0 - 300, y1: t.y1 - 300}))], frame).reason, 'multiple_huds');
  // A synthetic strip: white digits on grey with two olive brackets.
  const width = 40, height = 10, data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) data.set([90, 90, 90, 255], i * 4);
  for (const x of [12, 30]) for (let y = 2; y < 9; y++) data.set([160, 185, 130, 255], (y * width + x) * 4);
  assert.deepEqual(H.brackets({width, height, data}, {x0: 0, y0: 0, x1: width, y1: height}), [{x0: 12, x1: 13}, {x0: 30, x1: 31}]);
  // A high EXP gauge underneath adds green rows across the box; they are not brackets.
  const tall = {width, height: height + 3, data: new Uint8ClampedArray(width * (height + 3) * 4)};
  tall.data.set(data);
  for (const y of [10, 11, 12]) for (let x = 0; x < 34; x++) tall.data.set([190, 250, 60, 255], (y * width + x) * 4);
  assert.deepEqual(H.brackets(tall, {x0: 0, y0: 0, x1: width, y1: height + 3}), [{x0: 12, x1: 13}, {x0: 30, x1: 31}]);
  for (let y = 2; y < 9; y++) data.set([90, 90, 90, 255], (y * width + 30) * 4);
  assert.equal(H.brackets({width, height, data}, {x0: 0, y0: 0, x1: width, y1: height}), null);  // Clipped field.
});

test('glyph templates: learned only from aligned confirmed text; conflicts are poisoned', async () => {
  const G = await import(new URL('glyphs.js', web));
  // Three synthetic 3x5 "glyphs" separated by blank columns (not game font data).
  const shapes = ['111/101/101/101/111', '010/110/010/010/111', '111/001/111/100/111'];
  const width = 3 * 4 + 1, height = 7, data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) data.set([60, 60, 60, 255], i * 4);
  shapes.forEach((shape, g) => shape.split('/').forEach((row, y) => [...row].forEach((bit, x) => {
    if (bit === '1') data.set([255, 255, 255, 255], ((y + 1) * width + 1 + g * 4 + x) * 4);
  })));
  const seg = G.segment({width, height, data}, {x0: 0, y0: 0, x1: width, y1: height});
  assert.equal(seg.glyphs.length, 3);
  const templates = {};
  assert.equal(G.read(seg, templates), null);
  assert.equal(G.learn(templates, seg, '0123'), null);  // Glyph and character counts differ: nothing learned.
  assert.equal(G.learn(templates, seg, '012'), 3);
  assert.equal(G.read(seg, templates), '012');
  G.learn(templates, seg, '812');  // The same bitmap later confirmed as another character.
  assert.equal(G.read(seg, templates), null);
  assert.deepEqual(G.displayed(1234567, 905), {number: '1,234,567', percent: '9.05%'});
});

test('a backup is checked before it can replace anything', async () => {
  const S = await import(new URL('store.js', web));
  const good = {format: 'msxp-local-v3', exportedAt: '2026-11-11T20:00:00.000Z',
    characters: [{id: 1, name: 'CharA', totalGain: 10}], sessions: [{id: 1, characterId: 1, startedAt: 5}],
    readings: [{id: 1, characterId: 1, sessionId: 1, at: 10, level: 21, exp: 100, bp: 50, gain: null}],
    days: [{characterId: 1, day: '2026-11-11', gain: 0, at: 10, level: 21, exp: 100, bp: 50}],
    pickups: [{id: 1, characterId: 1, at: 11, kind: 'item', itemId: 4000019, name: 'Snail Shell', count: 1}]};
  const backup = S.checkBackup(good);
  assert.equal(backup.characters.length, 1);
  assert.equal(S.checkBackup({format: 'msxp-local-v2', characters: []}).pickups.length, 0);  // Older backups have no pickups.
  assert.throws(() => S.checkBackup({format: 'something else'}), /isn't an msxp/);
  assert.throws(() => S.checkBackup({...good, readings: {}}), /aren't a list/);
  assert.throws(() => S.checkBackup({...good, readings: [{...good.readings[0], characterId: 2}]}), /a reading/);  // Another character's.
  assert.throws(() => S.checkBackup({...good, characters: [...good.characters, {id: 1, name: 'Twin'}]}), /a character/);  // Same id twice.
  assert.throws(() => S.checkBackup({...good, pickups: [{...good.pickups[0], name: 'x'.repeat(500)}]}), /a pickup/);
});

test('daily summaries keep the last reading of each local day and add up its gains', async () => {
  const S = await import(new URL('store.js', web));
  const morning = new Date(2026, 10, 10, 8).getTime(), evening = new Date(2026, 10, 10, 21).getTime();
  let day = S.foldDay(undefined, {characterId: 1, at: evening, level: 21, exp: 50, bp: 20, gain: 300});
  day = S.foldDay(day, {characterId: 1, at: morning, level: 20, exp: 900, bp: 4000, gain: 100});  // An older reading arrives later.
  assert.deepEqual(day, {characterId: 1, day: '2026-11-10', gain: 400, at: evening, level: 21, exp: 50, bp: 20});
  assert.equal(S.dayOf(new Date(2026, 0, 2, 23, 59).getTime()), '2026-01-02');
  assert.ok(S.DETAIL_MS > 24 * 3600e3 && S.DETAIL_MS <= 25 * 3600e3);
});

test('text reader lock: EXP scans wait for a pickup read, pickup reads give way, scans never queue', async () => {
  const {readerLock} = await import(new URL('lock.js', web));
  const exclusive = readerLock(), order = [];
  let finish;
  const pickup = exclusive(() => new Promise((resolve) => { finish = () => { order.push('pickup'); resolve('p'); }; }), {background: true});
  const scan = exclusive(async () => { order.push('scan'); return 's'; });  // Waits instead of skipping.
  assert.equal(await exclusive(async () => 'x', {background: true}), null);  // A scan is waiting: give way.
  assert.equal(await exclusive(async () => 'y'), null);  // A second scan never queues.
  finish();
  assert.deepEqual([await pickup, await scan], ['p', 's']);
  assert.deepEqual(order, ['pickup', 'scan']);
  let release;
  const running = exclusive(() => new Promise((resolve) => { release = resolve; }));
  assert.equal(await exclusive(async () => 'z'), null);  // A scan still running makes the next tick skip.
  release('done');
  assert.equal(await running, 'done');
  assert.equal(await exclusive(async () => 'free', {background: true}), 'free');
});

test('pickups: 24h mesos and items', () => {
  const now = at(100000), row = (s, extra) => ({at: now - s * 1000, ...extra});
  const rows = [row(90000, {kind: 'mesos', amount: 999}),  // Older than a day.
    row(4000, {kind: 'mesos', amount: 100}), row(500, {kind: 'mesos', amount: 30}), row(100, {kind: 'mesos', amount: 20}),
    row(400, {kind: 'item', itemId: 1, name: 'Tree Branch', count: 1}), row(50, {kind: 'item', itemId: 1, name: 'Tree Branch', count: 2}),
    row(60, {kind: 'item', itemId: 2, name: 'Arrows for Bows', count: 1})];
  const off = V.summarizePickups(rows, now);
  assert.equal(off.mesosDay, 150);
  assert.deepEqual(off.items.map((i) => [i.name, i.count]), [['Tree Branch', 3], ['Arrows for Bows', 1]]);
  // Items over a shorter window (mesos stay the day's): the branch from 400 s ago is left out of 5 min.
  const recent = V.summarizePickups(rows, now, 5);
  assert.equal(recent.mesosDay, 150);
  assert.deepEqual(recent.items.map((i) => [i.name, i.count]), [['Tree Branch', 2], ['Arrows for Bows', 1]]);
});

test('tracked data in a time range: EXP gains, mesos and items, for removing it', () => {
  const t = (s) => at(s);
  const readings = [{at: t(0), gain: null}, {at: t(20), gain: 30}, {at: t(40), gain: 0}, {at: t(60), gain: 50}, {at: t(80), gain: 70}];
  const pickups = [{at: t(30), kind: 'mesos', amount: 12}, {at: t(50), kind: 'item', itemId: 1, name: 'Iron Ore', count: 1},
    {at: t(55), kind: 'item', itemId: 1, name: 'Iron Ore', count: 2}, {at: t(90), kind: 'mesos', amount: 99}];
  const range = V.trackedBetween(readings, pickups, t(20), t(60));
  assert.deepEqual([range.exp, range.expReadings, range.mesos, range.mesoPickups], [80, 3, 12, 1]);
  assert.deepEqual(range.items.map((i) => [i.name, i.count]), [['Iron Ore', 3]]);
  const empty = V.trackedBetween(readings, pickups, t(81), t(85));
  assert.deepEqual([empty.expReadings, empty.mesoPickups, empty.items.length], [0, 0, 0]);
  // Older days keep only a summary: they count when the range covers the whole local day.
  const days = [{day: '2026-03-01', gain: 400}, {day: '2026-03-02', gain: 500}, {day: '2026-03-04', gain: 900}];
  const local = (text) => new Date(text).getTime(), detail = local('2026-03-04T00:00');
  const old = V.trackedBetween([], [], local('2026-03-01T12:00'), local('2026-03-05T00:00'), days, detail);
  assert.deepEqual([old.oldDays.map((d) => d.day), old.exp], [['2026-03-02'], 500]);  // Not the half of the 1st, nor the 4th (detail).
});

test('live rate: trailing-window rate per second, early estimate, quiet time slopes down', async () => {
  const L = await import(new URL('live-chart.js', web));
  const s = (n) => n * 1000, since = 0, window = s(300);
  const events = [{at: s(10), amount: 100}, {at: s(20), amount: 100}, {at: s(70), amount: 100}];
  assert.deepEqual(L.rateSeries(events.slice(0, 2), {from: 0, to: s(400), window, since}), []);  // Fewer than 3 gains: nothing yet.
  const series = L.rateSeries(events, {from: 0, to: s(400), window, since});
  const at = (sec) => Math.round(series.find((p) => p.at === s(sec)).perHour * 1000) / 1000, near = (v) => Math.round(v * 1000) / 1000;
  assert.equal(series[0].at, s(70));  // Starts at the third gain.
  assert.equal(at(70), near(300 / 70 * 3600));  // Early: over the 70 s tracked so far.
  assert.equal(at(300), near(300 / 300 * 3600));  // Full window.
  assert.equal(at(312), near(200 / 300 * 3600));  // The first gain left the window; nothing new: the rate falls.
  assert.equal(at(400), 0);
  assert.equal(L.rateSeries([{at: s(1), amount: 50}, {at: s(2), amount: 50}, {at: s(3), amount: 50}], {from: 0, to: s(3), window, since})[0].perHour, 150 / 60 * 3600);  // At least a minute.
  const eased = L.smooth([{at: 0, perHour: 0}, {at: 1, perHour: 600}, {at: 2, perHour: 600}]).map((p) => p.perHour);
  assert.ok(eased[1] > 0 && eased[1] < eased[2] && eased[2] < 600);  // A jump becomes a curve.
});

test('EXP reading: the EXP table picks the reading that fits the level, else variants must agree', async () => {
  const R = await import(new URL('reader.js', web));
  const total = E.requirement(table, 21), exp = Math.round(total * .3015), shown = exp.toLocaleString('en-US');
  const percent = `${(Math.floor(exp * 10000 / total) / 100).toFixed(2)}%`, fits = (e, bp) => E.consistency(table, 21, e, bp) === 'consistent';
  // A stretched HUD (measured): the percentage once lost its first digit; the other pass read 7 as 2.
  assert.deepEqual(R.pickExp([shown, shown], [percent, percent.slice(1)]), {reason: 'exp_variants_disagree'});
  assert.equal(R.pickExp([shown, shown], [percent, percent.slice(1)], fits).value.exp, exp);
  const misread = `2${shown.slice(1)}`;
  assert.deepEqual(R.pickExp([misread, misread], [percent, percent], fits), {reason: 'exp_disagrees_with_table'});
  assert.equal(R.pickExp([misread, misread], [percent, percent]).value.exp, Number(misread.replace(/,/g, '')));  // Without a level: agreement only.
  assert.deepEqual(R.pickExp(['4000', '4001'], ['30.15%', '30.15%'], () => true), {reason: 'exp_variants_disagree'});
});

test('EXP can combine observed candidates across passes only with a unique table match', async () => {
  const R = await import(new URL('reader.js', web));
  const frame = {width: 100, height: 20, data: new Uint8ClampedArray(100 * 20 * 4)};
  for (const x of [35, 90]) for (let y = 4; y < 12; y++) frame.data.set([160, 185, 130, 255], (y * 100 + x) * 4);
  const exp = Math.round(E.requirement(table, 21) * .3015), bp = Math.floor(exp * 10000 / E.requirement(table, 21));
  const shown = exp.toLocaleString('en-US'), percent = `${(bp / 100).toFixed(2)}%`;
  const run = async (options) => {
    const texts = {number: [shown, shown, `2${shown.slice(1)}`, `2${shown.slice(1)}`], percent: ['3015%', '3015%', percent, percent]};
    return R.readHud({read: async (_, field) => ({text: texts[field].shift()})}, frame,
      {exp: {x0: 0, y0: 2, x1: 98, y1: 15}}, null, options);
  };
  const matched = await run({table, previousLevel: 21});
  assert.equal(matched.status, 'ok'); assert.equal(matched.exp, exp); assert.equal(matched.bp, bp);
  // Without level evidence, the earlier number is never combined with the later percentage.
  const unguarded = await run({});
  assert.notEqual(unguarded.exp, exp);
});

test('Safari EXP word fallback recovers a dropped leading digit and retains validation', async () => {
  const R = await import(new URL('reader.js', web));
  const frame = {width: 100, height: 20, data: new Uint8ClampedArray(100 * 20 * 4)};
  for (const x of [35, 90]) for (let y = 4; y < 12; y++) frame.data.set([160, 185, 130, 255], (y * 100 + x) * 4);
  const exp = Math.round(E.requirement(table, 21) * .3015), percent = `${(Math.floor(exp * 10000 / E.requirement(table, 21)) / 100).toFixed(2)}%`;
  const run = (options, wordPercent) => R.readHud({read: async (_, field) => ({text:
    field.startsWith('number') ? String(exp) : field === 'percentWord' ? wordPercent : '3015%'})}, frame,
  {exp: {x0: 0, y0: 2, x1: 98, y1: 15}}, null, options);
  const matched = await run({table, previousLevel: 21, safari: true}, percent);
  assert.equal(matched.status, 'ok'); assert.equal(matched.exp, exp);
  assert.ok(matched.raw.exp.some((r) => r.word && r.field === 'percent'));
  assert.equal((await run({table, previousLevel: 21, safari: true}, '1.00%')).status, 'ambiguous');
  assert.equal((await run({safari: true}, percent)).status, 'ok');  // Both word variants agree without level evidence.
  // Other browsers skip the extra pass (4 OCR calls on every failing scan).
  const other = await run({table, previousLevel: 21}, percent);
  assert.notEqual(other.status, 'ok'); assert.ok(!other.raw.exp.some((r) => r.word));
});

test('Safari: failed EXP OCR can exclude a short label fragment and retry smaller images', async () => {
  const R = await import(new URL('reader.js', web));
  const exp = Math.round(E.requirement(table, 21) * .3015), bp = Math.floor(exp * 10000 / E.requirement(table, 21));
  const run = async ({tall = false, accepted = false, level = true, hasLabel = true} = {}) => {
    const width = 100, height = 24, frame = {width, height, data: new Uint8ClampedArray(width * height * 4)};
    const paint = (x, y, rgb) => frame.data.set([...rgb, 255], (y * width + x) * 4);
    for (const x of [60, 90]) for (let y = 5; y < 15; y++) paint(x, y, [160, 185, 130]);
    for (let y = 7; y < 14; y++) for (const x of [14, 15, 16, 70, 71, 72]) paint(x, y, [255, 255, 255]);
    if (hasLabel) for (let y = 5; y < 7; y++) paint(8, y, [255, 255, 255]);  // Label ends at x8 above the digit band.
    for (let y = 7; y < (tall ? 14 : 9); y++) paint(hasLabel ? 9 : 0, y, [255, 255, 255]);
    let numbers = 0;
    const engine = {read: async (_, field) => ({text: field === 'number' ? (++numbers > 4 || accepted ? String(exp) : '')
      : field === 'numberWord' ? '' : `${(bp / 100).toFixed(2)}%`})};
    return {result: await R.readHud(engine, frame, {exp: {x0: 0, y0: 0, x1: 98, y1: 21}}, null,
      level ? {table, previousLevel: 21, safari: true} : {safari: true}), numbers};
  };
  for (const level of [false, true]) {
    const {result, numbers} = await run({level});
    assert.equal(result.status, 'ok'); assert.equal(result.exp, exp); assert.equal(result.bp, bp);
    assert.equal(numbers, 6);
    assert.deepEqual(result.raw.exp.filter((r) => r.field === 'number').slice(-2).map((r) => r.scale), [3, 4]);
  }
  // A full-height leading digit must never be removed (Safari's later threshold pass may still read it).
  const trimmed = ({result}) => result.raw.exp.some((r) => r.field === 'number' && r.scale === 3);
  const tall = await run({tall: true});
  assert.ok(!trimmed(tall));
  const accepted = await run({accepted: true});
  assert.equal(accepted.result.status, 'ok'); assert.equal(accepted.numbers, 2);
  assert.ok(!trimmed(await run({hasLabel: false})));
});

test('Safari re-segments past an EXP label fragment before falling back from exact glyphs', async () => {
  const R = await import(new URL('reader.js', web)), G = await import(new URL('glyphs.js', web));
  const frame = {width: 128, height: 24, data: new Uint8ClampedArray(128 * 24 * 4)};
  const paint = (x, y, rgb) => frame.data.set([...rgb, 255], (y * frame.width + x) * 4);
  for (const x of [60, 120]) for (let y = 5; y < 15; y++) paint(x, y, [160, 185, 130]);
  const stamp = (left, char) => Object.entries(G.HUD_GLYPHS).find(([, c]) => c === char)[0].split('/').forEach((row, y) => {
    [...row].forEach((bit, x) => { if (bit === '1') paint(left + x, y + 7, [255, 255, 255]); });
  });
  stamp(14, '2');
  [...'13.33%'].forEach((char, i) => stamp([64, 68, 75, 78, 85, 92][i], char));
  for (const y of [5, 6]) paint(8, y, [255, 255, 255]);
  for (const y of [7, 8]) paint(9, y, [255, 255, 255]);
  const regions = {exp: {x0: 0, y0: 0, x1: 128, y1: 21}};
  const run = async (safari, templates = G.HUD_GLYPHS, glyphText = '') => {
    let calls = 0;
    const result = await R.readHud({read: async (_, field) => { calls++; return {text: field === 'percentGlyph' ? glyphText : ''}; }},
      frame, regions, templates, {safari});
    return {result, calls};
  };
  const {result, calls} = await run(true);
  assert.deepEqual([result.status, result.exp, result.bp, result.source, calls], ['ok', 2, 1333, 'glyphs', 0]);
  assert.equal(result.segments.number.glyphs.length, 1);
  assert.equal(E.consistency(table, 1, result.exp, result.bp), 'consistent');
  const other = await run(false);
  assert.notEqual(other.result.status, 'ok'); assert.ok(other.calls > 0);
  const unknown = await run(true, {});
  assert.notEqual(unknown.result.status, 'ok'); assert.ok(unknown.calls > 0);
  const partial = await run(true, Object.fromEntries(Object.entries(G.HUD_GLYPHS).filter(([, char]) => char !== '3')), '3');
  assert.deepEqual([partial.result.status, partial.result.exp, partial.result.bp, partial.result.source, partial.calls],
    ['ok', 2, 1333, 'ocr', 6]);
  // A softened digit pass may read no badge at all; Safari can try the crisp badge without dropping EXP.
  for (let y = 16; y < 23; y++) for (let x = 100; x < 110; x++) paint(x, y, [240, 130, 30]);
  for (let y = 17; y < 23; y++) paint(105, y, [255, 255, 255]);
  paint(103, 18, [255, 255, 255]); paint(104, 19, [255, 255, 255]);
  let badgeCalls = 0;
  const badge = await R.readHud({read: async () => ({text: ++badgeCalls > 4 ? '1' : ''})}, frame,
    {...regions, level: {x0: 99, y0: 15, x1: 111, y1: 24}}, G.HUD_GLYPHS, {safari: true});
  assert.equal(badge.status, 'ok'); assert.equal(badge.level, 1); assert.equal(badgeCalls, 6);
  assert.deepEqual(badge.raw.level.map((r) => r.smooth), [true, true, true, true, false, false]);
});

test('Safari font cells read every digit pair with different local thresholds and reject ambiguity', async () => {
  const G = await import(new URL('glyphs.js', web));
  const shapes = Object.entries(G.HUD_GLYPHS).slice(0, 13);
  const render = (text) => {
    const width = 2 + [...text].reduce((sum, c) => sum + (c === ',' ? 5 : 6), 0);
    const frame = {width, height: 7, data: new Uint8ClampedArray(width * 7 * 4)};
    let left = 1;
    for (const [n, char] of [...text].entries()) {
      const rows = shapes.find(([, c]) => c === char)[0].split('/'), offset = ['1', ','].includes(char) ? 1 : 0;
      const advance = char === ',' ? 5 : 6;
      for (let y = 0; y < 7; y++) for (let x = 0; x < advance - 1; x++) {
        const value = rows[y][x - offset] === '1' ? (n % 2 ? 220 : 150) : (n % 2 ? 155 : 80);
        frame.data.set([value, value, value, 255], (y * width + left + x) * 4);
      }
      left += advance;
    }
    return {frame, box: {x0: 1, x1: width, y0: 0, y1: 7}, band: {top: 0, bottom: 6}};
  };
  const read = ({frame, box, band}, templates = G.HUD_GLYPHS) => G.readSoftField(frame, box, band, 'number', templates);
  for (let n = 10; n < 100; n++) {
    const sample = render(String(n));
    assert.equal(read(sample)?.text, String(n));
    assert.equal(G.read(G.segment(sample.frame, sample.box), G.HUD_GLYPHS), null);
  }
  assert.equal(read(render('1,234'))?.text, '1,234');
  assert.equal(read(render('12,34')), null);
  assert.equal(read(render('12'), {}), null);
  const sample = render('8'), eight = shapes.find(([, c]) => c === '8')[0].split('/');
  const three = shapes.find(([, c]) => c === '3')[0].split('/');
  // This faint stroke permits both 3 and 8 at different thresholds: neither may be chosen.
  for (let y = 0; y < 7; y++) for (let x = 0; x < 5; x++) {
    const value = eight[y][x] === three[y][x] ? (eight[y][x] === '1' ? 220 : 80) : 170;
    sample.frame.data.set([value, value, value, 255], (y * sample.frame.width + x + 1) * 4);
  }
  assert.equal(read(sample)?.ambiguous, true);
  assert.equal(read({...sample, band: {top: 0, bottom: 5}}), null);
  assert.equal(read({...sample, box: {...sample.box, x0: -1}}), null);
});

test('Safari can separate blurred number glyphs without choosing between conflicting OCR candidates', async () => {
  const R = await import(new URL('reader.js', web)), G = await import(new URL('glyphs.js', web));
  const frame = {width: 128, height: 24, data: new Uint8ClampedArray(128 * 24 * 4)};
  const paint = (x, y, rgb) => frame.data.set([...rgb, 255], (y * frame.width + x) * 4);
  for (const x of [60, 120]) for (let y = 5; y < 15; y++) paint(x, y, [160, 185, 130]);
  const stamp = (left, char) => Object.entries(G.HUD_GLYPHS).find(([, c]) => c === char)[0].split('/').forEach((row, y) => {
    [...row].forEach((bit, x) => { if (bit === '1') paint(left + x, y + 7, [255, 255, 255]); });
  });
  stamp(47, '6'); stamp(53, '6');
  paint(52, 8, [153, 153, 153]);  // A dim bridge joins both digit components in the adaptive mask.
  [...'4.40%'].forEach((char, i) => stamp([64, 71, 74, 81, 88][i], char));
  const regions = {exp: {x0: 47, y0: 0, x1: 128, y1: 21}}, boxes = R.fieldBoxes(frame, regions), box = boxes.number;
  assert.equal(G.read(G.segment(frame, box), G.HUD_GLYPHS), null);
  assert.equal(G.readSoftField(frame, box, boxes.band, 'number', G.HUD_GLYPHS)?.text, '66');
  const run = async (safari, templates = G.HUD_GLYPHS) => {
    let calls = 0;
    const result = await R.readHud({read: async () => { calls++; return {text: ''}; }}, frame, regions, templates, {safari});
    return {result, calls};
  };
  const {result, calls} = await run(true);
  assert.deepEqual([result.status, result.exp, result.bp, result.source, calls], ['ok', 66, 440, 'glyphs', 0]);
  assert.equal(E.consistency({to_next: {'10': 1500}}, 10, result.exp, result.bp), 'consistent');
  const other = await run(false);
  assert.notEqual(other.result.status, 'ok'); assert.ok(other.calls > 0);
  const unknown = await run(true, {});
  assert.notEqual(unknown.result.status, 'ok'); assert.ok(unknown.calls > 0);
  const six = Object.keys(G.HUD_GLYPHS).find((key) => G.HUD_GLYPHS[key] === '6');
  assert.notEqual((await run(true, {...G.HUD_GLYPHS, [six]: '?'})).result.status, 'ok');
  const noPercent = Object.fromEntries(Object.entries(G.HUD_GLYPHS).filter(([, char]) => char !== '%'));
  let numberCalls = 0;
  const partial = await R.readHud({read: async (_, field) => {
    if (field.startsWith('number')) numberCalls++;
    return {text: field === 'percent' ? '4.40%' : field.startsWith('number') ? '68' : ''};
  }}, frame, regions, noPercent, {safari: true, table: {to_next: {'10': 1500}}, previousLevel: 10});
  assert.deepEqual([partial.status, partial.exp, partial.bp, partial.source, numberCalls], ['ok', 66, 440, 'ocr', 0]);
  assert.ok(partial.raw.exp.some((r) => r.field === 'number' && r.glyphs && r.text === '66'));
  // Rounded and truncated percentages can both fit; OCR must not replace an already verified field.
  const noSix = Object.fromEntries(Object.entries(G.HUD_GLYPHS).filter(([, char]) => char !== '6'));
  for (const previousLevel of [null, 10]) {
    let percentCalls = 0;
    const retained = await R.readHud({read: async (_, field) => {
      if (field.startsWith('percent')) percentCalls++;
      return {text: field.startsWith('number') ? '66' : '4.39%'};
    }}, frame, regions, noSix, {safari: true, table: {to_next: {'10': 1501}}, previousLevel});
    assert.deepEqual([retained.status, retained.exp, retained.bp, percentCalls], ['ok', 66, 440, 0]);
    assert.ok(retained.raw.exp.some((r) => r.field === 'percent' && r.glyphs && r.text === '4.40%'));
  }
  let variants = 0;
  const conflicting = await R.readHud({read: async (_, field) => ({text: field.startsWith('number') ? (++variants % 2 ? '4400' : '4401') : ''})},
    frame, regions, noSix, {safari: true, table: {to_next: {'10': 100000}}, previousLevel: 10});
  assert.equal(conflicting.status, 'ambiguous'); assert.equal(conflicting.reason, 'exp_variants_disagree');
});

test('Safari can retain known percentage glyphs and require agreement on each unknown', async () => {
  const R = await import(new URL('reader.js', web)), G = await import(new URL('glyphs.js', web));
  const frame = {width: 120, height: 24, data: new Uint8ClampedArray(120 * 24 * 4)};
  const paint = (x, y, rgb) => frame.data.set([...rgb, 255], (y * frame.width + x) * 4);
  for (const x of [40, 110]) for (let y = 4; y < 15; y++) paint(x, y, [160, 185, 130]);
  const shapes = ['01110/10001/00001/00010/00100/01100/11111', '0/0/0/0/0/0/1',
    '11111/00001/00001/00001/00010/00100/00100', '01/11/01/01/01/01/01',
    '0100001/1110010/0100100/0001000/0010010/0100111/1000010'];
  const stamp = (left, shape) => shape.split('/').forEach((row, y) => [...row].forEach((bit, x) => {
    if (bit === '1') paint(left + x, y + 6, [255, 255, 255]);
  }));
  stamp(10, shapes[0]);
  shapes.forEach((shape, i) => stamp([44, 52, 56, 65, 71][i], shape));
  const regions = {exp: {x0: 0, y0: 0, x1: 120, y1: 21}};
  const glyphs = G.segment(frame, R.fieldBoxes(frame, regions).percent).glyphs;
  const known = Object.fromEntries([1, 2, 3].map((i) => [glyphs[i].key, ['2', '.', '7', '1', '%'][i]]));
  const exp = Math.ceil(E.requirement(table, 21) * .0271);
  const run = async ({safari = true, level = true, accepted = false, disagree = false, templates = known,
    texts = ['2', '2', '', '', '%', '%']} = {}) => {
    let glyphCalls = 0, numbers = 0;
    const engine = {read: async (_, field) => ({text: field === 'percentGlyph' ? texts[glyphCalls++] ?? ''
      : field.startsWith('number') ? String(exp + (disagree ? numbers++ % 2 : 0)) : accepted ? '2.71%' : '2.1%'})};
    const result = await R.readHud(engine, frame, regions, templates, {safari, ...(level ? {table, previousLevel: 21} : {})});
    return {result, glyphCalls};
  };
  for (const level of [true, false]) {
    const {result, glyphCalls} = await run({level});
    assert.deepEqual([result.status, result.exp, result.bp], ['ok', exp, 271]);
    assert.equal(glyphCalls, 6);  // Unknown 2 agrees crisply; unknown % needs smoothing.
    assert.ok(result.raw.exp.some((r) => r.glyphs && r.text === '2.71%'));
    assert.notEqual((await run({level, disagree: true})).result.status, 'ok');
  }
  const other = await run({safari: false});
  assert.notEqual(other.result.status, 'ok'); assert.equal(other.glyphCalls, 0);
  const accepted = await run({accepted: true});
  assert.equal(accepted.result.status, 'ok'); assert.equal(accepted.glyphCalls, 0);
  const unlearned = await run({templates: {}});
  assert.notEqual(unlearned.result.status, 'ok'); assert.equal(unlearned.glyphCalls, 0);
  assert.notEqual((await run({texts: ['2', '3', '2', '3']})).result.status, 'ok');
  assert.notEqual((await run({texts: ['3', '3', '', '', '%', '%']})).result.status, 'ok');  // Table mismatch.
  assert.notEqual((await run({templates: {...known, [glyphs[2].key]: '?'}})).result.status, 'ok');
});

test('Safari can separate blurred number strokes with one unique table-consistent pair', async () => {
  const R = await import(new URL('reader.js', web));
  const frame = {width: 100, height: 24, data: new Uint8ClampedArray(100 * 24 * 4)};
  const paint = (x, y, rgb) => frame.data.set([...rgb, 255], (y * frame.width + x) * 4);
  for (const x of [40, 90]) for (let y = 4; y < 15; y++) paint(x, y, [160, 185, 130]);
  for (let y = 6; y < 13; y++) for (const x of [10, 11, 12, 18, 19, 20, 50, 51, 52]) paint(x, y, [255, 255, 255]);
  for (const y of [8, 9]) for (let x = 13; x < 18; x++) paint(x, y, [130, 130, 130]);  // Blur joins two strokes.
  const exp = Math.ceil(E.requirement(table, 21) * .03), bp = Math.floor(exp * 10000 / E.requirement(table, 21));
  assert.equal(E.consistency(table, 21, exp + 1, bp), 'consistent');  // Two valid candidates must be rejected.
  const run = async ({safari = true, level = true, disagree = false, mismatch = false, accepted = false, partial = false} = {}) => {
    let separated = 0;
    const engine = {read: async (bytes, field) => {
      if (!field.startsWith('number')) return {text: `${(bp / 100).toFixed(2)}%`};
      const header = new TextDecoder().decode(bytes.subarray(0, 40)).match(/^P5\n(\d+) (\d+)\n255\n/);
      const width = Number(header[1]), height = Number(header[2]), scale = (width - 16) / 40;
      const column = 8 + Math.floor(15.5 * scale), pixels = bytes.subarray(header[0].length);
      const joined = Array.from({length: height}, (_, y) => pixels[y * width + column]).includes(0);
      if (!joined) separated++;
      if (partial && separated === 1) return {text: String(Math.floor(exp / 10))};  // One magnification drops a digit.
      return {text: accepted || !joined ? String(exp * (mismatch ? 2 : 1) + (disagree ? separated % 2 : 0)) : ''};
    }};
    return {result: await R.readHud(engine, frame, {exp: {x0: 0, y0: 0, x1: 98, y1: 21}}, null,
      {safari, ...(level ? {table, previousLevel: 21} : {})}), separated};
  };
  const fixed = await run();
  assert.deepEqual([fixed.result.status, fixed.result.exp, fixed.result.bp], ['ok', exp, bp]);
  assert.equal(fixed.separated, 2);
  assert.deepEqual(fixed.result.raw.exp.filter((r) => r.field === 'number').slice(-2).map((r) => [r.smooth, r.threshold]),
    [[false, 150], [false, 150]]);
  assert.equal((await run({partial: true})).result.exp, exp);  // Only the complete observed number fits.
  for (const options of [{safari: false}, {level: false}, {disagree: true}, {mismatch: true}]) {
    assert.notEqual((await run(options)).result.status, 'ok');
  }
  const accepted = await run({accepted: true});
  assert.equal(accepted.result.status, 'ok'); assert.equal(accepted.separated, 0);
});

test('pickups: a bilinear-stretched corner is unstretched back to the game pixels', async () => {
  const P = await import(new URL('pickups.js', web));
  // A 60x40 "game" image of 1-pixel strokes and dark shadows, as a 1366-wide screen shows it at (300, 200).
  const gw = 60, gh = 40, game = new Uint8ClampedArray(gw * gh * 4).fill(120);
  for (let y = 5; y < 35; y += 7) for (let x = 3; x < 57; x += 3) { const i = (y * gw + x) * 4; game.fill(240, i, i + 3); game.fill(20, ((y + 1) * gw + x + 1) * 4, ((y + 1) * gw + x + 1) * 4 + 3); }
  // Stretched by 1920/1366 with the measured model, from the window's corner: the crop starts at screen
  // (ox, oy), the game image at game pixel (300, 200).
  const s = 1920 / P.GAME_WIDTH, ox = Math.ceil(300 * s), oy = Math.ceil(200 * s), sw = Math.floor(gw * s) - 2, sh = Math.floor(gh * s) - 2;
  const at = (x, y, c) => game[((Math.min(gh - 1, Math.max(0, y - 200))) * gw + Math.min(gw - 1, Math.max(0, x - 300))) * 4 + c];
  const screen = new Uint8ClampedArray(sw * sh * 4);
  for (let y = 0; y < sh; y++) for (let x = 0; x < sw; x++) {
    const px = (ox + x + .5) / s - .5, py = (oy + y + .5) / s - .5, x0 = Math.floor(px), y0 = Math.floor(py), ax = px - x0, ay = py - y0;
    for (let c = 0; c < 3; c++) screen[(y * sw + x) * 4 + c] = (at(x0, y0, c) * (1 - ax) + at(x0 + 1, y0, c) * ax) * (1 - ay) + (at(x0, y0 + 1, c) * (1 - ax) + at(x0 + 1, y0 + 1, c) * ax) * ay;
    screen[(y * sw + x) * 4 + 3] = 255;
  }
  const back = P.unstretch({width: sw, height: sh, data: screen}, s, s, ox, oy);
  const fx = Math.ceil(ox / s) - 300, fy = Math.ceil(oy / s) - 200;
  let worst = 0;
  for (let y = 2; y < back.height - 2; y++) for (let x = 2; x < back.width - 2; x++) worst = Math.max(worst, Math.abs(back.data[(y * back.width + x) * 4] - game[((y + fy) * gw + x + fx) * 4]));
  assert.ok(worst <= 8, `largest difference ${worst}`);  // The game's pixels within the screen's 8-bit rounding (edges aside).
});

test('a doubled capture with window chrome preserves the native pixel grid', async () => {
  const P = await import(new URL('pickups.js', web));
  const {sx, sy, mode} = P.captureScale(2732, 1592);
  assert.deepEqual({sx, sy, mode}, {sx: 2, sy: 2, mode: 'area'});
  const data = Uint8ClampedArray.from([20, 20, 240, 240, 20, 20, 240, 240].flatMap((v) => [v, v, v, 255]));
  const frame = P.unstretch({width: 4, height: 2, data}, sx, sy, 0, 1588, {}, mode);
  assert.deepEqual([...frame.data], [20, 20, 20, 255, 240, 240, 240, 255]);
  assert.deepEqual(P.captureScale(1368, 800), {sx: 1, sy: 1});
  assert.deepEqual(P.captureScale(1920, 1080), {sx: 1920 / 1366, sy: 1080 / 768});
});

test("the game's sharper 1080p stretch ('area') is undone with its own model", async () => {
  const P = await import(new URL('pickups.js', web));
  // A row of game pixels: dark with 1-pixel white strokes, stretched by 1920/1366 with each screen pixel the
  // average of the game pixels it covers.
  const s = 1920 / P.GAME_WIDTH, gw = 60, game = Array.from({length: gw}, (_, i) => (i % 5 === 2 ? 250 : 40));
  const sw = Math.floor(gw * s), screen = new Uint8ClampedArray(sw * 4);
  for (let j = 0; j < sw; j++) {
    const a = j / s, b = (j + 1) / s, i = Math.floor(a), split = Math.min(b, i + 1);
    const v = (game[i] * (split - a) + (game[Math.min(gw - 1, i + 1)] ?? game[i]) * (b - split)) * s;
    screen.set([v, v, v, 255], j * 4);
  }
  const back = (mode) => P.unstretch({width: sw, height: 1, data: screen}, s, 1, 0, 0, {}, mode);
  const worst = (img) => Math.max(...Array.from({length: img.width - 4}, (_, i) => Math.abs(img.data[(i + 2) * 4] - game[i + 2])));
  assert.ok(worst(back('area')) <= 3, `area model off by ${worst(back('area'))}`);
  assert.ok(worst(back('bilinear')) > worst(back('area')) + 10);  // The default model gets it wrong.
});

test('overlay options use the live URL parameters; unknown values fall back', () => {
  const o = V.overlayOptions('?layout=chart&theme=blue&name=twitch&interval=1800&range=60&background=ABCDEF&bg=green&evil=1');
  assert.deepEqual([o.layout, o.theme, o.name, o.interval, o.range, o.background, o.bg], ['chart', 'blue', 'none', '1800', '1440', 'abcdef', 'green']);
  // Window sizes: an empty header (no title, no name) is 14 px shorter; no background loses the 5 px margin.
  assert.deepEqual(V.overlaySize(V.overlayOptions('?layout=items')), [370, 203]);
  assert.deepEqual(V.overlaySize(V.overlayOptions('?layout=items&title=none')), [370, 189]);
  assert.deepEqual(V.overlaySize(V.overlayOptions('?layout=items&title=none&bg=none')), [360, 179]);
  assert.deepEqual(V.overlaySize(V.overlayOptions('?layout=card&name=character&title=none')), [500, 135]);
  assert.equal(V.overlayQuery(o), 'layout=chart&theme=blue&bg=green&interval=1800&range=1440&background=abcdef');
  assert.equal(V.overlayQuery(V.overlayOptions('')), '');
  assert.equal(V.headerInk('ffffff'), 'dark');
  assert.match(V.randomOverlayColors().background, /^[0-9a-f]{6}$/);
});

test('identity: a matching on-screen name skips the different-character pause; jobs match a closed list', async () => {
  const other = [r(0, 20, 5000), r(20, 20, 5100), r(40, 35, 100), r(60, 35, 200)];
  let state = {last: null, pending: null};
  let last;
  for (const reading of other) ({state, ...last} = E.step(table, state, reading, {trustedIdentity: true}));
  assert.equal(last.status, 'accepted');  // Same name on screen: a new baseline, not an identity pause.
  assert.equal(state.last.level, 35);
  const R = await import(new URL('reader.js', web));
  assert.equal(R.matchJob('Swordsman', V.JOBS), 'Swordsman');
  assert.equal(R.matchJob('Sw0rdsman', V.JOBS), 'Swordsman');
  assert.equal(R.matchJob('Wizard (Ice, Lightning)', V.JOBS), 'Wizard (Ice, Lightning)');
  assert.equal(R.matchJob('Wizard', V.JOBS), null);  // Two wizard jobs are equally close.
  assert.equal(R.matchJob('Swenrdsrman', V.JOBS), null);
  assert.equal(R.matchJob('', V.JOBS), null);
});

test('a softened job needs two matching reads and a unique known job', async () => {
  const R = await import(new URL('reader.js', web));
  const frame = {width: 24, height: 12, data: new Uint8ClampedArray(24 * 12 * 4).fill(120)};
  const run = async (texts) => {
    let calls = 0;
    const result = await R.readIdentity({read: async (_, field) => {
      assert.equal(field, 'job'); calls++; return {text: texts.shift()};
    }}, frame, {job: {x0: 0, y0: 0, x1: 24, y1: 12}}, null, V.JOBS);
    return {...result, calls};
  };
  assert.equal((await run(['Swdrdsman', 'Zegrdsman', 'Zwardsman', 'Zwtd seman', 'Swordsman', 'Swordsman'])).job, 'Swordsman');
  assert.equal((await run(['', '', '', '', 'Fighter', 'Page', 'Spearman', 'Swordsman'])).job, null);
  assert.equal((await run(['', '', '', '', 'Wizard', 'Wizard'])).job, null);
  assert.equal((await run(['Swordsman', 'Swordsman'])).calls, 2);
});

for (const initialKey of ['job', 'old-job']) {
  test(`job OCR failures retry without caching a success: ${initialKey}`, async () => {
    const saved = [], reads = [null, 'Swordsman'];
    const current = {nameChecked: 1, lastFrame: {}}, outcome = {frameWidth: 1366, frameHeight: 796,
      identity: {nameKey: 'name', jobKey: 'job', jobGlyphs: []}, boxes: {job: {}}};
    let attempts = 0;
    const context = vm.createContext({character: {id: 1, nameKey: 'name', nameSize: '1366x796', nameGlyphs: [], nameSource: 'user', job: 'Beginner', jobKey: initialKey},
      engine: {}, JOBS: V.JOBS, readIdentity: async () => { attempts++; return {job: reads.shift()}; },
      teachLetters: async () => {}, refreshCharacters: async () => {}, broadcast() {},
      store: {async saveCharacter(c) { saved.push(c); return 1; }, async getCharacter() { return saved.at(-1); }},
    });
    vm.runInContext(app.slice(app.indexOf('const ownsName ='), app.indexOf('async function handle(')), context);
    await context.identify(current, outcome, 1000); await context.identify(current, outcome, 2000);
    assert.equal(attempts, 1); assert.equal(saved.length, 0);
    assert.equal(context.character.jobKey, initialKey); assert.equal(context.character.job, 'Beginner');
    await context.identify(current, outcome, 3000); assert.equal(attempts, 1);
    await context.identify(current, outcome, 32000); await context.identify(current, outcome, 33000);
    assert.equal(attempts, 2); assert.equal(context.character.job, 'Swordsman'); assert.equal(context.character.jobKey, 'job');
    await context.identify(current, outcome, 34000); assert.equal(attempts, 2);
  });
}

test('panel lines beside the level badge give stable per-line keys', async () => {
  const G = await import(new URL('glyphs.js', web));
  const width = 200, height = 40, data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) data.set([50, 55, 60, 255], i * 4);
  const paint = (x0, y0, x1, y1, rgb) => { for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) data.set([...rgb, 255], (y * width + x) * 4); };
  paint(10, 15, 30, 28, [240, 130, 30]);  // Orange badge.
  paint(15, 18, 17, 20, [255, 255, 255]);
  for (const x of [40, 44, 48]) paint(x, 9, x + 2, 17, [255, 255, 255]);  // Job line.
  for (const x of [40, 45]) paint(x, 23, x + 3, 33, [255, 255, 255]);  // Name line.
  const frame = {width, height, data};
  const badge = H.orangeBox(frame, {x0: 0, y0: 0, x1: 35, y1: 40});
  const lines = H.panelLines(frame, badge);
  assert.deepEqual([lines.job.y0, lines.job.y1, lines.name.y0, lines.name.y1], [9, 17, 23, 33]);
  assert.equal(G.lineKey(frame, lines.name), G.lineKey(frame, lines.name));
  assert.notEqual(G.lineKey(frame, lines.name), G.lineKey(frame, lines.job));
  assert.equal(G.trimKey('000/010/000'), '010');
});

test('a name with joined glyphs needs two matching whole-line OCR reads', async () => {
  const R = await import(new URL('reader.js', web));
  const frame = {width: 16, height: 12, data: new Uint8ClampedArray(16 * 12 * 4)};
  for (let y = 3; y < 9; y++) for (const x of [2, 6, 7, 8, 9]) frame.data.fill(255, (y * 16 + x) * 4, (y * 16 + x) * 4 + 4);
  const boxes = {name: {x0: 0, y0: 0, x1: 16, y1: 12}};
  const nameFrom = async (fallback) => {
    const texts = ['Cara', 'Gara', 'Caia', 'Cora', ...fallback];
    const engine = {read: async () => ({text: texts.shift()})};
    return (await R.readIdentity(engine, frame, boxes, null, [])).name;
  };
  assert.equal(await nameFrom(['CharA', 'CharB', 'CharA']), 'CharA');
  assert.equal(await nameFrom(['CharA', 'CharB', 'CharC']), null);
});

test('a blurred name can agree in whole-line OCR at the same glyph count', async () => {
  const R = await import(new URL('reader.js', web));
  const frame = {width: 24, height: 12, data: new Uint8ClampedArray(24 * 12 * 4)};
  for (let y = 3; y < 9; y++) for (const x of [2, 6, 10, 14, 18]) frame.data.fill(255, (y * 24 + x) * 4, (y * 24 + x) * 4 + 4);
  const nameFrom = async (fallback) => {
    const texts = ['Ca', 'Ga', 'Cai', 'Co', ...fallback];
    return (await R.readIdentity({read: async () => ({text: texts.shift()})}, frame,
      {name: {x0: 0, y0: 0, x1: 24, y1: 12}}, null, [])).name;
  };
  assert.equal(await nameFrom(['CharA', 'CharA', 'CharB']), 'CharA');
  assert.equal(await nameFrom(['CharA', 'CharB', 'CharC']), null);
  assert.equal(await nameFrom(['Char A', 'Char A', 'CharB']), null);
});

test('badge glyph matching ignores a cursor at the lower tile edge', async () => {
  const R = await import(new URL('reader.js', web));
  const G = await import(new URL('glyphs.js', web));
  const frame = {width: 100, height: 20, data: new Uint8ClampedArray(100 * 20 * 4)};
  const paint = (x, y, rgb) => frame.data.set([...rgb, 255], (y * frame.width + x) * 4);
  for (let y = 2; y < 15; y++) for (let x = 3; x < 24; x++) paint(x, y, [240, 130, 30]);
  for (const left of [5, 14]) '0111110/1100011/0000011/0011110/0110000/1100000/1111111'.split('/').forEach((row, y) => {
    [...row].forEach((bit, x) => { if (bit === '1') paint(left + x, y + 4, [255, 255, 255]); });
  });
  paint(11, 14, [255, 255, 255]);
  for (const x of [54, 77]) for (let y = 4; y < 12; y++) paint(x, y, [160, 185, 130]);
  const engine = {read: async (_, field) => {
    assert.ok(field === 'number' || field === 'percent', 'badge read from glyphs');
    return {text: field === 'number' ? '5000' : '25.00%'};
  }};
  const read = await R.readHud(engine, frame, {exp: {x0: 42, x1: 95, y0: 2, y1: 15}, level: {x0: 2, x1: 26, y0: 0, y1: 17}}, G.HUD_GLYPHS);
  assert.equal(read.level, 22);
  assert.equal(read.levelSource, 'glyphs');
});

test('letters: learned from verified text only when counts match; renames are authoritative', async () => {
  const G = await import(new URL('glyphs.js', web));
  const letters = {};
  assert.equal(G.learnLetters(letters, ['k1', 'k2', 'k3'], 'Cab'), 3);
  assert.equal(G.learnLetters(letters, ['k1', 'k2'], 'Cab'), 0);  // Counts differ: nothing learned.
  assert.equal(G.learnLetters(letters, ['k4', 'k5', 'k6', 'k7'], 'Pa ge'), 4);  // Spaces are gaps, not glyphs.
  G.learnLetters(letters, ['k2'], 'h');  // A conflicting job letter poisons the bitmap.
  assert.equal(letters.k2, '?');
  G.learnLetters(letters, ['k2'], 'a', {authoritative: true});  // A typed rename settles it.
  assert.equal(letters.k2, 'a');
});

test('pickup messages: outlined text lines, stack counting and reading helpers', async () => {
  const P = await import(new URL('pickups.js', web));
  const width = 200, height = 60;
  const frame = (lines) => {
    const data = new Uint8ClampedArray(width * height * 4);
    for (let i = 0; i < width * height; i++) data.set([120, 170, 220, 255], i * 4);  // Sky, no pure black.
    // Like the game font: 1-pixel light strokes, each with a pure-black outline on both sides.
    lines.forEach(([y, seed]) => {
      // Different messages use different strokes, like different words.
      for (let x = 60; x < 196; x += 3) if (Math.floor(x / 3) % 3 === seed % 3) for (let yy = y; yy < y + 7; yy++) {
        data.set([0, 0, 0, 255], (yy * width + x - 1) * 4); data.set([235, 235, 235, 255], (yy * width + x) * 4); data.set([0, 0, 0, 255], (yy * width + x + 1) * 4);
      }
    });
    return {width, height, data};
  };
  assert.equal(P.messageLines(frame([[48, 1]])).length, 1);
  assert.equal(P.messageLines(frame([])).length, 0);
  // Synthetic softened strokes: a grey backdrop, dark shadow and a partial 3x3 blur, without game pixels.
  const sharp = frame([[48, 1]]), softened = {width, height, data: new Uint8ClampedArray(width * height * 4).fill(60)};
  const grayAt = (x, y) => sharp.data[(y * width + x) * 4] === 235 ? 220 : sharp.data[(y * width + x) * 4] === 0 ? 0 : 60;
  for (let y = 1; y < height - 1; y++) for (let x = 1; x < width - 1; x++) {
    let value = 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) value += grayAt(x + dx, y + dy) * (dx ? 1 : 2) * (dy ? 1 : 2) / 16;
    value = value * .8 + grayAt(x, y) * .2;
    softened.data.set([value, value, value, 255], (y * width + x) * 4);
  }
  assert.equal(P.messageLines(softened).length, 0);
  assert.equal(P.messageLines(softened, true, true).length, 1);
  assert.equal(P.messageLines(frame([]), true, true).length, 0);
  assert.equal(P.messageLines(frame([[48, 1]]), true, true).length, 1);
  // Each new message enters at the bottom and pushes the stack up one 14-pixel slot. Messages are
  // reported once their lines have left the screen, each exactly once.
  const early = P.stackTracker();  // Lines already on screen when tracking starts are not counted.
  assert.deepEqual([...early.update(P.messageLines(frame([[48, 1]]), true), 0), ...early.update([], 5000)], []);
  const tracker = P.stackTracker(), done = [];
  const feed = (lines, at) => done.push(...tracker.update(P.messageLines(frame(lines), true), at));
  feed([], -70);
  feed([[48, 1]], 0); feed([[48, 1]], 70);  // One message, seen on two frames.
  feed([[34, 1], [48, 2]], 140); feed([[34, 1], [48, 2]], 210);  // A second one pushes it up.
  feed([[6, 1], [20, 2], [34, 3], [48, 1]], 280);  // Two more in one frame; the last repeats the first.
  feed([], 280); feed([[6, 1], [20, 2], [34, 3], [48, 1]], 350);  // A missed frame counts nothing again.
  assert.equal(done.length, 0);
  feed([], 5000);  // The stack has faded out.
  assert.deepEqual(done.map((m) => m.at), [0, 140, 280, 280]);
  assert.ok(done.every((m) => m.samples.length && m.samples[0].bits.length === m.samples[0].width * m.samples[0].height));
  // Every frame of a line is added up: a stroke seen in a single frame (scenery) is not in the combined sample.
  const fuse = P.stackTracker(), fusedDone = [];
  fuse.update([], -70);
  for (let i = 0; i < 10; i++) fusedDone.push(...fuse.update(P.messageLines(frame(i === 4 ? [[48, 1], [48, 2]] : [[48, 1]]), true), i * 70));
  fusedDone.push(...fuse.update([], 9000));
  const clean = P.messageLines(frame([[48, 1]]), true)[0], combined = fusedDone[0].samples.find((m) => m.width === clean.x1 - clean.x0 + 1);
  assert.ok(combined, 'a combined sample the width of the line');
  assert.equal(combined.bits.reduce((n, b) => n + b, 0), clean.bits.reduce((n, b) => n + b, 0));
  // A stray first line sets the bottom 6 px off the real stack: the vote moves it onto the real rows.
  const off = P.stackTracker(), late = [];
  off.update(P.messageLines(frame([[42, 1]]), true), 0);
  for (let i = 1; i <= 20; i++) off.update(P.messageLines(frame([[48, 2]]), true), i * 70);
  late.push(...off.update(P.messageLines(frame([[34, 2], [48, 3]]), true), 1500), ...off.update([], 9000));
  assert.ok(late.length >= 1, 'messages after a misplaced bottom are counted');

  // A line mask: "(+" then the digits "13" (a narrow 1 followed by a 4-column gap) and ")".
  const mask = {width: 24, height: 12, bits: new Uint8Array(24 * 12)};
  const ink = (x0, x1, y0, y1) => { for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) mask.bits[y * 24 + x] = 1; };
  ink(0, 0, 0, 11); ink(2, 4, 5, 5); ink(3, 3, 3, 7); ink(7, 7, 2, 8); ink(12, 15, 2, 8); ink(18, 18, 0, 11);
  assert.deepEqual(P.lineWords(mask).map((w) => w.glyphs.length), [3, 2]);  // The narrow 1 splits the word...
  assert.deepEqual(P.amountSpan(mask), [7, 16]);  // ...but the digits sit between "(+" and ")".
  assert.equal(P.tabOf('(Etc)'), 'Etc');
  assert.equal(P.tabOf('(Eqp)'), 'Equip');
  assert.equal(P.tabOf('(Usel'), 'Use');
  assert.equal(P.tabOf('earned.'), null);
  const items = [{name: 'Orange Mushroom Cap', tab: 'Etc'}, {name: 'Green Mushroom Cap', tab: 'Etc'}, {name: 'Blue Mushroom Cap', tab: 'Etc'}, {name: 'Blue Mushroom Hat', tab: 'Equip'}, {name: "Pig's Ribbon", tab: 'Etc'}];
  assert.equal(P.resolveItem(items, {name: 'Orange Mushro', cut: true, tab: 'Etc'}).name, 'Orange Mushroom Cap');
  assert.equal(P.resolveItem(items, {name: 'Blue Mushroom', cut: true, tab: 'Etc'}).name, 'Blue Mushroom Cap');  // The tab separates the cap from the hat.
  assert.equal(P.resolveItem(items, {name: 'Blue Mushroom', cut: true, tab: null}), null);  // Ambiguous without the tab: no guess.
  assert.equal(P.resolveItem(items, {name: "Fig's Ribhon", cut: false, tab: 'Etc'}).name, "Pig's Ribbon");  // OCR slips are tolerated.
  assert.equal(P.resolveItem(items, {name: 'Squishy Liquid', cut: false, tab: 'Etc'}), null);  // Not in the list.
  // Up to a third of the letters misread, when nothing else is close; short names must be exact.
  const more = [...items, {name: 'Squishy Liquid', tab: 'Etc'}, {name: 'Silver Ore', tab: 'Etc'}, {name: 'Sai', tab: 'Equip'}];
  assert.equal(P.resolveItem(more, {name: 'Syulshy Liguld', cut: false, tab: null}).name, 'Squishy Liquid');
  assert.equal(P.resolveItem(more, {name: 'Sliver Ora', cut: false, tab: null}).name, 'Silver Ore');
  assert.equal(P.resolveItem(more, {name: 'Si', cut: false, tab: null}), null);
  assert.equal(P.resolveItem([...more, {name: 'Silver Ora', tab: 'Etc'}], {name: 'Sliver Orb', cut: false, tab: null}), null);  // Two close: no guess.
  const feathers = [{name: 'Stiff Feather', tab: 'Etc'}, {name: 'Soft Feather', tab: 'Etc'}];
  assert.equal(P.resolveItem(feathers, {name: 'Sift Feather', cut: false, tab: 'Etc'}), null);
  assert.equal(P.resolveItem(feathers, {name: 'Stitf Feather', cut: false, tab: 'Etc'}).name, 'Stiff Feather');
  for (const item of feathers) assert.equal(P.resolveItem(feathers, {name: item.name, cut: false, tab: 'Etc'}), item);
  // A cut name that also starts Use items: the one Etc item (a drop) wins the tie; two Etc items still don't.
  const caps = [{name: 'Orange Mushroom Cap', tab: 'Etc'}, {name: 'Orange Mushroom Daydream', tab: 'Use'}, {name: 'Orange Mushroom Package', tab: 'Use'}];
  assert.equal(P.resolveItem(caps, {name: 'Orange Mushro', cut: true, tab: null}).name, 'Orange Mushroom Cap');
  assert.equal(P.resolveItem([...caps, {name: 'Orange Mushroom Doll', tab: 'Etc'}], {name: 'Orange Mushro', cut: true, tab: null}), null);
  const S = await import(new URL('pickup-session.js', web));
  assert.deepEqual(S.lineParts('Leather:1 eamed. (Etc)'), {amount: null, name: 'Leather', count: 1, tab: 'Etc'});  // "x1" read as ":1".
  assert.deepEqual(S.lineParts('Tree Branch x2 earned. (Etc)'), {amount: null, name: 'Tree Branch', count: 2, tab: 'Etc'});
  // Over light fog the inside of an "8" sits next to the strokes' own shadows: it stays background.
  const F = await import(new URL('message-font.js', web)), eight = F.seedFont({})['8'][0], fog = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) fog.set([180, 180, 180, 255], i * 4);
  for (let gx = 60; gx < 190; gx += 7) for (let y = 0; y < eight.h; y++) for (let x = 0; x < eight.w; x++) if (eight.bits[y * eight.w + x]) {
    const p = (40 + y) * width + gx + x;
    fog.set([245, 245, 245, 255], p * 4);
    if (x + 1 >= eight.w || !eight.bits[(y + 1) * eight.w + x + 1]) fog.set([6, 6, 6, 255], (p + width + 1) * 4);
  }
  const line = P.messageLines({width, height, data: fog}, true)[0], lw = line.x1 - line.x0 + 1;
  const got = Array.from({length: 9}, (_, y) => Array.from({length: 5}, (_, x) => line.bits[(40 + y - line.y0) * lw + 60 + x - line.x0] ? '#' : '.').join(''));
  assert.deepEqual(got, Array.from({length: 9}, (_, y) => Array.from({length: 5}, (_, x) => eight.bits[y * 5 + x] ? '#' : '.').join('')));
  // A glyph the mask lost strokes of reads from the line's brightness: strokes light, their shadows dark.
  const font8 = F.seedFont({}), W = eight.w, H = eight.h, lost = Uint8Array.from(eight.bits), gray = new Uint8Array((W + 1) * (H + 1)).fill(200);
  for (const [x, y] of [[1, 4], [2, 4], [3, 4], [4, 1], [4, 2]]) lost[y * W + x] = 0;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (eight.bits[y * W + x]) {
    gray[y * (W + 1) + x] = 245;
    if (!(x + 1 < W && y + 1 < H && eight.bits[(y + 1) * W + x + 1])) gray[(y + 1) * (W + 1) + x + 1] = 10;
  }
  assert.equal(F.readLine(font8, {width: W, height: H, bits: lost}), '?');
  assert.equal(F.readLine(font8, {width: W, height: H, bits: lost, gray}), '8');
  // Reads are remembered per glyph shape, and forgotten when the font learns: the lost "8" reads once taught.
  const taught = {width: W, height: H, bits: lost};
  assert.equal(F.readLine(font8, taught), '?');
  assert.equal(F.learnLine(font8, taught, '8'), 1);
  assert.equal(F.readLine(font8, taught), '8');
});

test('Safari retries unread pickup messages in word mode without replacing parsed readings', async () => {
  const S = await import(new URL('pickup-session.js', web));
  const mask = {width: 12, height: 12, bits: new Uint8Array(144)};
  const run = async (soft, first = '') => {
    const fields = [], engine = {exclusive: (fn) => fn(), read: async (_, field) => {
      fields.push(field);
      return {text: field === 'messageWord' ? 'You have gained mesos (+12)' : first};
    }};
    return {result: await S.readMessage(engine, [mask, mask], [], null, soft), fields};
  };
  const safari = await run(true);
  assert.deepEqual(safari.result.parsed, {kind: 'mesos', amount: 12, approx: false});
  assert.deepEqual(safari.fields, ['message', 'message', 'messageWord', 'messageWord']);
  const other = await run(false);
  assert.equal(other.result.parsed, null); assert.deepEqual(other.fields, ['message', 'message']);
  const existing = await run(true, 'You have gained mesos (+15)');
  assert.equal(existing.result.parsed.amount, 15); assert.deepEqual(existing.fields, ['message', 'message']);
});

test('Safari keeps known font digits when the fixed words are unreadable', async () => {
  const mask = {width: 120, height: 12, bits: new Uint8Array(1440)};
  for (const soft of [false, true]) {
    const context = vm.createContext({binarize: H.binarize, pgm: H.pgm, lineWords: () => [],
      readLine: () => 'Y?u have ?ai?ed ????s (+888)', learnLine() {}, amountSpan: () => null, URL, setTimeout, clearTimeout,
    });
    vm.runInContext(pickupSession.replace(/^import .*;\n/gm, '').replaceAll('export ', '')
      .replaceAll('import.meta.url', JSON.stringify(new URL('pickup-session.js', web).href)), context);
    const engine = {exclusive: (fn) => fn(), read: async () => ({text: 'You have gained mesos (+808)'})};
    const result = await context.readMessage(engine, [mask, mask], [], {}, soft);
    assert.equal(result.parsed.amount, soft ? 888 : 808);
    assert.equal(result.parsed.approx, false);
  }
});

test('Safari reads the amount suffix with delimiters instead of a possibly clipped digit span', async () => {
  const S = await import(new URL('pickup-session.js', web));
  const mask = {width: 180, height: 12, bits: new Uint8Array(2160)};
  for (const soft of [false, true]) for (const amount of ['30(+13)', '1313']) {
    const fields = [], engine = {exclusive: (fn) => fn(), read: async (_, field) => {
      fields.push(field);
      return {text: field === 'amount' ? amount : 'You have gained mesos'};
    }};
    const result = await S.readMessage(engine, [mask, mask], [], null, soft);
    if (soft && amount === '30(+13)') {
      assert.deepEqual(result.parsed, {kind: 'mesos', amount: 13, approx: false});
    } else assert.equal(result.parsed, null);
    assert.equal(fields.includes('amount'), soft);
  }
});

test('pickup message font: learned glyphs read later lines, misaligned lines are refused', async () => {
  const F = await import(new URL('message-font.js', web));
  // Three made-up 3x7 glyphs drawn into a line mask, two empty columns apart (five for a space).
  // "a" is short like the real one; "b" and "1" reach the top row.
  const shapes = {a: ['000', '000', '111', '101', '101', '101', '111'], b: ['100', '100', '111', '101', '101', '101', '111'], 1: ['010', '110', '010', '010', '010', '010', '111']};
  const line = (text) => {
    const cols = [];
    for (const char of text) {
      if (char === ' ') { cols.push(...Array(3).fill(null)); continue; }
      if (cols.length) cols.push(null, null);
      for (let x = 0; x < 3; x++) cols.push(shapes[char].map((row) => row[x] === '1' ? 1 : 0));
    }
    const width = cols.length, height = 9, bits = new Uint8Array(width * height);
    cols.forEach((col, x) => col?.forEach((v, y) => { bits[(y + 1) * width + x] = v; }));
    return {width, height, bits};
  };
  const font = {};
  assert.equal(F.learnLine(font, line('ab'), 'ab'), 2);
  assert.equal(F.readLine(font, line('ba')), 'ba');
  assert.equal(F.readLine(font, line('b1 a')), 'b? a');  // An unknown glyph is "?", never a guess.
  assert.equal(F.learnLine(font, line('ab'), 'ba'), 0);  // Glyphs that look like other characters.
  assert.equal(F.learnLine(font, line('ab1'), 'a'), 0);  // Glyph and character counts differ.
  // Whole names compared shape by shape: the closest name wins; a letter the font lacks costs the same for all.
  const names = [{name: 'abba', tab: 'Etc'}, {name: 'baab', tab: 'Etc'}, {name: 'abab', tab: 'Etc'}];
  const matched = F.matchName(font, [line('abba')], names);
  assert.equal(matched.item.name, 'abba');
  assert.equal(matched.cost, 0);
  assert.ok(matched.next >= 1);
  // The shipped font fills characters not learned yet (at most four variants each), keeps learned
  // variants, and drops one clearly closer to another character: a 6 learned as "8".
  const shipped = F.seedFont({});
  assert.ok(Object.keys(shipped).length > 40 && Object.values(shipped).every((v) => v.length <= 4 && v.every((g) => g.bits.length === g.w * g.h)));
  const kept = F.seedFont({8: [{...shipped[8][0]}]}), healed = F.seedFont({8: [{...shipped[6][0]}]});
  assert.equal(kept[8].length, shipped[8].length);  // A learned copy of a shipped 8 adds nothing.
  assert.ok(healed[8].every((g) => g.bits.join('') !== shipped[6][0].bits.join('')));
  // Words pair up by the widest gaps; a word with one piece too many joins its narrowest close pair
  // (an "x" whose centre was not seen comes in two 2-px pieces).
  const g = (w, gap) => ({w, h: 3, gap, bits: new Uint8Array(w * 3).fill(1)});
  const pairs = F.alignLine([g(5, 0), g(4, 1), g(2, 3), g(2, 1), g(3, 2), g(5, 5)], 'Le x1 e');
  assert.deepEqual(pairs.map(([glyph, char]) => `${char}${glyph.w}`), ['L5', 'e4', 'x5', '13', 'e5']);
  assert.deepEqual(F.alignLine([g(5, 0), g(4, 2), g(4, 2)], 'L e'), []);  // No gap clearly wider: no spaces to anchor on.
  const S = await import(new URL('pickup-session.js', web));
  assert.equal(S.rounded([23, 28]), 20);  // Unconfirmed reads round down to what they agree on.
  assert.equal(S.rounded([23]), 20);
  assert.equal(S.rounded([1250, 1290]), 1200);
  assert.equal(S.rounded([132, 13]), 10);  // A ")" read as a digit does not make it 100.
  assert.equal(S.rounded([132, 13, 138]), 130);  // Unless most reads have three digits.
});

test('the digit row ignores a panel border caught by a box that is too tall', () => {
  const width = 30, height = 14, data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) data.set([60, 60, 60, 255], i * 4);
  for (let x = 0; x < width; x++) data.set([220, 220, 220, 255], (1 * width + x) * 4);  // Border: a solid bright row.
  for (let y = 5; y < 12; y++) for (const x of [3, 4, 9, 15]) data.set([255, 255, 255, 255], (y * width + x) * 4);  // Digits.
  assert.deepEqual(H.inkRows({width, height, data}, {x0: 0, y0: 0, x1: width, y1: height}), {top: 5, bottom: 11});
});

test('level planner: EXP to each later level adds the rest of this one and whole later ones', async () => {
  const {climb} = await import(new URL('level-plan.js', web));
  const table = {to_next: {'22': 29000, '23': 33000, '24': 37000}};
  assert.deepEqual(climb(table, 22, 9000, 25), [{level: 23, exp: 20000}, {level: 24, exp: 53000}, {level: 25, exp: 90000}]);
  assert.deepEqual(climb(table, 24, 0, 30), [{level: 25, exp: 37000}]);  // Stops where the table ends.
});

test('level planner: hours a day spread play over days; EXP typed with commas or decimals is whole', async () => {
  const {when, whole} = await import(new URL('level-plan.js', web));
  const now = new Date(2026, 10, 12, 9, 0).getTime();  // A Thursday morning.
  assert.equal(when(3, 4, now), 'Today');
  assert.equal(when(4, 4, now), 'Today');  // Exactly a day's play.
  assert.equal(when(6, 4, now), 'Tomorrow');
  assert.equal(when(9, 4, now), new Date(2026, 10, 14).toLocaleDateString(undefined, {weekday: 'short'}));
  assert.equal(whole('52,300'), 52300);
  assert.equal(whole('123.4'), 123);
  assert.equal(whole('abc'), 0);
});

test('level planner: the finish moment and the hours of play before a date, at hours a day', async () => {
  const {finish, playable} = await import(new URL('level-plan.js', web));
  const now = 0, h = 36e5, d = 864e5;
  assert.equal(finish(3, 4, now), 3 * h);           // Done today.
  assert.equal(finish(6, 4, now), d + 2 * h);       // A day's 4 h, then 2 h tomorrow.
  assert.equal(finish(30, 24, now), 30 * h);        // All day: straight through.
  assert.equal(playable(d + 2 * h, 4), 6);          // The same moment back: 6 h of play.
  assert.equal(playable(d + 10 * h, 4), 8);         // A second day plays its 4 h at most.
});

test('pickup stack: lines whose numbers read differently are new messages, even swapped whole in one frame', async () => {
  const P = await import(new URL('pickups.js', web));
  const width = 200, height = 60;
  // Each message its own stroke pattern; a fixed "number" per pattern stands in for the font's read.
  const frame = (lines) => {
    const data = new Uint8ClampedArray(width * height * 4);
    for (let i = 0; i < width * height; i++) data.set([120, 170, 220, 255], i * 4);
    for (const [y, seed] of lines) for (let x = 60; x < 196; x += 3) if ((x * seed) % 7 < 3) for (let yy = y; yy < y + 7; yy++) {
      data.set([0, 0, 0, 255], (yy * width + x - 1) * 4); data.set([235, 235, 235, 255], (yy * width + x) * 4); data.set([0, 0, 0, 255], (yy * width + x + 1) * 4);
    }
    return {width, height, data};
  };
  const read = (mask) => `You have gained mesos (+${mask.bits.reduce((sum, bit, i) => sum + bit * (i % mask.width) * (i % 13), 0) % 997})`;
  const t = P.stackTracker({read}), done = [];
  for (let i = 0; i < 5; i++) done.push(...t.update(P.messageLines(frame([[48, 2], [34, 3], [20, 4]]), true), i * 70));
  assert.equal(done.length, 0);  // On screen when tracking began: followed, not counted.
  for (let i = 5; i < 10; i++) done.push(...t.update(P.messageLines(frame([[48, 5], [34, 6], [20, 8]]), true), i * 70));
  done.push(...t.update([], 9000));
  assert.equal(done.length, 3);  // All three new lines, once each.
});

test('pickup area: the right quarter above the status bar, never narrower than 300 px', async () => {
  const {regionBox} = await import(new URL('pickup-session.js', web));
  assert.deepEqual(regionBox(1368, 800), {x: 1026, y: 360, w: 342, h: 352});  // As tuned (768p window).
  assert.equal(regionBox(1920, 1080).x, 1440);  // Stretched 1080p: unchanged.
  assert.deepEqual(regionBox(800, 600), {x: 500, y: 270, w: 300, h: 264});  // 800x600: widened.
});


test('overlay stats validate choices, preserve layout slots and round trip local settings', () => {
  const query = '?card1=rate:10&bar2=percent:60&rates4=gain:1440&live5=gain:session&card3=mesoRate:30&bar1=mesos:1440';
  const options = V.overlayOptions(query);
  assert.equal(options.live5, 'gain:session');
  assert.equal(options.card3, 'mesoRate:30');
  assert.equal(V.overlayOptions(V.overlayQuery(options)).rates4, 'gain:1440');
  const publicOptions = OverlayStats.read(query);
  assert.equal(publicOptions.card1, 'rate:10');
  assert.equal(publicOptions.card3, undefined);
  assert.equal(publicOptions.live5, undefined);
  for (const value of ['rate:1440', 'eta:session', 'gain:0', 'gain:5:bad', 'bad:15', 'mesos:session']) {
    assert.deepEqual(OverlayStats.read('?card1=' + value, true), {});
  }
  assert.equal(OverlayStats.label('eta', '10'), 'NEXT LEVEL');
  assert.equal(OverlayStats.label('gain', 'session'), 'This session');
});

test('custom local overlay stats use accepted intervals, coverage and the latest session', () => {
  const popout = readFileSync(new URL('popout.js', web), 'utf8');
  const body = popout.split('OverlayStats.render(options, (metric, period) => {')[1].split('\n  });')[0];
  const now = at(600), readings = [
    {...r(0, 20, 100), sessionId: 1, gain: null},
    {...r(300, 20, 200), sessionId: 1, gain: 100},
    {...r(360, 20, 200), sessionId: 2, gain: null},
    {...r(600, 20, 400), sessionId: 2, gain: 200},
  ];
  const view = V.summarize(table, {last: readings.at(-1)}, readings, now);
  const pickups = [{at: at(0), kind: 'mesos', amount: 100}, {at: at(500), kind: 'mesos', amount: 300}];
  const resolve = vm.runInNewContext(`(metric, period) => {${body}}`, {readings, pickups, now, view, table,
    windowStats: E.windowStats, sessionStats: E.sessionStats, eta: E.eta, duration: V.duration, expText: V.exp});
  assert.equal(resolve('gain', 'session'), '200');
  assert.equal(resolve('gain', '10'), '300');
  assert.equal(resolve('rate', '5'), '3,000');
  assert.equal(resolve('rate', '60'), '—');
  assert.equal(resolve('eta', '60'), '—');
  assert.equal(resolve('mesos', '5'), '300');
  assert.equal(resolve('mesoRate', '5'), '3,600');
});


test('level crop excludes orange scenery, preserves all tiles and rejects ambiguous or clipped groups', () => {
  const width = 130, height = 50, frame = {width, height, data: new Uint8ClampedArray(width * height * 4)};
  const paint = (x0, y0, x1, y1, rgb) => { for (let y=y0; y<y1; y++) for(let x=x0; x<x1; x++) frame.data.set([...rgb,255], (y*width+x)*4); };
  const tile = (x, y) => { paint(x,y,x+11,y+13,[240,130,30]);paint(x+3,y+3,x+6,y+9,[255,255,255]); };
  const region = {x0:0,y0:0,x1:width,y1:height};
  paint(1,4,20,15,[200,110,50]); paint(12,25,25,33,[240,130,30]);
  assert.equal(H.orangeBox(frame,region),null); // Scenery has no enclosed digit ink.
  for (let n=1;n<=3;n++) {
    tile(60+(n-1)*12,20);
    assert.deepEqual(H.orangeBox(frame,region),{x0:60,y0:20,x1:60+(n-1)*12+11,y1:33});
  }
  assert.equal(H.orangeBox(frame,{...region,x0:64}),null); // First tile cut off.
  assert.equal(H.orangeBox(frame,{...region,x1:90}),null); // Last tile cut off.
  assert.equal(H.orangeBox(frame,{...region,y0:23}),null); // Digit tops cut off.
  tile(35,2);
  assert.equal(H.orangeBox(frame,region),null); // Two plausible badge groups: never guess.
});


test('an empty local overlay still applies custom stat labels with unavailable values', () => {
  const popout = readFileSync(new URL('popout.js', web), 'utf8');
  const render = popout.slice(popout.indexOf('function render() {'), popout.indexOf('// The Live layout mirrors'));
  const calls = [], characterLabel = {};
  const context = vm.createContext({table: {}, character: null, options: {layout:'live',live1:'gain:10'}, Date,
    renderItems() {}, $: () => characterLabel, OverlayStats: {render(options, resolve) { calls.push({options, value:resolve('gain','10')}); }}});
  vm.runInContext(render + '\nrender();', context);
  assert.equal(calls.length, 1); assert.equal(calls[0].options.live1,'gain:10'); assert.equal(calls[0].value,'\u2014');
  assert.equal(characterLabel.textContent,'Start tracking at msxp.pages.dev/local');
});


test('local General level visibility round trips without changing its independent badge color', () => {
  const options=V.overlayOptions('?showlevel=off&level=abcdef');
  assert.equal(options.showlevel,'off'); assert.equal(options.level,'abcdef');
  assert.equal(V.overlayOptions(V.overlayQuery(options)).showlevel,'off');
  assert.equal(V.overlayOptions('').showlevel,'on');
});


test('empty Items preview updates its filters and slots without a character or EXP table', () => {
  const popout = readFileSync(new URL('popout.js', web), 'utf8');
  const render = popout.slice(popout.indexOf('function render() {'), popout.indexOf('// The Live layout mirrors'));
  const items = popout.slice(popout.indexOf('function renderItems(now) {'), popout.indexOf('// The pop-out window'));
  const elements = {}, context = vm.createContext({table: null, character: null, Date, Map,
    options: {layout:'items',kind:'equip',last:'5'}, pickups: [], icons: null, shownCounts: null, bumps: new Map(), GLOW_MS: 1200,
    summarizePickups: V.summarizePickups, exp: V.exp,
    $: id => elements[id] ??= {replaceChildren(...children) { this.children=children; }},
    document: {createElement() { return {setAttribute(key,value) { this[key]=value; }}; }},
    loadItems() { throw new Error('Empty previews must not load icons'); },
  });
  vm.runInContext(render + '\n' + items + '\nrender();', context);
  assert.equal(elements['items-since'].textContent,'Equip \u00b7 last 5 min');
  assert.equal(elements['items-total'].textContent,'None yet');
  assert.equal(elements['items-grid'].children.length,12);
  assert.ok(elements['items-grid'].children.every(slot=>slot.className==='items-slot' && slot['aria-hidden']==='true'));
  vm.runInContext("options.kind='use';options.last='30';render();",context);
  assert.equal(elements['items-since'].textContent,'Use \u00b7 last 30 min');
  vm.runInContext("options.kind='all';options.last='1440';render();",context);
  assert.equal(elements['items-since'].textContent,'Items \u00b7 last 24 h');
});

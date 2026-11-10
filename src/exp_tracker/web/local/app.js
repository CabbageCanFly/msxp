// /local: capture the game window the user shares, read the HUD every few seconds, track locally.
// No network requests besides this site's own static files; nothing leaves the browser.
import * as store from './store.js';
import {acceptBaseline, maxGapFor, resolveLevel, step} from './exp.js';
import {denormalize, locate, normalize, orangeBox} from './hud.js';
import {fieldBoxes, readHud} from './reader.js';
import {displayed, learn} from './glyphs.js';
import {CHANNEL, JOBS, chartSvg, compact, duration, exp as fmtExp, jobIcon, percent, summarize} from './view.js';

const $ = (id) => document.getElementById(id);
const INTERVALS = [5, 10, 20, 30];
const debug = new URLSearchParams(location.search).has('debug');
const channel = 'BroadcastChannel' in window ? new BroadcastChannel(CHANNEL) : null;
// One capture session per browser profile: a second /local tab neither tracks nor closes the first's session.
const LOCK = 'msxp-local-capture';
let releaseLock = null;

async function acquireLock() {
  if (!navigator.locks) return true;
  return new Promise((resolve) => {
    navigator.locks.request(LOCK, {ifAvailable: true}, (lock) => {
      if (!lock) { resolve(false); return; }
      resolve(true);
      return new Promise((release) => { releaseLock = release; });
    });
  });
}

const lockHeldElsewhere = async () => Boolean((await navigator.locks?.query?.())?.held?.some((l) => l.name === LOCK));

let table = null, engine = null, enginePromise = null;
// glyphs: templates learned from confirmed readings, valid only for one calibration (window size and boxes).
let settings = {interval: 20, window: 15, calibration: null, activeCharacterId: null, glyphs: null};
let character = null, readingsCache = [];
// Capture session state; only exists while the user is sharing a window.
let capture = null;  // {stream, track, grabber, video, sessionId, tracker, timer, lastFrame, ...}
let lastScan = null, identitySuspect = null;

async function loadTable() {
  const response = await fetch('/static/local/community-exp.json');
  if (!response.ok) throw new Error('EXP table unavailable');
  table = await response.json();
}

function getEngine() {
  return enginePromise ??= import('./ocr.js').then((m) => m.createEngine()).then((e) => (engine = e))
    .catch((error) => { enginePromise = null; throw error; });
}

// ---------- characters ----------

async function refreshCharacters() {
  const list = (await store.characters()).sort((a, b) => a.name.localeCompare(b.name));
  const select = $('character-select');
  select.replaceChildren(...list.map((c) => new Option(c.name, c.id)), new Option('+ New character…', 'new'));
  character = list.find((c) => c.id === settings.activeCharacterId) ?? list[0] ?? null;
  select.value = character ? String(character.id) : 'new';
  if (!character) openCharacterForm(true);
  readingsCache = character ? await store.readings(character.id, Date.now() - 6 * 3600e3) : [];
  render();
}

function openCharacterForm(isNew) {
  const form = $('character-form');
  form.hidden = false; form.dataset.mode = isNew ? 'new' : 'edit';
  $('character-name').value = isNew ? '' : character?.name ?? '';
  $('character-job').value = isNew ? 'Beginner' : character?.job || 'Beginner';
  $('character-new').hidden = isNew || !character; $('character-delete').hidden = isNew || !character;
  $('character-cancel').hidden = !character;
  $('character-name').focus();
}

async function saveCharacterForm(asNew) {
  const name = $('character-name').value.trim().slice(0, 20), job = $('character-job').value;
  if (!name) return $('character-name').reportValidity();
  const isNew = asNew || $('character-form').dataset.mode === 'new' || !character;
  // A renamed character keeps its history; a new one never inherits another character's readings.
  const id = await store.saveCharacter(isNew ? {name, job} : {...character, name, job});
  $('character-form').hidden = true;
  await selectCharacter(id);
}

async function selectCharacter(id) {
  if (capture && character && character.id !== id) await restartSession('character_switch', id);
  settings.activeCharacterId = id; await store.setSetting('activeCharacterId', id);
  identitySuspect = null;
  await refreshCharacters();
  broadcast();
}

// ---------- capture ----------

async function start() {
  if (capture) return;
  if (!character) { openCharacterForm(true); return setStatus('Name your character first', 'warn'); }
  if (!navigator.mediaDevices?.getDisplayMedia) return setStatus('This browser cannot share a window. Use Chrome or Edge on a computer.', 'warn');
  if (!await acquireLock()) return setStatus('Tracking is already running in another msxp tab or window.', 'warn');
  setStatus('Choose the MapleStory window in the sharing dialog…');
  let stream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      // A low frame rate is only a request; scans sample the latest frame on their own schedule.
      video: {displaySurface: 'window', frameRate: {ideal: 5, max: 5}, cursor: 'never'},
      audio: false, selfBrowserSurface: 'exclude', surfaceSwitching: 'include', preferCurrentTab: false,
    });
  } catch (error) {
    releaseLock?.(); releaseLock = null;
    return setStatus(error.name === 'NotAllowedError' ? 'Sharing was cancelled' : `Could not share: ${error.message}`, 'warn');
  }
  const [track] = stream.getVideoTracks();
  capture = {stream, track, tracker: null, sessionId: null, timer: null, scans: [], failures: 0, lastDetect: 0};
  track.addEventListener('ended', () => stop('sharing_stopped'));
  capture.grabber = 'ImageCapture' in window ? new ImageCapture(track) : null;
  if (!capture.grabber) {
    const video = Object.assign(document.createElement('video'), {muted: true, playsInline: true, srcObject: stream});
    await video.play().catch(() => {});
    capture.video = video;
  }
  window.addEventListener('beforeunload', guardUnload);
  document.body.dataset.tracking = 'on';
  $('start').hidden = true; $('stop').hidden = false;
  for (const id of ['hud-detect', 'hud-preview', 'hud-draw-exp', 'hud-draw-level']) $(id).disabled = false;
  await beginSession();
  setStatus('Loading the text reader…');
  try { await getEngine(); } catch (error) { stop('ocr_failed'); return setStatus(`Text reader failed to load: ${error.message}`, 'warn'); }
  store.prune().catch(() => {});
  navigator.storage?.persist?.().then(updateStorageNote).catch(() => {});
  scan();
}

async function beginSession() {
  const at = Date.now();
  capture.sessionId = await store.startSession(character.id, at);
  // A new session never continues the previous interval; the last reading is only an identity reference.
  capture.tracker = {last: null, pending: null, reference: character.last ?? null};
}

async function restartSession(reason, nextCharacterId) {
  clearTimeout(capture.timer);
  await store.endSession(capture.sessionId, Date.now(), reason);
  settings.activeCharacterId = nextCharacterId;
  character = await store.getCharacter(nextCharacterId);
  await beginSession();
  capture.timer = setTimeout(scan, 1000);
}

async function stop(reason = 'stopped') {
  if (!capture) return;
  const current = capture;
  capture = null;
  clearTimeout(current.timer);
  current.stream.getTracks().forEach((t) => t.stop());
  if (current.video) current.video.srcObject = null;
  window.removeEventListener('beforeunload', guardUnload);
  document.body.dataset.tracking = 'off';
  $('start').hidden = false; $('stop').hidden = true;
  for (const id of ['hud-detect', 'hud-preview', 'hud-draw-exp', 'hud-draw-level']) $(id).disabled = true;
  $('hud-view').hidden = true; drawing = null;
  if (current.sessionId) await store.endSession(current.sessionId, Date.now(), reason).catch(() => {});
  releaseLock?.(); releaseLock = null;
  setStatus(reason === 'sharing_stopped' ? 'Sharing stopped. Your readings are saved.' : 'Not tracking. Your readings are saved.');
  render();
}

function guardUnload(event) {
  // The browser decides whether and how to confirm; saved readings are safe either way.
  event.preventDefault();
  event.returnValue = '';
}

async function grab() {
  const {track, grabber, video} = capture;
  const {width, height} = track.getSettings();
  let source, w, h;
  if (grabber) {
    // A minimized window may stop producing frames; don't wait forever.
    source = await Promise.race([grabber.grabFrame(), new Promise((_, reject) => setTimeout(() => reject(new Error('no_frame')), 4000))]);
    w = source.width; h = source.height;
  } else {
    if (!video.videoWidth) throw new Error('no_frame');
    source = video; w = video.videoWidth; h = video.videoHeight;
  }
  const canvas = capture.canvas ??= new OffscreenCanvas(1, 1);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const context = canvas.getContext('2d', {willReadFrequently: true});
  context.drawImage(source, 0, 0);
  source.close?.();
  const frame = context.getImageData(0, 0, w, h);
  return {width: frame.width, height: frame.height, data: frame.data, reported: {width, height}};
}

function regionsFor(frame) {
  const c = settings.calibration;
  if (!c || !c.exp) return null;
  // Normalized boxes follow a resized window only when the aspect ratio is unchanged.
  if (Math.abs(c.width / c.height - frame.width / frame.height) > .01) return null;
  return {exp: denormalize(c.exp, frame), level: c.level && denormalize(c.level, frame)};
}

async function detect(frame) {
  capture.lastDetect = Date.now();
  const found = await engine.labels(frame);
  const result = locate(found, frame);
  if (!result.exp) return result.reason;
  await saveCalibration({source: 'auto', width: frame.width, height: frame.height, exp: normalize(result.exp, frame),
    level: normalize(result.level, frame)});
  return null;
}

async function saveCalibration(calibration) {
  settings.calibration = calibration;
  await store.setSetting('calibration', calibration);
  // A different window size or box means different pixels: start learning glyphs again.
  const size = `${calibration.width}x${calibration.height}`;
  if (settings.glyphs?.size !== size) await saveGlyphs({size, templates: {}});
}

async function saveGlyphs(glyphs) {
  settings.glyphs = glyphs;
  await store.setSetting('glyphs', glyphs);
}

async function scan() {
  if (!capture) return;
  const current = capture, started = performance.now(), at = Date.now();
  let outcome;
  try {
    const frame = await grab();
    if (capture !== current) return;
    current.lastFrame = frame;
    outcome = await engine.exclusive(async () => {
      let regions = regionsFor(frame);
      const stale = !regions || (current.failures >= 3 && settings.calibration?.source === 'auto' && Date.now() - current.lastDetect > 60e3);
      if (stale && settings.calibration?.source !== 'manual' || !regions) {
        const reason = await detect(frame);
        regions = regionsFor(frame);
        if (!regions) return {status: 'no_hud', reason: reason ?? 'hud_not_found'};
      }
      const glyphs = settings.glyphs?.size === `${frame.width}x${frame.height}` ? settings.glyphs.templates : null;
      return readHud(engine, frame, regions, glyphs);
    });
    if (!outcome) return;  // A previous scan is still running; never queue another.
    if (capture !== current) return;
    outcome.frameWidth = frame.width; outcome.frameHeight = frame.height;
    lastScan = {...outcome, frame, at, ms: performance.now() - started};
    await handle(current, outcome, at);
    if (!$('hud-view').hidden) drawPreview();
  } catch (error) {
    if (capture !== current) return;
    current.failures++;
    setStatus(error.message === 'no_frame' ? 'No picture from the game window. Is it minimized?' : `Scan failed: ${error.message}`, 'warn');
    await store.record(character.id, current.sessionId, [], current.tracker, error.message === 'no_frame' ? 'no_frame' : 'error').catch(() => {});
  } finally {
    if (capture === current) {
      const ms = performance.now() - started;
      current.scans.push({at, ms});
      if (current.scans.length > 30) current.scans.shift();
      clearTimeout(current.timer);
      current.timer = setTimeout(scan, Math.max(500, settings.interval * 1000 - ms));
      renderScanStats();
    }
  }
}

const MESSAGES = {
  no_hud: 'Looking for the EXP bar… Keep the game window visible, or draw the HUD boxes below.',
  unreadable: 'Couldn\'t read the EXP numbers this time.',
  ambiguous: 'The EXP numbers were unclear, so this reading was skipped.',
  invalid: 'That reading didn\'t make sense, so it was skipped.',
  level_unreadable: 'Couldn\'t read your level badge.',
  level_disagrees_with_exp: 'Level and EXP didn\'t match the EXP table, so this reading was skipped.',
  awaiting_confirmation: 'Got a reading. Confirming it on the next scan…',
  level_change_pending: 'Level changed. Confirming on the next scan…',
  exp_decrease_pending: 'EXP went down. Confirming on the next scan…',
  large_jump_pending: 'Big EXP jump. Confirming on the next scan…',
  gap_requires_new_baseline: 'Resuming after a gap. Confirming on the next scan…',
  non_increasing_time: 'Clock went backwards; reading skipped.',
};

async function handle(current, outcome, at) {
  let status = outcome.status, reason = outcome.reason, accepted = [];
  if (status === 'ok') {
    const previous = current.tracker.last?.level ?? current.tracker.pending?.level ?? null;
    const resolved = resolveLevel(table, outcome.level, outcome.exp, outcome.bp, previous);
    if (resolved.level === null) { status = 'rejected'; reason = resolved.reason; }
    else {
      const result = step(table, current.tracker, {at, level: resolved.level, exp: outcome.exp, bp: outcome.bp}, {maxGapSeconds: maxGapFor(settings.interval)});
      current.tracker = result.state; accepted = result.accept; status = result.status; reason = result.reason;
      if (status === 'identity_check') identitySuspect = result.suspect;
    }
  }
  // Table-rejected readings count too: a box that clips digits reads 'cleanly' but never matches.
  current.failures = ['accepted', 'pending', 'identity_check'].includes(status) ? 0 : current.failures + 1;
  await store.record(character.id, current.sessionId, accepted, current.tracker, status);
  if (status === 'accepted' && outcome.source === 'ocr' && outcome.segments) await teach(outcome);
  if (accepted.length) {
    character = await store.getCharacter(character.id);
    readingsCache.push(...accepted.map((r) => ({...r, characterId: character.id, sessionId: current.sessionId})));
    broadcast();
  }
  if (status === 'accepted') setStatus('Tracking', 'ok');
  else if (status === 'identity_check') setStatus('Paused: this looks like a different character', 'warn');
  else setStatus(MESSAGES[reason] ?? MESSAGES[status] ?? reason, 'warn');
  render();
}

// Only a reading the tracker accepted (table-consistent, confirmed by a second scan) teaches glyphs.
async function teach(outcome) {
  const frameSize = `${outcome.frameWidth}x${outcome.frameHeight}`;
  const glyphs = settings.glyphs?.size === frameSize ? settings.glyphs : {size: frameSize, templates: {}};
  const text = displayed(outcome.exp, outcome.bp), templates = {...glyphs.templates};
  const added = (learn(templates, outcome.segments.number, text.number) ?? 0) + (learn(templates, outcome.segments.percent, text.percent) ?? 0);
  if (added || JSON.stringify(templates) !== JSON.stringify(glyphs.templates)) await saveGlyphs({size: frameSize, templates});
}

async function confirmIdentity() {
  if (!capture || !identitySuspect) return;
  const result = acceptBaseline(identitySuspect);
  capture.tracker = {...result.state, reference: null};
  await store.record(character.id, capture.sessionId, result.accept, capture.tracker, 'confirmed_by_user');
  character = await store.getCharacter(character.id);
  readingsCache.push(...result.accept.map((r) => ({...r, characterId: character.id, sessionId: capture.sessionId})));
  identitySuspect = null;
  setStatus('Tracking', 'ok'); render(); broadcast();
}

// ---------- rendering ----------

function setStatus(text, tone = '') {
  $('status').textContent = text;
  $('status').dataset.tone = tone;
}

function render() {
  if (!table) return;
  const now = Date.now();
  const view = summarize(table, character, readingsCache, now, settings.window, capture?.sessionId ?? null);
  $('player-name').textContent = character?.name || 'Your character';
  $('player-job').hidden = !character?.job;
  if (character?.job) { $('player-job-icon').src = jobIcon(character.job); $('player-job-name').textContent = character.job; }
  $('level').textContent = view.last ? `Lv. ${view.last.level}` : 'Lv. —';
  $('progress').value = view.progress;
  $('exp').textContent = view.last ? fmtExp(view.last.exp) : '—';
  $('percentage').textContent = view.last ? ` [${percent(view.last.bp)}]` : '';
  $('age').textContent = view.last ? `· last reading ${duration(view.age)} ago` : '';
  $('rate').textContent = view.perHour == null ? '—' : fmtExp(view.perHour);
  $('rate-label').textContent = settings.window === 'session' ? 'EXP / hour · session' : `EXP / hour · ${settings.window} min`;
  $('rate-note').textContent = view.perHour == null ? 'Needs a few minutes of readings'
    : (view.early ? `So far · ${duration(view.covered)} observed` : '') + (view.percentPerHour != null ? `${view.early ? ' · ' : ''}${view.percentPerHour.toFixed(2)}% / hour` : '');
  $('movement').textContent = view.recent == null ? '—' : fmtExp(view.recent);
  $('tracked-exp').textContent = capture ? compact(view.sessionGain) : compact(view.totalGain);
  $('tracked-note').textContent = capture ? `This session · ${duration(view.sessionCovered)} observed` : 'All time on this device';
  $('eta').textContent = view.eta == null ? '—' : duration(view.eta);
  $('eta-note').textContent = view.eta == null ? (view.last && !view.total ? 'No EXP table for this level' : 'Needs an EXP / hour') : `${fmtExp(view.total - view.last.exp)} EXP to go`;
  $('chart').innerHTML = chartSvg(view.buckets, {height: 120});
  $('identity').hidden = !identitySuspect;
  if (identitySuspect) {
    const ref = capture?.tracker.last ?? capture?.tracker.reference;
    $('identity-text').textContent = `The game shows Lv. ${identitySuspect.level} at ${percent(identitySuspect.bp)}, but ${character.name} was last Lv. ${ref?.level} at ${percent(ref?.bp)}. Readings are paused so histories don't mix.`;
  }
}

function renderScanStats() {
  const scans = capture?.scans ?? [];
  if (!scans.length) return;
  const ms = scans.reduce((a, s) => a + s.ms, 0) / scans.length;
  const gaps = scans.slice(1).map((s, i) => (s.at - scans[i].at) / 1000);
  const every = gaps.length ? gaps.reduce((a, b) => a + b, 0) / gaps.length : null;
  const settingsNow = capture.track.getSettings();
  $('scan-stats').textContent = `Scan ${Math.round(ms)} ms` + (every ? ` · every ${every.toFixed(1)} s` : '')
    + (settingsNow.width ? ` · ${settingsNow.width}×${settingsNow.height}` : '') + (settingsNow.frameRate ? ` @ ${Math.round(settingsNow.frameRate)} fps` : '');
}

async function updateStorageNote(persisted) {
  if (persisted === undefined) persisted = await navigator.storage?.persisted?.();
  $('storage-note').textContent = persisted ? 'This browser has agreed to keep it unless you clear site data.' : '';
}

function broadcast() {
  // The overlay recomputes from IndexedDB; the message only says something changed and for whom.
  channel?.postMessage({type: 'update', characterId: character?.id ?? null});
}

// ---------- HUD preview and manual calibration ----------

let drawing = null;  // 'exp' | 'level' while the user drags a box

function drawPreview() {
  const frame = lastScan?.frame ?? capture?.lastFrame;
  if (!frame) return;
  const canvas = $('hud-canvas'), y0 = Math.floor(frame.height * .6), h = frame.height - y0;
  canvas.width = frame.width; canvas.height = h;
  const context = canvas.getContext('2d');
  context.putImageData(new ImageData(frame.data, frame.width, frame.height), 0, -y0);
  const regions = regionsFor(frame), boxes = regions ? fieldBoxes(frame, regions) : {};
  for (const [key, colour] of [['exp', '#b6e65b'], ['level', '#ffb347']]) {
    const box = regions?.[key];
    if (box) { context.strokeStyle = colour; context.lineWidth = 2; context.setLineDash([5, 4]); context.strokeRect(box.x0, box.y0 - y0, box.x1 - box.x0, box.y1 - box.y0); }
    const tight = boxes[key];
    if (tight) { context.setLineDash([]); context.strokeRect(tight.x0, tight.y0 - y0, tight.x1 - tight.x0, tight.y1 - tight.y0); }
    cropPreview($(`crop-${key}`), frame, tight);
    const raw = lastScan?.raw?.[key]?.map((r) => r.text).join(' | ');
    $(`text-${key}`).textContent = raw || '—';
  }
  canvas.dataset.offset = y0;
}

function cropPreview(canvas, frame, box) {
  if (!box) { canvas.width = canvas.height = 0; return; }
  const w = Math.max(1, Math.round(box.x1 - box.x0)), h = Math.max(1, Math.round(box.y1 - box.y0)), scale = 3;
  const source = new OffscreenCanvas(frame.width, frame.height);
  source.getContext('2d').putImageData(new ImageData(frame.data, frame.width, frame.height), 0, 0);
  canvas.width = w * scale; canvas.height = h * scale;
  const context = canvas.getContext('2d');
  context.imageSmoothingEnabled = false;
  context.drawImage(source, box.x0, box.y0, w, h, 0, 0, w * scale, h * scale);
}

function canvasPoint(event) {
  const canvas = $('hud-canvas'), rect = canvas.getBoundingClientRect();
  return {x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height + Number(canvas.dataset.offset || 0)};
}

function beginDraw(kind) {
  if (!capture?.lastFrame) return;
  drawing = {kind};
  $('hud-view').hidden = false; drawPreview();
  setStatus(kind === 'exp' ? 'Drag a box around the EXP numbers, including the [percent]' : 'Drag a box around the orange level badge', '');
}

function setupDrawing() {
  const canvas = $('hud-canvas');
  canvas.addEventListener('pointerdown', (event) => {
    if (!drawing) return;
    drawing.from = canvasPoint(event); canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!drawing?.from) return;
    drawPreview();
    const to = canvasPoint(event), context = canvas.getContext('2d'), offset = Number(canvas.dataset.offset);
    context.setLineDash([]); context.strokeStyle = '#fff'; context.lineWidth = 2;
    context.strokeRect(drawing.from.x, drawing.from.y - offset, to.x - drawing.from.x, to.y - drawing.from.y);
  });
  canvas.addEventListener('pointerup', async (event) => {
    if (!drawing?.from) return;
    const to = canvasPoint(event), frame = capture?.lastFrame, kind = drawing.kind, from = drawing.from;
    drawing = null;
    if (!frame) return;
    const box = {x0: Math.min(from.x, to.x), y0: Math.min(from.y, to.y), x1: Math.max(from.x, to.x), y1: Math.max(from.y, to.y)};
    if (box.x1 - box.x0 < 6 || box.y1 - box.y0 < 4) return setStatus('That box was too small; try again', 'warn');
    if (kind === 'level' && !orangeBox(frame, box)) return setStatus('No orange level badge inside that box; try again', 'warn');
    const old = settings.calibration && regionsFor(frame) ? settings.calibration : {};
    await saveCalibration({source: 'manual', width: frame.width, height: frame.height, exp: old.exp ?? null, level: old.level ?? null, [kind]: normalize(box, frame)});
    setStatus(kind === 'exp' && !settings.calibration.level ? 'EXP box saved. Now draw the level box (optional but recommended).' : 'HUD boxes saved', 'ok');
    drawPreview();
    if (capture) { clearTimeout(capture.timer); capture.timer = setTimeout(scan, 300); }
  });
}

// ---------- wiring ----------

function pressed(selector, attribute, value) {
  for (const button of document.querySelectorAll(selector)) button.setAttribute('aria-pressed', String(button.dataset[attribute] === String(value)));
}

async function init() {
  $('character-job').replaceChildren(...JOBS.map((j) => new Option(j, j)));
  $('start').addEventListener('click', start);
  $('stop').addEventListener('click', () => stop('stopped'));
  $('character-select').addEventListener('change', (event) => event.target.value === 'new' ? openCharacterForm(true) : selectCharacter(Number(event.target.value)));
  $('character-edit').addEventListener('click', () => openCharacterForm(!character));
  $('character-form').addEventListener('submit', (event) => { event.preventDefault(); saveCharacterForm(false); });
  $('character-new').addEventListener('click', () => saveCharacterForm(true));
  $('character-cancel').addEventListener('click', () => { $('character-form').hidden = true; $('character-select').value = character ? String(character.id) : 'new'; });
  $('character-delete').addEventListener('click', (event) => twoStep(event.currentTarget, 'Delete its history too?', async () => {
    if (capture) await stop('character_deleted');
    await store.deleteCharacter(character.id);
    settings.activeCharacterId = null; $('character-form').hidden = true;
    await refreshCharacters(); broadcast();
  }));
  $('identity-same').addEventListener('click', confirmIdentity);
  $('identity-switch').addEventListener('click', () => { identitySuspect = null; render(); $('character-select').focus(); });
  for (const button of document.querySelectorAll('[data-interval]')) button.addEventListener('click', async () => {
    settings.interval = Number(button.dataset.interval); pressed('[data-interval]', 'interval', settings.interval);
    await store.setSetting('interval', settings.interval);
    if (capture) { clearTimeout(capture.timer); capture.timer = setTimeout(scan, settings.interval * 1000); }
  });
  for (const button of document.querySelectorAll('[data-window]')) button.addEventListener('click', async () => {
    settings.window = button.dataset.window === 'session' ? 'session' : Number(button.dataset.window);
    pressed('[data-window]', 'window', settings.window); await store.setSetting('window', settings.window); render();
  });
  $('popout').addEventListener('click', () => {
    // A separate window from this browser profile shares IndexedDB and BroadcastChannel with this tab.
    window.open('/local/overlay', 'msxp-local-overlay', 'popup,width=520,height=200');
  });
  $('hud-detect').addEventListener('click', async () => {
    if (!capture?.lastFrame || !engine) return;
    const reason = await engine.exclusive(() => detect(capture.lastFrame));
    setStatus(reason ? 'Couldn\'t find the HUD automatically. Draw the boxes in the preview.' : 'Found the HUD', reason ? 'warn' : 'ok');
    if (!$('hud-view').hidden) drawPreview();
  });
  $('hud-preview').addEventListener('click', () => { const view = $('hud-view'); view.hidden = !view.hidden; $('hud-preview').textContent = view.hidden ? 'Show preview' : 'Hide preview'; if (!view.hidden) drawPreview(); });
  $('hud-draw-exp').addEventListener('click', () => beginDraw('exp'));
  $('hud-draw-level').addEventListener('click', () => beginDraw('level'));
  $('export').addEventListener('click', async () => {
    const blob = new Blob([JSON.stringify(await store.exportAll(), null, 1)], {type: 'application/json'});
    const link = Object.assign(document.createElement('a'), {href: URL.createObjectURL(blob), download: `msxp-local-${new Date().toISOString().slice(0, 10)}.json`});
    link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });
  $('clear').addEventListener('click', (event) => twoStep(event.currentTarget, 'Click again to delete everything', async () => {
    if (capture) await stop('cleared');
    await store.clearAll();
    settings = {interval: settings.interval, window: settings.window, calibration: null, activeCharacterId: null, glyphs: null};
    character = null; readingsCache = [];
    await refreshCharacters(); broadcast(); setStatus('Local history cleared');
  }));
  setupDrawing();
  if (debug) setupDebug();

  try {
    await loadTable();
    if (!await lockHeldElsewhere()) await store.closeAbandoned();
    for (const key of ['interval', 'window', 'calibration', 'activeCharacterId', 'glyphs']) {
      const value = await store.getSetting(key);
      if (value !== undefined) settings[key] = value;
    }
    if (!INTERVALS.includes(settings.interval)) settings.interval = 20;
    pressed('[data-interval]', 'interval', settings.interval); pressed('[data-window]', 'window', settings.window);
    await refreshCharacters();
    updateStorageNote();
  } catch (error) {
    setStatus(`Local storage is unavailable: ${error.message}`, 'warn');
    $('start').disabled = true;
  }
  setInterval(render, 5000);
}

// Destructive actions use a second click instead of a blocking dialog.
function twoStep(button, prompt, action) {
  if (button.dataset.armed) { delete button.dataset.armed; button.textContent = button.dataset.label; return action(); }
  button.dataset.label = button.textContent; button.dataset.armed = '1'; button.textContent = prompt;
  setTimeout(() => { if (button.dataset.armed) { delete button.dataset.armed; button.textContent = button.dataset.label; } }, 5000);
}

// ?debug: save the bottom of the last frame to a local file for diagnosing OCR. Never automatic.
function setupDebug() {
  const button = Object.assign(document.createElement('button'), {type: 'button', textContent: 'Save HUD strip (debug)'});
  button.addEventListener('click', async () => {
    const frame = capture?.lastFrame; if (!frame) return;
    const y0 = Math.floor(frame.height * .78), canvas = new OffscreenCanvas(frame.width, frame.height - y0);
    canvas.getContext('2d').putImageData(new ImageData(frame.data, frame.width, frame.height), 0, -y0);
    const link = Object.assign(document.createElement('a'), {href: URL.createObjectURL(await canvas.convertToBlob()), download: `msxp-hud-${frame.width}x${frame.height}-${Date.now()}.png`});
    link.click();
  });
  document.querySelector('.hud-actions').append(button);
  window.msxpLocal = {get lastScan() { return lastScan && {...lastScan, frame: undefined}; }, get capture() { return capture; }, get settings() { return settings; }, get engine() { return engine; }};
}

init();

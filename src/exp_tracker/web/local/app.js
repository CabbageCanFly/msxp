// /local: capture the game window the user shares, read the HUD every few seconds, track locally.
// No network requests besides this site's own static files; nothing leaves the browser.
import * as store from './store.js';
import {acceptBaseline, maxGapFor, resolveLevel, step, suspicious} from './exp.js';
import {denormalize, locate, normalize, orangeBox} from './hud.js';
import {fieldBoxes, readHud, readIdentity} from './reader.js';
import {displayed, learn, learnLetters} from './glyphs.js';
import {CHANNEL, JOBS, OVERLAY_CHOICES, OVERLAY_COLORS, OVERLAY_SIZES, THEME_COLORS, WINDOWS, duration, exp as fmtExp, jobIcon, overlayOptions,
  overlayQuery, percent, randomOverlayColors, summarize} from './view.js';
import {drawDailyChart, drawExpChart, drawPercentChart, expText, hideTip} from './charts.js';

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
let settings = {interval: 20, window: 15, calibration: null, activeCharacterId: null, glyphs: null, letters: {}};
let character = null, readingsCache = [], daysCache = [];
// Chart and overlay-builder choices, as on the live character page (kept for this page view only).
const charts = {mode: 'exp', bucket: 300, chartWindow: 60, longWindow: 1440, lineWindow: 15, days: 30, levelOnly: false};
const builder = overlayOptions('');
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
  readingsCache = character ? await store.readings(character.id, Date.now() - store.DETAIL_MS) : [];
  daysCache = character ? await store.days(character.id) : [];
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
  const id = await store.saveCharacter(isNew ? {name, job, nameSource: 'user'} : {...character, name, job, ...(name !== character.name ? {nameSource: 'user'} : {})});
  // A typed rename is the truth about the on-screen name: it teaches those letters for future names.
  if (!isNew && name !== character.name) await teachLetters(character.nameGlyphs, name, true);
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
  capture.pruneTimer = setInterval(() => store.prune().catch(() => {}), 3600e3);
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
  clearTimeout(current.timer); clearInterval(current.pruneTimer);
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

// The latest frame, or only a band of rows (the HUD) when its boxes are known: copying 1368x60 pixels
// instead of 1368x800 is what makes one-second scans cheap. `top` and `full` map band rows to the window.
async function grab(band = null) {
  const {grabber, video} = capture;
  let source, w, h;
  if (grabber) {
    // A minimized window may stop producing frames; don't wait forever.
    source = await Promise.race([grabber.grabFrame(), new Promise((_, reject) => setTimeout(() => reject(new Error('no_frame')), 4000))]);
    w = source.width; h = source.height;
  } else {
    if (!video.videoWidth) throw new Error('no_frame');
    source = video; w = video.videoWidth; h = video.videoHeight;
  }
  const top = band ? Math.max(0, Math.min(h - 1, Math.floor(band.y0))) : 0;
  const rows = band ? Math.max(1, Math.min(h, Math.ceil(band.y1)) - top) : h;
  const canvas = capture.canvas ??= new OffscreenCanvas(1, 1);
  if (canvas.width !== w || canvas.height !== rows) { canvas.width = w; canvas.height = rows; }
  const context = canvas.getContext('2d', {willReadFrequently: true});
  context.drawImage(source, 0, top, w, rows, 0, 0, w, rows);
  source.close?.();
  const frame = context.getImageData(0, 0, w, rows);
  return {width: w, height: rows, data: frame.data, top, full: {width: w, height: h}};
}

const isFull = (frame) => frame && frame.top === 0 && frame.height === frame.full.height;

// Calibrated boxes in window pixels for a window of this size, or null (none, or another aspect ratio).
function regionsFor(size) {
  const c = settings.calibration;
  if (!c || !c.exp || !size) return null;
  // Normalized boxes follow a resized window only when the aspect ratio is unchanged.
  if (Math.abs(c.width / c.height - size.width / size.height) > .01) return null;
  return {exp: denormalize(c.exp, size), level: c.level && denormalize(c.level, size)};
}

// Boxes in the coordinates of a (possibly banded) frame.
const shifted = (regions, top) => top ? Object.fromEntries(Object.entries(regions).map(([k, b]) => [k, b && {...b, y0: b.y0 - top, y1: b.y1 - top}])) : regions;

// Rows to copy: the EXP and level boxes, plus room for the name/job panel above and below the badge.
function bandFor(regions, size) {
  const boxes = [regions.exp, regions.level].filter(Boolean), margin = Math.max(12, size.height * .02);
  return {y0: Math.min(...boxes.map((b) => b.y0)) - margin, y1: Math.max(...boxes.map((b) => b.y1)) + margin};
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
    const known = regionsFor(current.full);
    const redetect = !known || (current.failures >= 3 && settings.calibration?.source === 'auto' && Date.now() - current.lastDetect > 60e3);
    // Full frames for detection and the preview; otherwise only the HUD rows.
    const banded = Boolean(known) && !redetect && $('hud-view').hidden && !drawing;
    const frame = await grab(banded ? bandFor(known, current.full) : null);
    if (capture !== current) return;
    const resized = current.full && (frame.full.width !== current.full.width || frame.full.height !== current.full.height);
    current.full = frame.full; current.lastFrame = frame;
    if (resized && banded) { current.burst = Math.max(current.burst || 0, 1); return; }  // Re-measure with a full frame.
    outcome = await engine.exclusive(async () => {
      let regions = regionsFor(frame.full);
      if (!banded && (redetect && settings.calibration?.source !== 'manual' || !regions)) {
        const reason = await detect(frame);
        regions = regionsFor(frame.full);
        if (!regions) return {status: 'no_hud', reason: reason ?? 'hud_not_found'};
      }
      return readHud(engine, frame, shifted(regions, frame.top), templatesFor(frame));
    });
    if (!outcome) return;  // A previous scan is still running; never queue another.
    if (capture !== current) return;
    outcome.frameWidth = frame.full.width; outcome.frameHeight = frame.full.height;
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
      // A burst re-scans after a second to confirm a change quickly; otherwise the chosen interval.
      const delay = current.burst > 0 ? (current.burst--, 1000) : Math.max(500, settings.interval * 1000 - ms);
      current.timer = setTimeout(scan, delay);
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
  name_confirming: 'A different name is on screen. Checking…',
};

const templatesFor = (frame) => settings.glyphs?.size === `${frame.full.width}x${frame.full.height}` ? settings.glyphs.templates : null;

async function teachLetters(keys, text, authoritative = false) {
  const letters = {...settings.letters};
  if (!learnLetters(letters, keys, text, {authoritative})) return;
  settings.letters = letters;
  await store.setSetting('letters', letters);
}

/**
 * Who is on screen, by exact name bitmap. A new bitmap must repeat on three scans a second apart. It
 * then switches to the character with that bitmap, gives a not-yet-named character its bitmap (if the
 * reading fits its history), or creates a character from the name OCR read. Returns a status to stop
 * this scan, or null to continue tracking the (possibly same) character.
 */
async function identify(current, outcome, at) {
  const id = outcome.identity;
  if (!id?.nameKey) return null;
  if (character.nameKey === id.nameKey) {
    current.nameStreak = null;
    // Remember the name's glyphs, so a later rename can teach its letters.
    if (!character.nameGlyphs && id.nameGlyphs) character = await store.getCharacter(await store.saveCharacter({...character, nameGlyphs: id.nameGlyphs}));
    // A name read by OCR (never one the player typed) is re-read once per session with the current
    // reader and learned letters; a same-length correction replaces the old label.
    if (character.nameSource !== 'user' && current.nameChecked !== character.id) {
      current.nameChecked = character.id;
      const who = await readIdentity(engine, current.lastFrame, {name: outcome.boxes.name}, templatesFor(current.lastFrame), JOBS, settings.letters);
      if (who.name && who.name !== character.name && who.name.length === character.name.length) {
        character = await store.getCharacter(await store.saveCharacter({...character, name: who.name, nameSource: 'ocr'}));
        await refreshCharacters(); broadcast();
      }
    }
    if (id.jobKey && character.jobKey !== id.jobKey) {
      current.jobStreak = current.jobStreak?.key === id.jobKey ? {key: id.jobKey, count: current.jobStreak.count + 1} : {key: id.jobKey, count: 1};
      if (current.jobStreak.count >= 2) {
        current.jobStreak = null;
        const who = await readIdentity(engine, current.lastFrame, {job: outcome.boxes.job}, null, JOBS);
        if (who.job) await teachLetters(id.jobGlyphs, who.job);
        character = await store.saveCharacter({...character, jobKey: id.jobKey, ...(who.job ? {job: who.job} : {})}).then(store.getCharacter);
        await refreshCharacters(); broadcast();
      } else current.burst = Math.max(current.burst || 0, 1);
    }
    return null;
  }
  // A logout, loading screen or fade can show a half-drawn panel next to the old EXP bar: such a scan
  // never counts toward a change (and is not tracked either).
  const evidence = resolveLevel(table, outcome.level, outcome.exp, outcome.bp, null).evidence;
  if (evidence !== 'ocr_and_table' && evidence !== 'ocr_only') { current.nameStreak = null; current.burst = Math.max(current.burst || 0, 1); return 'name_confirming'; }
  current.nameStreak = current.nameStreak?.key === id.nameKey ? {key: id.nameKey, count: current.nameStreak.count + 1} : {key: id.nameKey, count: 1};
  if (current.nameStreak.count < 3) { current.burst = Math.max(current.burst || 0, 1); return 'name_confirming'; }
  current.nameStreak = null;
  const all = await store.characters(), match = all.find((c) => c.nameKey === id.nameKey);
  if (match) { await selectCharacter(match.id); setStatus(`Switched to ${match.name}`, 'ok'); return 'character_switched'; }
  const who = await readIdentity(engine, current.lastFrame, outcome.boxes, templatesFor(current.lastFrame), JOBS, settings.letters);
  if (who.job) await teachLetters(id.jobGlyphs, who.job);
  const resolved = resolveLevel(table, outcome.level, outcome.exp, outcome.bp, null), reading = {at, level: resolved.level, exp: outcome.exp, bp: outcome.bp};
  const fits = !character.last || (resolved.level !== null && !suspicious(character.last, reading));
  if (!character.nameKey && fits) {
    // The character being tracked had no name bitmap yet: this is it.
    character = await store.getCharacter(await store.saveCharacter({...character, nameKey: id.nameKey, nameGlyphs: id.nameGlyphs, jobKey: id.jobKey,
      ...(who.name ? {name: who.name, nameSource: 'ocr'} : {}), ...(who.job ? {job: who.job} : {})}));
    await refreshCharacters(); broadcast();
    return null;
  }
  // Identity is the bitmap; an unreadable name only means a placeholder label the player can rename.
  const name = who.name ?? `Character ${all.length + 1}`;
  const created = await store.saveCharacter({name, nameSource: who.name ? 'ocr' : 'placeholder', job: who.job ?? 'Beginner', nameKey: id.nameKey, nameGlyphs: id.nameGlyphs, jobKey: id.jobKey});
  await selectCharacter(created); setStatus(who.name ? `New character: ${name}` : `New character (name unreadable, rename it): ${name}`, 'ok');
  return 'character_switched';
}

async function handle(current, outcome, at) {
  let status = outcome.status, reason = outcome.reason, accepted = [];
  const switched = status === 'ok' ? await identify(current, outcome, at) : null;
  if (switched === 'character_switched' || capture !== current) { render(); return; }
  if (switched) { status = 'identity_pending'; reason = switched; }
  if (status === 'ok') {
    const previous = current.tracker.last?.level ?? current.tracker.pending?.level ?? null;
    const resolved = resolveLevel(table, outcome.level, outcome.exp, outcome.bp, previous);
    if (resolved.level === null) { status = 'rejected'; reason = resolved.reason; }
    else {
      const trustedIdentity = Boolean(character.nameKey && outcome.identity?.nameKey === character.nameKey);
      const result = step(table, current.tracker, {at, level: resolved.level, exp: outcome.exp, bp: outcome.bp}, {maxGapSeconds: maxGapFor(settings.interval), trustedIdentity});
      current.tracker = result.state; accepted = result.accept; status = result.status; reason = result.reason;
      if (status === 'pending') current.burst = Math.max(current.burst || 0, 1);  // Confirm a second later.
      if (status === 'identity_check') identitySuspect = result.suspect;
    }
  }
  // Table-rejected readings count too: a box that clips digits reads 'cleanly' but never matches.
  current.failures = ['accepted', 'pending', 'identity_check', 'identity_pending'].includes(status) ? 0 : current.failures + 1;
  await store.record(character.id, current.sessionId, accepted, current.tracker, status);
  if (status === 'accepted') await teach(outcome);
  if (accepted.length) {
    character = await store.getCharacter(character.id);
    readingsCache.push(...accepted.map((r) => ({...r, characterId: character.id, sessionId: current.sessionId})));
    readingsCache = readingsCache.filter((r) => r.at >= Date.now() - store.DETAIL_MS);
    daysCache = await store.days(character.id);
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
  const text = displayed(outcome.exp, outcome.bp), templates = {...glyphs.templates}, last = capture?.tracker.last;
  let added = 0;
  if (outcome.source === 'ocr' && outcome.segments) added += (learn(templates, outcome.segments.number, text.number) ?? 0) + (learn(templates, outcome.segments.percent, text.percent) ?? 0);
  // Level digits too, once the accepted level is the one the badge showed.
  if (outcome.levelSource === 'ocr' && outcome.levelSegments && last?.level === outcome.level) added += learn(templates, outcome.levelSegments, String(outcome.level)) ?? 0;
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
  const view = summarize(table, character, readingsCache, now, settings.window, {sessionId: capture?.sessionId ?? null, levelOnly: charts.levelOnly, live: Boolean(capture)});
  $('player-name').textContent = character?.name || 'Your character';
  $('player-job').hidden = !character?.job;
  if (character?.job) { $('player-job-icon').src = jobIcon(character.job); $('player-job-name').textContent = character.job; }
  $('level').textContent = view.last ? `Lv. ${view.last.level}` : 'Lv. —';
  $('progress').value = view.progress;
  $('exp').textContent = view.last ? fmtExp(view.last.exp) : '—';
  $('percentage').textContent = view.last ? ` [${percent(view.last.bp)}]` : '';
  $('age').textContent = view.last ? `· last reading ${duration(view.age)} ago` : '';
  $('rate').textContent = view.perHour == null ? '—' : fmtExp(view.perHour);
  $('rate-label').textContent = `EXP / hour · ${settings.window} min`;
  $('rate-note').textContent = view.perHour == null ? 'Needs a few minutes of readings'
    : (view.early ? `So far · ${duration(view.covered)} observed` : '') + (view.percentPerHour != null ? `${view.early ? ' · ' : ''}${view.percentPerHour.toFixed(2)}% / hour` : '');
  $('movement').textContent = view.recent == null ? '—' : fmtExp(view.recent);
  $('tracked-exp').textContent = view.dayGain == null ? '—' : expText(view.dayGain);
  $('tracked-note').textContent = view.dayGain == null ? `${expText(view.totalGain)} EXP tracked on this device` : `${duration(view.dayCovered)} observed · ${expText(view.totalGain)} all time`;
  $('eta').textContent = view.eta == null ? '—' : duration(view.eta);
  $('eta-note').textContent = view.eta == null ? (view.last && !view.total ? 'No EXP table for this level' : 'Needs an EXP / hour') : `${fmtExp(view.total - view.last.exp)} EXP to go`;
  $('identity').hidden = !identitySuspect;
  if (identitySuspect) {
    const ref = capture?.tracker.last ?? capture?.tracker.reference;
    $('identity-text').textContent = `The game shows Lv. ${identitySuspect.level} at ${percent(identitySuspect.bp)}, but ${character.name} was last Lv. ${ref?.level} at ${percent(ref?.bp)}. Readings are paused so histories don't mix.`;
  }
  drawHistory(view, now);
}

// The live character page's chart panel: EXP bars, Level % line, or daily History.
function drawHistory(view, now = Date.now()) {
  const svg = $('history-chart'), daily = charts.mode === 'daily', long = charts.bucket === 1800;
  pressed('[data-chart]', 'chart', charts.mode); pressed('[data-bucket]', 'bucket', charts.bucket);
  pressed('[data-line-window]', 'lineWindow', charts.lineWindow); pressed('[data-daily-days]', 'dailyDays', charts.days);
  for (const button of document.querySelectorAll('[data-chart-window]')) {
    const minutes = Number(button.dataset.chartWindow);
    button.disabled = (minutes >= 720) !== long;
    button.setAttribute('aria-pressed', String(!button.disabled && minutes === (long ? charts.longWindow : charts.chartWindow)));
  }
  $('history-controls').hidden = daily; $('daily-controls').hidden = !daily;
  $('bucket-controls').hidden = charts.mode !== 'exp'; $('line-controls').hidden = charts.mode !== 'percentage';
  let note = '';
  if (charts.mode === 'exp') note = drawExpChart(svg, view.intervals, {anchor: now, seconds: charts.bucket, range: (long ? charts.longWindow : charts.chartWindow) * 60});
  else if (charts.mode === 'percentage') {
    const points = charts.levelOnly && view.last ? readingsCache.filter((r) => r.level === view.last.level) : readingsCache;
    note = drawPercentChart(svg, points, {anchor: now, minutes: charts.lineWindow});
  } else drawDailyChart(svg, daysCache, {now, range: charts.days});
  $('history-note').textContent = daily ? `One point per day: your last reading that day · ${daysCache.length} day${daysCache.length === 1 ? '' : 's'} saved` : note;
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
  if (!isFull(frame)) { if (capture) { clearTimeout(capture.timer); capture.timer = setTimeout(scan, 50); } return; }
  const canvas = $('hud-canvas'), y0 = Math.floor(frame.height * .6), h = frame.height - y0;
  canvas.width = frame.width; canvas.height = h;
  const context = canvas.getContext('2d');
  context.putImageData(new ImageData(frame.data, frame.width, frame.height), 0, -y0);
  const regions = regionsFor(frame.full), boxes = regions ? fieldBoxes(frame, regions) : {};
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
  if (!capture) return;
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
    if (!isFull(frame)) return setStatus('The preview was still updating; try again', 'warn');
    const box = {x0: Math.min(from.x, to.x), y0: Math.min(from.y, to.y), x1: Math.max(from.x, to.x), y1: Math.max(from.y, to.y)};
    if (box.x1 - box.x0 < 6 || box.y1 - box.y0 < 4) return setStatus('That box was too small; try again', 'warn');
    if (kind === 'level' && !orangeBox(frame, box)) return setStatus('No orange level badge inside that box; try again', 'warn');
    const old = settings.calibration && regionsFor(frame.full) ? settings.calibration : {};
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
    settings.window = Number(button.dataset.window);
    pressed('[data-window]', 'window', settings.window); await store.setSetting('window', settings.window); render();
  });
  $('current-level-only').addEventListener('change', (event) => { charts.levelOnly = event.target.checked; render(); });
  setupCharts();
  setupBuilder();
  $('hud-detect').addEventListener('click', async () => {
    if (!isFull(capture?.lastFrame) || !engine) { $('hud-view').hidden = false; drawPreview(); return setStatus('Getting a full frame; press again in a moment', ''); }
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
    settings = {interval: settings.interval, window: settings.window, calibration: null, activeCharacterId: null, glyphs: null, letters: {}};
    character = null; readingsCache = [];
    await refreshCharacters(); broadcast(); setStatus('Local history cleared');
  }));
  setupDrawing();
  if (debug) setupDebug();

  try {
    await loadTable();
    if (!await lockHeldElsewhere()) await store.closeAbandoned();
    for (const key of ['interval', 'window', 'calibration', 'activeCharacterId', 'glyphs', 'letters']) {
      const value = await store.getSetting(key);
      if (value !== undefined) settings[key] = value;
    }
    if (!INTERVALS.includes(settings.interval)) settings.interval = 20;
    if (!WINDOWS.includes(settings.window)) settings.window = 15;
    pressed('[data-interval]', 'interval', settings.interval); pressed('[data-window]', 'window', settings.window);
    Object.assign(builder, overlayOptions((await store.getSetting('overlay')) ?? ''));
    await refreshCharacters();
    updateBuilder();
    store.prune().catch(() => {});
    updateStorageNote();
  } catch (error) {
    setStatus(`Local storage is unavailable: ${error.message}`, 'warn');
    $('start').disabled = true;
  }
  setInterval(render, 5000);
}

function setupCharts() {
  const on = (selector, handler) => { for (const button of document.querySelectorAll(selector)) button.addEventListener('click', () => { if (button.disabled) return; handler(button); hideTip(); render(); updateBuilder(); }); };
  on('[data-chart]', (b) => { charts.mode = b.dataset.chart; });
  on('[data-bucket]', (b) => { charts.bucket = Number(b.dataset.bucket); });
  on('[data-chart-window]', (b) => { const minutes = Number(b.dataset.chartWindow); if (charts.bucket === 1800) charts.longWindow = minutes; else charts.chartWindow = minutes; });
  on('[data-line-window]', (b) => { charts.lineWindow = Number(b.dataset.lineWindow); });
  on('[data-daily-days]', (b) => { charts.days = Number(b.dataset.dailyDays); });
  window.addEventListener('scroll', hideTip, true);
  window.addEventListener('resize', () => render());
}

// The live overlay builder: options, presets and colours, previewed in place. "Open pop-out" opens a
// window of this browser profile at the overlay's size, for OBS Window Capture.
function overlayURL() { const query = overlayQuery(builder); return `/local/overlay${query ? '?' + query : ''}`; }
function updateBuilder() {
  builder.interval = String(charts.bucket); builder.range = String(charts.bucket === 1800 ? charts.longWindow : charts.chartWindow);
  const url = overlayURL(), [width, height] = OVERLAY_SIZES[builder.layout], frame = $('overlay-preview');
  $('overlay-url').value = location.origin + url; $('overlay-link').href = url; $('overlay-size').textContent = `Window · ${width} × ${height}`;
  for (const button of document.querySelectorAll('[data-option] button')) {
    const key = button.closest('[data-option]').dataset.option;
    button.setAttribute('aria-pressed', String(builder[key] === button.dataset.value && (key !== 'theme' || !OVERLAY_COLORS.some((color) => builder[color]))));
  }
  for (const input of document.querySelectorAll('[data-color]')) input.value = '#' + (builder[input.dataset.color] ?? THEME_COLORS[builder.theme][input.dataset.color]);
  frame.width = width; frame.height = height; scalePreview();
  if (frame.dataset.loaded) frame.contentWindow?.applyOverlay?.({...builder}); else if (!frame.src) frame.src = url;
}
function scalePreview() {
  const frame = $('overlay-preview'), scale = Math.min(1, (($('overlay-stage').clientWidth || 524) - 26) / frame.width);
  frame.style.transform = `scale(${scale})`; $('overlay-stage').style.height = `${Math.ceil(frame.height * scale) + 26}px`;
}
const saveBuilder = () => store.setSetting('overlay', overlayQuery(builder)).catch(() => {});
function setupBuilder() {
  const frame = $('overlay-preview');
  frame.addEventListener('load', () => { frame.dataset.loaded = 'true'; frame.contentWindow?.applyOverlay?.({...builder}); });
  for (const button of document.querySelectorAll('[data-option] button')) button.addEventListener('click', () => {
    const key = button.closest('[data-option]').dataset.option;
    if (!OVERLAY_CHOICES[key]?.includes(button.dataset.value)) return;
    if (key === 'theme') for (const color of OVERLAY_COLORS) delete builder[color];
    builder[key] = button.dataset.value; saveBuilder(); updateBuilder();
  });
  for (const input of document.querySelectorAll('[data-color]')) input.addEventListener('input', () => { builder[input.dataset.color] = input.value.slice(1).toLowerCase(); saveBuilder(); updateBuilder(); });
  $('overlay-randomize').addEventListener('click', () => { for (const key of OVERLAY_COLORS) delete builder[key]; Object.assign(builder, {theme: 'night'}, randomOverlayColors()); saveBuilder(); updateBuilder(); });
  $('overlay-reset').addEventListener('click', () => { for (const key of OVERLAY_COLORS) delete builder[key]; saveBuilder(); updateBuilder(); });
  $('popout').addEventListener('click', () => {
    // A separate window of this browser profile shares IndexedDB and BroadcastChannel with this tab.
    const [width, height] = OVERLAY_SIZES[builder.layout];
    window.open(overlayURL(), 'msxp-local-overlay', `popup,width=${width},height=${height}`);
  });
  window.addEventListener('resize', scalePreview);
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
    const frame = capture?.lastFrame; if (!isFull(frame)) return;
    const y0 = Math.floor(frame.height * .78), canvas = new OffscreenCanvas(frame.width, frame.height - y0);
    canvas.getContext('2d').putImageData(new ImageData(frame.data, frame.width, frame.height), 0, -y0);
    const link = Object.assign(document.createElement('a'), {href: URL.createObjectURL(await canvas.convertToBlob()), download: `msxp-hud-${frame.width}x${frame.height}-${Date.now()}.png`});
    link.click();
  });
  document.querySelector('.hud-actions').append(button);
  window.msxpLocal = {get lastScan() { return lastScan && {...lastScan, frame: undefined}; }, get capture() { return capture; }, get settings() { return settings; }, get engine() { return engine; }};
}

init();

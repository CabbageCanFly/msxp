// /local: capture the game window the user shares, read the HUD every few seconds, track locally.
// No network requests besides this site's own static files; nothing leaves the browser.
import * as store from './store.js';
import {acceptBaseline, maxGapFor, resolveLevel, step, suspicious} from './exp.js';
import {denormalize, locate, normalize, orangeBox} from './hud.js';
import {fieldBoxes, readHud, readIdentity} from './reader.js';
import {HUD_GLYPHS, displayed, learn, learnLetters} from './glyphs.js';
import {GAME_WIDTH, captureScale, unstretch} from './pickups.js';
import {CHANNEL, JOBS, OVERLAY_CHOICES, OVERLAY_COLORS, THEME_COLORS, WINDOWS, overlaySize, duration, exp as fmtExp, jobIcon, overlayOptions,
  overlayQuery, percent, randomOverlayColors, summarize, summarizePickups, trackedBetween} from './view.js';
import {drawDailyChart, drawExpChart, drawPercentChart, expText, hideTip, setTimeZone, timeZone} from './charts.js';
import {loadItems, regionBox, startPickups} from './pickup-session.js';
import {seedFont} from './message-font.js';
import {setScenery} from './scenery.js';
import {liveChart, rateSeries, smooth} from './live-chart.js';

const $ = (id) => document.getElementById(id);
const INTERVALS = [1, 5, 10, 20, 30];
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
// glyphs: templates learned from confirmed readings, per window size ({'1368x800': templates}): another size
// draws other pixels, and a size used before reads at once again. pickupFont: the same for pickup messages
// (fonts saved as messageFont, learned before the word alignment, held misread shapes and are not loaded).
let settings = {interval: 1, window: 5, calibration: null, activeCharacterId: null, glyphs: null, letters: {}, pickups: true, scenery: true, liveKind: 'exp', liveWindow: 5, mesoWindow: 5, mesoTotalWindow: 1440, itemWindow: 1440, itemKind: 'all', pickupFont: null};
let character = null, readingsCache = [], daysCache = [], pickupsCache = [], itemIcons = null;
// Chart and overlay-builder choices, as on the live character page (kept for this page view only).
const charts = {mode: 'exp', bucket: 60, chartWindow: 60, longWindow: 1440, lineWindow: 15, days: 30, levelOnly: false};
const builder = overlayOptions('');
// Capture session state; only exists while the user is sharing a window.
let capture = null;  // {stream, track, grabber, video, sessionId, tracker, timer, lastFrame, ...}
let lastScan = null, identitySuspect = null;
let plannerState = {};  // Level, EXP and EXP / hour last shown, for the level planner (level-plan.js).

async function loadTable() {
  const response = await fetch('/static/local/community-exp.json');
  if (!response.ok) throw new Error('EXP table unavailable');
  table = await response.json();
}

function getEngine() {
  return enginePromise ??= import('./ocr.js').then((m) => m.createEngine()).then((e) => (engine = e))
    .catch((error) => { enginePromise = null; throw error; });
}

// Pickup reading has its own OCR worker, made when first needed: EXP scans then never wait for a pickup
// read, nor pickup reads for scans.
let pickupEnginePromise = null;
const getPickupEngine = () => pickupEnginePromise ??= import('./ocr.js').then((m) => m.createEngine())
  .catch((error) => { pickupEnginePromise = null; throw error; });

// ---------- characters ----------

async function refreshCharacters() {
  const list = (await store.characters()).sort((a, b) => a.name.localeCompare(b.name));
  const select = $('character-select');
  select.replaceChildren(...list.map((c) => new Option(c.name, c.id)), new Option('+ New character…', 'new'));
  character = list.find((c) => c.id === settings.activeCharacterId) ?? list[0] ?? null;
  // A fallback (the saved one is gone, e.g. after an import) is saved too: the overlays follow the saved one.
  if ((character?.id ?? null) !== (settings.activeCharacterId ?? null)) {
    settings.activeCharacterId = character?.id ?? null; await store.setSetting('activeCharacterId', settings.activeCharacterId);
  }
  select.value = character ? String(character.id) : 'new';
  readingsCache = character ? await store.readings(character.id, Date.now() - store.DETAIL_MS) : [];
  daysCache = character ? await store.days(character.id) : [];
  pickupsCache = character ? await store.pickups(character.id, Date.now() - store.DETAIL_MS) : [];
  render();
}

// The Edit popup: the character's name and job, and removing tracked data between two times.
function openCharacterForm(isNew) {
  const form = $('character-form');
  form.dataset.mode = isNew ? 'new' : 'edit';
  $('editor-title').textContent = isNew ? 'New character' : 'Edit';
  $('remove-tracked').hidden = isNew || !character;
  if (!isNew && character) resetRemoval();
  if (!$('editor').matches(':popover-open')) $('editor').showPopover();
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
  $('editor').hidePopover();
  await selectCharacter(id);
}

async function selectCharacter(id) {
  if (capture && character && character.id !== id) await restartSession('character_switch', id);
  settings.activeCharacterId = id; await store.setSetting('activeCharacterId', id);
  identitySuspect = null;
  await refreshCharacters();
  broadcast();
}

// ---------- removing tracked data ----------

// datetime-local inputs hold local time to the minute; "To" covers its whole minute.
const localInput = (at) => new Date(at - new Date(at).getTimezoneOffset() * 60e3).toISOString().slice(0, 16);
const KINDS = ['exp', 'mesos', 'items'];

function resetRemoval() {
  const now = Date.now();
  $('remove-from').value = localInput(now - 15 * 60e3); $('remove-to').value = localInput(now);
  const own = new Intl.DateTimeFormat('en-US', {timeZoneName: 'short'}).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value;
  $('remove-zone').textContent = `${own ?? 'local time'} · ${Intl.DateTimeFormat().resolvedOptions().timeZone}`;
  for (const kind of KINDS) $(`remove-${kind}`).checked = false;
  renderRemoval();
}

// Each kind is offered only when something of it was tracked in the range.
function renderRemoval() {
  const from = new Date($('remove-from').value).getTime(), to = new Date($('remove-to').value).getTime() + 59999;
  const found = from <= to ? trackedBetween(readingsCache, pickupsCache, from, to, daysCache, Date.now() - store.DETAIL_MS) : {expReadings: 0, oldDays: [], mesoPickups: 0, items: []};
  const old = found.oldDays.length;
  $('remove-exp-row').hidden = !found.expReadings && !old;
  $('remove-exp-text').textContent = `EXP · ${fmtExp(found.exp)}${old ? ` (incl. ${old} older day${old === 1 ? '' : 's'} of history)` : ''}`;
  $('remove-mesos-row').hidden = !found.mesoPickups;
  $('remove-mesos-text').textContent = `Mesos · ${fmtExp(found.mesos)} from ${found.mesoPickups} pickup${found.mesoPickups === 1 ? '' : 's'}`;
  $('remove-items-row').hidden = !found.items.length;
  $('remove-items-text').textContent = `Items · ${found.items.map((item) => `${item.name} ×${item.count}`).join(', ')}`;
  $('remove-empty').hidden = Boolean(found.expReadings || old || found.mesoPickups || found.items.length);
  const chosen = KINDS.filter((kind) => !$(`remove-${kind}-row`).hidden && $(`remove-${kind}`).checked);
  $('remove-apply').disabled = !chosen.length;
  return {from, to, chosen, oldDays: found.oldDays.map((d) => d.day)};
}

async function applyRemoval() {
  const {from, to, chosen, oldDays} = renderRemoval();
  if (!character || !chosen.length) return;
  await store.removeTracked(character.id, from, to, {...Object.fromEntries(chosen.map((kind) => [kind, true])), oldDays});
  await refreshCharacters(); broadcast();
  for (const kind of KINDS) $(`remove-${kind}`).checked = false;
  renderRemoval();
  setStatus(`Removed tracked ${chosen.join(' and ').replace('exp', 'EXP')} from ${$('remove-from').value.replace('T', ' ')} to ${$('remove-to').value.replace('T', ' ')}`, 'ok');
}

// ---------- capture ----------

let starting = false;
async function start() {
  if (capture || starting) return;
  if (!navigator.mediaDevices?.getDisplayMedia) return setStatus('This browser cannot share a window. Use Chrome or Edge on a computer.', 'warn');
  // Firefox lists the game window but captures it black (hardware-drawn windows; reported 2026-11-13), and has no
  // MediaStreamTrackProcessor for pickups: say so rather than track nothing.
  if (/firefox/i.test(navigator.userAgent)) return setStatus(`Firefox shows the game window as black, so it can't be read. Try a different browser.`, 'warn');
  // Safari allows the sharing dialog only straight from the click: ask before any await (reported 2026-11-13).
  const sharing = navigator.mediaDevices.getDisplayMedia({
    // A low frame rate is only a request; scans sample the latest frame on their own schedule.
    video: {displaySurface: 'window', frameRate: {ideal: 5, max: 5}, cursor: 'never'},
    audio: false, selfBrowserSurface: 'exclude', surfaceSwitching: 'include', preferCurrentTab: false,
  });
  starting = true;
  setStatus('Choose the MapleStory window in the sharing dialog…');
  let stream;
  try {
    if (!await acquireLock()) {
      sharing.then((s) => s.getTracks().forEach((t) => t.stop()), () => {});
      return setStatus('Tracking is already running in another msxp tab or window.', 'warn');
    }
    try {
      stream = await sharing;
    } catch (error) {
      releaseLock?.(); releaseLock = null;
      return setStatus(error.name === 'NotAllowedError' ? 'Sharing was cancelled' : `Could not share: ${error.message}`, 'warn');
    }
    // No character yet: an unnamed one, named from the screen by its first readings (identify adopts the first
    // name bitmap and reads the name and job). Typing a name stays possible under Edit.
    if (!character) {
      settings.activeCharacterId = await store.saveCharacter({name: 'New character', nameSource: 'placeholder', job: 'Beginner'});
      await store.setSetting('activeCharacterId', settings.activeCharacterId); await refreshCharacters();
    }
  } finally { starting = false; }
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
  navigator.storage?.persist?.().catch(() => {});
  scan();
  // Pickup reading (its own text reader, 15 fps) starts after the first accepted EXP reading, so loading it does
  // not slow finding the HUD; after 30 s it starts anyway (reported live: started at once, the first level took ~30 s).
  setTimeout(startPickupTracking, 30e3);
}

async function beginSession() {
  const at = Date.now();
  capture.sessionId = await store.startSession(character.id, at); capture.startedAt = at;
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
  await stopPickupTracking(current);
  await current.recording?.stop();
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
// A window wider than the game's screen shows it stretched (fullscreen 1920x1080): the frame is then the
// game's own pixels, so the HUD reads as it does natively (measured: stretched digits looked different
// at every position, and needed 53 learned shapes and minutes of skipped scans).
// shortcut: assumes the window shows only the game (fullscreen or borderless), as the pickup reader does.
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
  const {sx, sy, mode} = captureScale(w, h);
  // Band rows are in frame (game) pixels; a stretched window needs a few more rows around them.
  const pad = sx > 1 ? 2 : 0, top = band ? Math.max(0, Math.min(h - 1, Math.floor(band.y0 * sy) - pad)) : 0;
  const rows = band ? Math.max(1, Math.min(h, Math.ceil(band.y1 * sy) + pad) - top) : h;
  const canvas = capture.canvas ??= new OffscreenCanvas(1, 1);
  if (canvas.width !== w || canvas.height !== rows) { canvas.width = w; canvas.height = rows; }
  const context = canvas.getContext('2d', {willReadFrequently: true});
  context.drawImage(source, 0, top, w, rows, 0, 0, w, rows);
  source.close?.();
  const frame = context.getImageData(0, 0, w, rows);
  if (sx === 1) return {width: w, height: rows, data: frame.data, top, full: {width: w, height: h}};
  // Undone the way the game stretched it: its default (bilinear) or its sharper 1080p filter ('area'); see scan.
  const game = unstretch(frame, sx, sy, 0, top, capture.unstretch ??= {}, mode ?? capture.stretchMode ?? 'bilinear');
  return {width: game.width, height: game.height, data: game.data, top: Math.ceil(top / sy), full: {width: Math.round(w / sx), height: Math.round(h / sy)}, stretched: !mode};
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
}

async function saveGlyphs(size, templates) {
  settings.glyphs = {...settings.glyphs, [size]: templates};
  await store.setSetting('glyphs', settings.glyphs);
}

async function scan() {
  if (!capture) return;
  const current = capture, started = performance.now(), at = Date.now();
  let outcome;
  try {
    const known = regionsFor(current.full);
    // Failing scans look for the HUD again once a minute; within two minutes of a resize every 5 s, since a
    // look taken while the window was still changing can land on the wrong rows (measured live: 2 minutes
    // without readings after a switch to 768p).
    const retry = Date.now() - (current.resizedAt ?? 0) < 120e3 ? 5e3 : 60e3;
    const redetect = !known || (current.failures >= 3 && settings.calibration?.source === 'auto' && Date.now() - current.lastDetect > retry);
    // Full frames for detection and the preview; otherwise only the HUD rows.
    const banded = Boolean(known) && !redetect && $('hud-view').hidden && !drawing;
    const frame = await grab(banded ? bandFor(known, current.full) : null);
    if (capture !== current) return;
    const resized = current.full && (frame.full.width !== current.full.width || frame.full.height !== current.full.height);
    if (resized) current.resizedAt = Date.now();
    current.full = frame.full; current.lastFrame = frame;
    if (resized && banded) { current.burst = Math.max(current.burst || 0, 1); return; }  // Re-measure with a full frame.
    outcome = await engine.exclusive(async () => {
      let regions = regionsFor(frame.full);
      if (!banded && (redetect && settings.calibration?.source !== 'manual' || !regions)) {
        const reason = await detect(frame);
        regions = regionsFor(frame.full);
        if (!regions) return {status: 'no_hud', reason: reason ?? 'hud_not_found'};
      }
      return readHud(engine, frame, shifted(regions, frame.top), templatesFor(frame),
        {table, previousLevel: current.tracker.last?.level ?? current.tracker.pending?.level ?? current.tracker.reference?.level ?? null});
    });
    if (!outcome) return;  // A previous scan is still running; never queue another.
    if (capture !== current) return;
    outcome.frameWidth = frame.full.width; outcome.frameHeight = frame.full.height;
    // The game can stretch 1080p two ways (its filter setting). The exact HUD digits match only when the frame is
    // undone the same way, so a stretched scan whose digits didn't match tries the other way next (measured live:
    // the filtered screen read 20,679 [84.74%] exactly undone as 'area', the percentage not at all as bilinear).
    if (frame.stretched && outcome.source !== 'glyphs') current.stretchMode = current.stretchMode === 'area' ? 'bilinear' : 'area';
    // Pickup reading undoes the stretch the same way once the HUD digits have settled it.
    else if (frame.stretched && current.pickups?.session && current.pickups.stretch !== (current.stretchMode ?? 'bilinear')) {
      current.pickups.stretch = current.stretchMode ?? 'bilinear'; current.pickups.session.setStretch(current.pickups.stretch);
    }
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
  ignored_by_user: 'Skipping readings that looked like another character (you chose to ignore them).',
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

// Learned glyphs are kept per size, and every frame of game pixels (a native window, or a stretched one
// read unstretched) shares one set: the same digits at 768p and 1080p, over the built-in HUD_GLYPHS.
// The game draws its interface at the same pixel size at every resolution (800x600 reads with the shipped
// glyphs: measured on a screenshot), so any window not wider than the game's screen is 'game'; a wider one is
// stretched and learns its own.
const glyphSize = ({width, height}) => (width / GAME_WIDTH <= 1.03 ? 'game' : `${width}x${height}`);
const templatesFor = (frame) => {
  const size = glyphSize(frame.full), learned = settings.glyphs?.[size] ?? null;
  return size === 'game' ? {...HUD_GLYPHS, ...learned} : learned;
};

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
// A character's name bitmap, or one learned for another screen size (each size draws other pixels).
const ownsName = (c, key) => c.nameKey === key || Object.values(c.nameKeys ?? {}).includes(key);

async function identify(current, outcome, at) {
  const id = outcome.identity;
  if (!id?.nameKey) return null;
  const size = `${outcome.frameWidth}x${outcome.frameHeight}`;
  if (ownsName(character, id.nameKey)) {
    current.nameStreak = null;
    // The size the character's own bitmap is drawn at; another size may adopt a bitmap (below).
    if (character.nameKey === id.nameKey && character.nameSize !== size) character = await store.getCharacter(await store.saveCharacter({...character, nameSize: size}));
    // Remember the name's glyphs, so a later rename can teach its letters.
    if (!character.nameGlyphs && id.nameGlyphs) character = await store.getCharacter(await store.saveCharacter({...character, nameGlyphs: id.nameGlyphs}));
    // A name read by OCR (never one the player typed) is re-read once per session with the current
    // reader and learned letters. Only an OCR label needs a same-length correction.
    if (character.nameSource !== 'user' && current.nameChecked !== character.id) {
      current.nameChecked = character.id;
      const who = await readIdentity(engine, current.lastFrame, {name: outcome.boxes.name}, templatesFor(current.lastFrame), JOBS, settings.letters);
      if (who.name && who.name !== character.name && (character.nameSource === 'placeholder' || who.name.length === character.name.length)) {
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
  const resolved = resolveLevel(table, outcome.level, outcome.exp, outcome.bp, null), reading = {at, level: resolved.level, exp: outcome.exp, bp: outcome.bp};
  const fits = !character.last || (resolved.level !== null && !suspicious(character.last, reading));
  // At a screen size this character has no name bitmap for yet, the name is drawn with other pixels
  // (measured: a stretched 1920x1080 window). When the EXP carries on from its last reading, it is still
  // this character, and the bitmap is remembered for this size. Never at the size its own bitmap was seen
  // at: there another bitmap is another name (an alt at a similar level would otherwise be adopted).
  if (character.nameKey && character.last && fits && !character.nameKeys?.[size] && character.nameSize && character.nameSize !== size) {
    character = await store.getCharacter(await store.saveCharacter({...character, nameKeys: {...character.nameKeys, [size]: id.nameKey}}));
    return null;
  }
  const all = await store.characters(), match = all.find((c) => ownsName(c, id.nameKey));
  if (match) { await selectCharacter(match.id); setStatus(`Switched to ${match.name}`, 'ok'); return 'character_switched'; }
  const who = await readIdentity(engine, current.lastFrame, outcome.boxes, templatesFor(current.lastFrame), JOBS, settings.letters);
  if (who.job) await teachLetters(id.jobGlyphs, who.job);
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
  // Name and job reads hold the text reader too, so a pickup read cannot change its settings midway.
  const switched = status === 'ok' ? await engine.exclusive(() => identify(current, outcome, at)) : null;
  if (switched === 'character_switched' || capture !== current) { render(); return; }
  if (switched) { status = 'identity_pending'; reason = switched; }
  if (status === 'ok') {
    const previous = current.tracker.last?.level ?? current.tracker.pending?.level ?? null;
    const resolved = resolveLevel(table, outcome.level, outcome.exp, outcome.bp, previous);
    if (resolved.level === null) { status = 'rejected'; reason = resolved.reason; }
    else {
      const trustedIdentity = Boolean(character.nameKey && outcome.identity?.nameKey && ownsName(character, outcome.identity.nameKey));
      const result = step(table, current.tracker, {at, level: resolved.level, exp: outcome.exp, bp: outcome.bp}, {maxGapSeconds: maxGapFor(settings.interval), trustedIdentity});
      current.tracker = result.state; accepted = result.accept; status = result.status; reason = result.reason;
      if (status === 'pending') current.burst = Math.max(current.burst || 0, 1);  // Confirm a second later.
      // Within a minute of "Ignore these readings", such readings are dropped without asking again.
      if (status === 'identity_check' && Date.now() < (current.ignoreUntil ?? 0)) { current.tracker = {...current.tracker, pending: null, agree: 1}; status = 'rejected'; reason = 'ignored_by_user'; }
      if (status === 'identity_check') identitySuspect = result.suspect;
      else if (status === 'accepted') identitySuspect = null;  // Back on track: the question no longer applies.
    }
  }
  // Table-rejected readings count too: a box that clips digits reads 'cleanly' but never matches.
  current.failures = ['accepted', 'pending', 'identity_check', 'identity_pending'].includes(status) ? 0 : current.failures + 1;
  await store.record(character.id, current.sessionId, accepted, current.tracker, status);
  if (status === 'accepted') await teach(outcome);
  if (accepted.length) {
    startPickupTracking();
    character = await store.getCharacter(character.id);
    readingsCache.push(...accepted.map((r) => ({...r, characterId: character.id, sessionId: current.sessionId})));
    readingsCache = readingsCache.filter((r) => r.at >= Date.now() - store.DETAIL_MS);
    daysCache = await store.days(character.id);
    broadcast(false);
  }
  if (['accepted', 'pending', 'identity_check', 'identity_pending'].includes(status)) current.readableAt = at;
  const stuck = at - (current.readableAt ?? current.startedAt ?? at) > 60e3;
  if (status === 'accepted') setStatus('Tracking', 'ok');
  else if (status === 'identity_check') setStatus('Paused: this looks like a different character', 'warn');
  // A minute without a usable reading: one steady explanation instead of a new reason every scan.
  else if (stuck) {
    $('hud-tools').open = true;  // The tools for this open by themselves.
    setStatus(`Can't read the EXP bar in this ${current.full?.width}×${current.full?.height} window yet. Keep the HUD visible, try the game at 1366×768, or draw the HUD boxes below.`, 'warn');
  }
  else setStatus(MESSAGES[reason] ?? MESSAGES[status] ?? reason, 'warn');
  render();
}

// Only a reading the tracker accepted (table-consistent, confirmed by a second scan) teaches glyphs.
async function teach(outcome) {
  const frameSize = glyphSize({width: outcome.frameWidth, height: outcome.frameHeight});
  const known = settings.glyphs?.[frameSize] ?? {};
  const text = displayed(outcome.exp, outcome.bp), templates = {...known}, last = capture?.tracker.last;
  let added = 0;
  if (outcome.source === 'ocr' && outcome.segments) added += (learn(templates, outcome.segments.number, text.number) ?? 0) + (learn(templates, outcome.segments.percent, text.percent) ?? 0);
  // Level digits too, from the accepted level: when the badge OCR read that level, or read nothing (a lone
  // digit, which OCR misses) and the EXP table settled it. Never when OCR read another level.
  if (outcome.levelSource === 'ocr' && outcome.levelSegments && last?.level != null && (outcome.level === null || outcome.level === last.level)) {
    added += learn(templates, outcome.levelSegments, String(last.level)) ?? 0;
  }
  if (added || JSON.stringify(templates) !== JSON.stringify(known)) await saveGlyphs(frameSize, templates);
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

// ---------- pickups ----------

// Meso and item pickups, read from the game's messages while "Track pickups" is on (pickup-session.js).
async function startPickupTracking() {
  const current = capture;
  if (!current || !engine || current.pickups || !settings.pickups) return;
  const state = current.pickups = {since: Date.now(), session: null, fontSaved: Date.now()};
  // The learned message font is kept per game-window size: another size draws other pixels. The worker
  // reads any window at least the game's width in game pixels (unstretched when wider), so those share one.
  const {width, height} = current.track.getSettings(), size = fontSize({width, height});
  // Game pixels start from the shipped font; another size draws other pixels, so it learns its own.
  const font = (settings.pickupFont ??= {})[size] ??= {};
  if (size === 'game') seedFont(font);
  try {
    state.session = await startPickups({track: current.track, engine: await getPickupEngine(), font,
      onMessage: (m) => savePickup(current, m).catch((error) => setStatus(`Couldn't save a pickup: ${error.message}`, 'warn')),
      onStats(s) { $('pickup-stats').textContent = `Reading pickups · ${s.fps.toFixed(1)} fps${s.queued ? ` · ${s.queued} waiting` : ''}`; },
      onError(message) { $('pickup-stats').textContent = `Pickup reading stopped: ${message}`; },
    });
    // Stopped, or switched off, while starting.
    if (capture !== current || current.pickups !== state) await state.session.stop();
  } catch (error) {
    if (current.pickups === state) current.pickups = null;
    $('pickup-stats').textContent = `Can't track pickups here: ${error.message}`;
  }
  render();
}

async function stopPickupTracking(current = capture) {
  const state = current?.pickups;
  if (!state) return;
  current.pickups = null;
  $('pickup-stats').textContent = '';
  await state.session?.stop();
  saveFont();
}

const saveFont = () => store.setSetting('pickupFont', settings.pickupFont).catch(() => {});
// Pickup messages are read in game pixels at every size: native when the window is not wider than the game's
// screen (800x600 included), unstretched when it is.
const fontSize = () => 'game';

// Mesos and items that resolve to a known item are kept; EXP comes from the EXP bar, exactly.
async function savePickup(current, m) {
  if (debug) logPickup(m);
  // Letters learned from this message are saved at most every 30 s (and when pickup reading stops).
  if (current.pickups && Date.now() - current.pickups.fontSaved > 30e3) { current.pickups.fontSaved = Date.now(); saveFont(); }
  const p = m.parsed;
  if (capture !== current || !character || !p || p.kind === 'exp' || (p.kind === 'item' && !m.item)) return;
  const row = {characterId: character.id, sessionId: current.sessionId, at: m.at, kind: p.kind, approx: Boolean(p.approx),
    ...(p.kind === 'mesos' ? {amount: p.amount} : {itemId: m.item.id, name: m.item.name, count: p.count})};
  await store.addPickup(row);
  broadcast(false);  // The pop-out's mesos/hour.
  pickupsCache.push(row);
  pickupsCache = pickupsCache.filter((r) => r.at >= Date.now() - store.DETAIL_MS);
  render();
}

function renderPickups(now) {
  const view = summarizePickups(pickupsCache, now, settings.itemWindow), window = settings.mesoWindow * 60e3;
  // Like the Live rate line: from the saved pickups (not only this session), an estimate from the third meso
  // pickup on; time without pickups counts as none, so it falls to 0 while not tracking.
  const mesos = pickupsCache.filter((r) => r.kind === 'mesos').map((r) => ({at: r.at, amount: r.amount})), since = mesos[0]?.at ?? null;
  const rate = since == null ? null : rateSeries(mesos, {from: now - 1000, to: now, window, since}).at(-1)?.perHour ?? null;
  // Always shown, so the Live rate panel keeps its half of the row; empty notes say how to start.
  $('meso-window').value = String(settings.mesoWindow); $('item-window').value = String(settings.itemWindow);
  $('meso-rate').textContent = rate == null ? '—' : fmtExp(rate);
  $('meso-rate-note').textContent = rate == null ? 'After a few meso pickups with Track pickups on' : !capture?.pickups ? 'Not reading pickups right now'
    : now - since < window ? `So far · ${duration((now - since) / 1000)} tracked` : `Over the last ${settings.mesoWindow} min`;
  $('meso-total-window').value = String(settings.mesoTotalWindow);
  $('meso-day').textContent = fmtExp(mesos.filter((r) => r.at >= now - settings.mesoTotalWindow * 60e3).reduce((sum, r) => sum + r.amount, 0));
  // Item icons come from the drop list's sprite sheets (32 px cells), loaded once.
  if (view.items.length && !itemIcons) {
    itemIcons = new Map();
    loadItems().then((list) => { itemIcons = new Map(list.map((i) => [i.id, i])); render(); }).catch(() => {});
  }
  // The category from the item ID's first digit (the inventory tab: 1 Equip, 2 Use, 4 Etc).
  const items = view.items.filter((item) => settings.itemKind === 'all' || ITEM_KINDS[Math.floor(item.itemId / 1e6)] === settings.itemKind);
  $('pickup-items').replaceChildren(...items.map(itemChip));
  // The popup with every item draws only while open; the search narrows it by name.
  if ($('items-popup').matches(':popover-open')) {
    const query = $('items-search').value.trim().toLowerCase(), shown = query ? items.filter((item) => item.name.toLowerCase().includes(query)) : items;
    $('items-popup-list').replaceChildren(...shown.map(itemChip));
    $('items-popup-note').textContent = shown.length ? `${shown.length} kind${shown.length === 1 ? '' : 's'} · ${fmtExp(shown.reduce((sum, i) => sum + i.count, 0))} picked up`
      : query ? 'No items match the search.' : 'No items picked up in this time.';
  }
  const span = settings.itemWindow === 1440 ? '24 hours' : `${settings.itemWindow} min`;
  $('pickup-note').textContent = (view.items.length ? `Items picked up in the last ${span}. ` : `No items picked up in the last ${span}. `)
    + 'Pickups are read from the game\'s messages, so a few can be missed or misread.';
}

const ITEM_KINDS = {1: 'equip', 2: 'use', 4: 'etc'};
// One item: its icon from the drop list's sprite sheets (32 px cells), name and count.
function itemChip(item) {
  const li = document.createElement('li'), icon = document.createElement('span'), known = itemIcons?.get(item.itemId);
  icon.className = 'icon';
  if (known) icon.style.cssText = `background-image:url(/static/local/items/icons-${known.sheet}.png);background-position:-${known.cell % 16 * 32}px -${Math.floor(known.cell / 16) * 32}px`;
  li.append(icon, item.name, Object.assign(document.createElement('span'), {className: 'count', textContent: `×${fmtExp(item.count)}`}));
  return li;
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
  // The shared style (product.css) puts the dot before it.
  $('age').textContent = view.last ? `last reading ${duration(view.age)} ago` : '';
  $('rate').textContent = view.perHour == null ? '—' : fmtExp(view.perHour);
  $('rate-label').textContent = `EXP / hour · ${settings.window} min`;
  $('rate-note').textContent = view.perHour == null ? 'Needs a few minutes of readings'
    : (view.early ? `So far · ${duration(view.covered)} observed` : '') + (view.percentPerHour != null ? `${view.early ? ' · ' : ''}${view.percentPerHour.toFixed(2)}% / hour` : '');
  $('movement').textContent = view.recent == null ? '—' : fmtExp(view.recent);
  $('tracked-exp').textContent = view.dayGain == null ? '—' : expText(view.dayGain);
  $('tracked-note').textContent = view.dayGain == null ? `${expText(view.totalGain)} EXP tracked on this device` : `${duration(view.dayCovered)} observed · ${expText(view.totalGain)} all time`;
  plannerState = {level: view.last?.level ?? null, exp: view.last?.exp ?? null, rate: view.perHour, tracked: view.dayCovered};
  $('eta').textContent = view.eta == null ? '—' : duration(view.eta);
  $('eta-note').textContent = view.eta == null ? (view.last && !view.total ? 'No EXP table for this level' : 'Needs an EXP / hour') : `${fmtExp(view.total - view.last.exp)} EXP to go`;
  renderPickups(now);
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

// The overlay recomputes from IndexedDB; the message only says something changed and for whom. `full:
// false` (a new reading or pickup) lets it fetch only the new rows; anything else rereads everything.
function broadcast(full = true) {
  channel?.postMessage({type: 'update', characterId: character?.id ?? null, full});
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
    $(`text-${key}`).textContent = key === 'level' && lastScan?.levelSource === 'glyphs' ? `${lastScan.level} (glyphs)` : raw || '—';
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
  // Closing the popup any way (Cancel, ×, Escape, a click outside) leaves the selected character as it was.
  $('editor').addEventListener('toggle', (event) => { if (event.newState === 'closed') $('character-select').value = character ? String(character.id) : 'new'; });
  // The whole Next level card opens the planner; its pencil stays the keyboard's way in.
  document.querySelector('.next-card').addEventListener('click', (event) => { if (!event.target.closest('button')) $('planner').showPopover(); });
  $('planner').addEventListener('toggle', async (event) => { if (event.newState === 'open') (await import('./level-plan.js')).openPlanner($('planner-body'), table, plannerState); });
  for (const id of ['remove-from', 'remove-to', 'remove-exp', 'remove-mesos', 'remove-items']) $(id).addEventListener('input', renderRemoval);
  $('remove-apply').addEventListener('click', (event) => confirmFirst(event.currentTarget, {title: 'Remove the selected data?',
    text: 'The checked EXP, mesos and items in this time range are removed from this browser. This can\'t be undone.', yes: 'Remove'}, applyRemoval));
  $('character-form').addEventListener('submit', (event) => { event.preventDefault(); saveCharacterForm(false); });
  $('character-new').addEventListener('click', () => saveCharacterForm(true));
  $('character-cancel').addEventListener('click', () => $('editor').hidePopover());
  $('character-delete').addEventListener('click', (event) => confirmFirst(event.currentTarget, {title: `Delete ${character?.name ?? 'this character'}?`,
    text: 'Its tracked EXP, mesos and items in this browser are deleted with it. This can\'t be undone.', yes: 'Delete character'}, async () => {
    if (capture) await stop('character_deleted');
    await store.deleteCharacter(character.id);
    settings.activeCharacterId = null; $('editor').hidePopover();
    await refreshCharacters(); broadcast();
  }));
  $('identity-same').addEventListener('click', confirmIdentity);
  $('identity-switch').addEventListener('click', () => { identitySuspect = null; render(); $('character-select').focus(); });
  // The readings were wrong (a misread badge, say): drop them, keep the character's last good state, and don't
  // ask again for a minute.
  $('identity-ignore').addEventListener('click', () => {
    identitySuspect = null;
    if (capture) { capture.tracker = {...capture.tracker, pending: null, agree: 1}; capture.ignoreUntil = Date.now() + 60e3; }
    setStatus('Ignored those readings', 'ok'); render();
  });
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
  for (const button of document.querySelectorAll('[data-live-kind]')) button.addEventListener('click', () => { settings.liveKind = button.dataset.liveKind; store.setSetting('liveKind', settings.liveKind).catch(() => {}); showLive(); });
  for (const button of document.querySelectorAll('[data-item-kind]')) button.addEventListener('click', () => {
    settings.itemKind = button.dataset.itemKind; store.setSetting('itemKind', settings.itemKind).catch(() => {});
    pressed('[data-item-kind]', 'itemKind', settings.itemKind); render();
  });
  $('items-search').addEventListener('input', () => render());
  $('items-popup').addEventListener('toggle', (event) => { if (event.newState === 'open') render(); });
  $('meso-total-window').addEventListener('change', (event) => {
    settings.mesoTotalWindow = Number(event.target.value); store.setSetting('mesoTotalWindow', settings.mesoTotalWindow).catch(() => {}); render();
  });
  $('meso-window').addEventListener('change', (event) => {
    settings.mesoWindow = Number(event.target.value); store.setSetting('mesoWindow', settings.mesoWindow).catch(() => {}); render();
  });
  // The item time: the panel's dropdown and the popup's pills are the same setting.
  $('item-window').addEventListener('change', (event) => {
    settings.itemWindow = Number(event.target.value); store.setSetting('itemWindow', settings.itemWindow).catch(() => {});
    pressed('[data-item-window]', 'itemWindow', settings.itemWindow); render();
  });
  for (const button of document.querySelectorAll('[data-item-window]')) button.addEventListener('click', () => {
    settings.itemWindow = Number(button.dataset.itemWindow); store.setSetting('itemWindow', settings.itemWindow).catch(() => {});
    pressed('[data-item-window]', 'itemWindow', settings.itemWindow); render();
  });
  for (const button of document.querySelectorAll('[data-live-window]')) button.addEventListener('click', () => { settings.liveWindow = Number(button.dataset.liveWindow); store.setSetting('liveWindow', settings.liveWindow).then(broadcast, () => {}); showLive(); });
  liveChart($('live-canvas'), liveSource);
  // Footer: the zone for times on this page, as on the live pages.
  const zones = $('timezone'), own = Intl.DateTimeFormat().resolvedOptions().timeZone, list = Intl.supportedValuesOf?.('timeZone') ?? [];
  zones.append(new Option(`${own.replaceAll('_', ' ')} (local)`, ''), ...(list.includes('UTC') ? list : ['UTC', ...list]).map((z) => new Option(z.replaceAll('_', ' '), z)));
  zones.value = timeZone ?? '';
  zones.addEventListener('change', () => {
    setTimeZone(zones.value);
    try { if (zones.value) localStorage.setItem('timezone', zones.value); else localStorage.removeItem('timezone'); } catch {}
    render();
  });
  $('scenery-toggle').addEventListener('click', () => {
    settings.scenery = $('scenery-toggle').getAttribute('aria-pressed') !== 'true';
    showScenery(settings.scenery); store.setSetting('scenery', settings.scenery).catch(() => {});
  });
  $('track-pickups').addEventListener('change', async (event) => {
    settings.pickups = event.target.checked;
    await store.setSetting('pickups', settings.pickups);
    if (settings.pickups) await startPickupTracking(); else await stopPickupTracking();
    render();
  });
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
  // Restore: a backup file replaces everything tracked here, once it has been checked and confirmed.
  $('restore').addEventListener('click', () => $('restore-file').click());
  $('restore-file').addEventListener('change', async (event) => {
    const file = event.target.files[0], note = $('restore-note');
    event.target.value = '';
    if (!file) return;
    let backup;
    try {
      if (file.size > 200e6) throw new Error('This file is too large to be a backup.');
      backup = store.checkBackup(JSON.parse(await file.text()));
    } catch (error) {
      note.textContent = `Can't import: ${error instanceof SyntaxError ? "the file isn't valid JSON." : error.message}`;
      return;
    }
    note.textContent = '';
    const when = backup.exportedAt && !Number.isNaN(Date.parse(backup.exportedAt)) ? ` from ${new Date(backup.exportedAt).toLocaleString()}` : '';
    const count = (n, word) => `${n.toLocaleString('en-US')} ${word}${n === 1 ? '' : 's'}`;
    confirmFirst($('restore'), {title: 'Import this file?',
      text: `Everything tracked in this browser is replaced by the file${when}: ${count(backup.characters.length, 'character')}, ${count(backup.readings.length, 'reading')} and ${count(backup.pickups.length, 'pickup')}. This can't be undone.`,
      yes: 'Import'}, async () => {
      if (capture) await stop('restored');
      try { await store.restoreAll(backup); } catch (error) { note.textContent = `Can't import: ${error.message}`; return; }
      // The character tracked most recently in the file becomes the active one (the overlays show it).
      const latest = backup.readings.reduce((a, r) => (r.at > (a?.at ?? -Infinity) ? r : a), null);
      settings.activeCharacterId = latest?.characterId ?? backup.characters[0]?.id ?? null;
      await store.setSetting('activeCharacterId', settings.activeCharacterId);
      character = null; readingsCache = []; pickupsCache = [];
      await refreshCharacters(); broadcast();
      note.textContent = `Imported: ${count(backup.characters.length, 'character')}.`;
    });
  });
  for (const id of ['clear', 'editor-clear']) $(id).addEventListener('click', (event) => confirmFirst(event.currentTarget, {title: 'Clear all local history?',
    text: 'Every character, reading and pickup in this browser is deleted, along with what the reader has learned. This can\'t be undone.', yes: 'Clear everything'}, async () => {
    if (capture) await stop('cleared');
    await store.clearAll();
    settings = {interval: settings.interval, window: settings.window, calibration: null, activeCharacterId: null, glyphs: null, letters: {}, pickups: true, scenery: settings.scenery, liveKind: settings.liveKind, liveWindow: settings.liveWindow, mesoWindow: settings.mesoWindow, mesoTotalWindow: settings.mesoTotalWindow, itemWindow: settings.itemWindow, itemKind: settings.itemKind};
    character = null; readingsCache = []; pickupsCache = []; $('track-pickups').checked = true;
    await refreshCharacters(); broadcast(); setStatus('Local history cleared');
  }));
  setupDrawing();
  if (debug) setupDebug();

  try {
    await loadTable();
    if (!await lockHeldElsewhere()) await store.closeAbandoned();
    for (const key of ['interval', 'window', 'calibration', 'activeCharacterId', 'glyphs', 'letters', 'pickups', 'scenery', 'liveKind', 'liveWindow', 'mesoWindow', 'mesoTotalWindow', 'itemWindow', 'itemKind', 'pickupFont']) {
      const value = await store.getSetting(key);
      if (value !== undefined) settings[key] = value;
    }
    // Saved before sizes were kept apart: {size, templates} and {size, glyphs}.
    if (settings.glyphs?.templates) settings.glyphs = {[settings.glyphs.size]: settings.glyphs.templates};
    // Sets learned per window size before game pixels were shared: a native window's become the shared set.
    for (const size of Object.keys(settings.glyphs ?? {})) {
      const [width, height] = size.split('x').map(Number);
      if (glyphSize({width, height}) === 'game') { settings.glyphs = {...settings.glyphs, game: {...settings.glyphs[size], ...settings.glyphs.game}}; delete settings.glyphs[size]; }
    }
    if (!INTERVALS.includes(settings.interval)) settings.interval = 1;
    if (!WINDOWS.includes(settings.window)) settings.window = 5;
    pressed('[data-interval]', 'interval', settings.interval); pressed('[data-window]', 'window', settings.window);
    $('track-pickups').checked = Boolean(settings.pickups);
    showScenery(settings.scenery !== false);
    showLive();
    Object.assign(builder, overlayOptions((await store.getSetting('overlay')) ?? ''));
    await refreshCharacters();
    updateBuilder();
    store.prune().catch(() => {});
  } catch (error) {
    setStatus(`Local storage is unavailable: ${error.message}`, 'warn');
    $('start').disabled = true;
  } finally {
    // Paint the hidden state first, even when local data loads before the first frame.
    requestAnimationFrame(() => requestAnimationFrame(() => { delete document.body.dataset.loading; }));
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
  const url = overlayURL(), [width, height] = overlaySize(builder), frame = $('overlay-preview');
  $('overlay-url').value = location.origin + url; $('overlay-link').href = url; $('overlay-size').textContent = `Window · ${width} × ${height}`;
  for (const button of document.querySelectorAll('[data-option] button')) {
    const key = button.closest('[data-option]').dataset.option;
    button.setAttribute('aria-pressed', String(builder[key] === button.dataset.value && (key !== 'theme' || !OVERLAY_COLORS.some((color) => builder[color]))));
  }
  for (const input of document.querySelectorAll('[data-color]')) input.value = '#' + (builder[input.dataset.color] ?? THEME_COLORS[builder.theme][input.dataset.color]);
  for (const row of document.querySelectorAll('[data-for-layout]')) row.hidden = row.dataset.forLayout !== builder.layout;
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
    // A separate window of this browser profile shares IndexedDB and BroadcastChannel with this tab. One window
    // per layout, so several can be open at once (Last hour, Live and Items in one scene).
    const [width, height] = overlaySize(builder);
    window.open(overlayURL(), `msxp-local-overlay-${builder.layout}`, `popup,width=${width},height=${height}`);
  });
  window.addEventListener('resize', scalePreview);
}

function showScenery(on) {
  setScenery(on);
  $('scenery-toggle').setAttribute('aria-pressed', String(on));
  $('scenery-toggle').title = on ? 'Hide the town background and mobs' : 'Show the town background and mobs';
}

// ---------- Live rate ----------

function showLive() {
  if (!['exp', 'mesos'].includes(settings.liveKind)) settings.liveKind = 'exp';
  if (!WINDOWS.includes(settings.liveWindow)) settings.liveWindow = 5;
  if (![...WINDOWS, 60, 1440].includes(settings.itemWindow)) settings.itemWindow = 1440;
  if (!WINDOWS.includes(settings.mesoWindow)) settings.mesoWindow = 5;
  if (![5, 10, 15, 30, 60, 240, 720, 1440].includes(settings.mesoTotalWindow)) settings.mesoTotalWindow = 1440;
  if (!['all', 'equip', 'use', 'etc'].includes(settings.itemKind)) settings.itemKind = 'all';
  pressed('[data-item-kind]', 'itemKind', settings.itemKind);
  pressed('[data-item-window]', 'itemWindow', settings.itemWindow);
  pressed('[data-live-kind]', 'liveKind', settings.liveKind); pressed('[data-live-window]', 'liveWindow', settings.liveWindow);
  $('live-board').dataset.kind = settings.liveKind;
  live.key = null;
}

// The chart asks about 30 times a second; the series is rebuilt once a second or when data changes.
const live = {key: null, view: null};
function liveSource() {
  const kind = settings.liveKind, window = settings.liveWindow * 60e3, now = Date.now();
  const key = `${kind}|${window}|${Math.floor(now / 1000)}|${readingsCache.length}|${pickupsCache.length}|${Boolean(capture?.pickups)}`;
  if (live.key === key) return live.view;
  live.key = key;
  const rows = kind === 'mesos' ? pickupsCache.filter((r) => r.kind === 'mesos') : readingsCache;
  const events = rows.filter((r) => (r.amount ?? r.gain) != null).map((r) => ({at: r.at, amount: r.amount ?? r.gain}));
  // From the saved data (24 hours), not only this session, always up to now: time with no gains (not
  // tracking, or nothing picked up) counts as nothing gained, so the line falls toward 0.
  const since = rows[0]?.at ?? now, to = now;
  // The note quotes the drawn (eased) value, so it matches the line's tip.
  const drawn = smooth(rateSeries(events, {from: now - window - 60e3, to, window, since}));
  const unit = kind === 'mesos' ? 'mesos / h' : 'EXP / h';
  const latest = drawn.at(-1), gained = events.filter((e) => e.at > now - window).reduce((sum, e) => sum + e.amount, 0);
  $('live-note').textContent = latest
    ? `${fmtExp(latest.perHour)} ${kind === 'mesos' ? 'mesos' : 'EXP'} / hour now · ${fmtExp(gained)} gained in the last ${settings.liveWindow} min${kind === 'mesos' ? ' (approximate)' : ''}`
    : kind === 'mesos' && !settings.pickups ? 'Turn on Track pickups to see mesos.' : 'The line starts after a few gains while tracking.';
  // Smooth while this tab tracks or gains are in view (another tab tracking sends them here).
  live.view = {series: drawn, window, unit, empty: kind === 'mesos' && !settings.pickups ? 'Turn on Track pickups' : 'Waiting for a few gains…',
    live: Boolean(capture) || events.some((e) => e.at > now - window)};
  return live.view;
}

// Destructive actions ask first in a small panel saying what goes (a second click on the same button was
// too easy to do by accident). Cancel has the focus, so Enter or Escape keeps everything. Opened from the
// button (`source`), it sits over the Edit popup instead of closing it.
function confirmFirst(button, {title, text, yes}, action) {
  const box = $('confirm');
  $('confirm-title').textContent = title; $('confirm-text').textContent = text; $('confirm-yes').textContent = yes;
  $('confirm-yes').onclick = () => { box.hidePopover(); action(); };
  try { box.showPopover({source: button}); } catch { box.showPopover(); }
  $('confirm-no').focus();
}

// ?debug: every pickup message as read (unread and EXP included), newest first, to compare with the game.
function setupPickupLog() {
  const section = document.createElement('section');
  section.className = 'board local-hud';
  section.innerHTML = '<header class="board-header"><h2>Pickup messages (debug)</h2></header><ol id="pickup-log" class="pickup-log" reversed></ol>';
  document.querySelector('.local-data').before(section);
  window.msxpPickups = {messages: []};
}

// The last LOG_KEEP messages only (with their masks): an all-session log grew memory for as long as tracking ran.
const LOG_KEEP = 300;
function logPickup(m) {
  const kept = window.msxpPickups.messages;
  kept.push(m);
  if (kept.length > LOG_KEEP) kept.splice(0, kept.length - LOG_KEEP);
  const p = m.parsed, row = document.createElement('li');
  const what = !p ? 'unread' : p.kind === 'item' ? `${m.item?.name ?? p.name + (p.cut ? '…' : '') + ' (?)'} ×${p.count}` : `${p.kind} +${fmtExp(p.amount)}${p.approx ? '~' : ''}`;
  row.textContent = `${new Date(m.at).toLocaleTimeString()} · ${what} · “${m.text}”${m.via ? ` · ${m.via}` : ''}`;
  $('pickup-log').prepend(row);
  while ($('pickup-log').children.length > LOG_KEEP) $('pickup-log').lastElementChild.remove();
}

// ?debug: save the bottom of the last frame to a local file for diagnosing OCR. Never automatic.
// Test recordings of the pickup corner (?debug only), in the format the offline benches read: frames.bin
// (the corner's lossless PNGs, back to back) and index.json {region, frame, frames: [{at, offset, size}]}.
function recordButton() {
  const button = Object.assign(document.createElement('button'), {type: 'button', textContent: 'Record pickups (debug)'});
  button.addEventListener('click', async () => {
    if (capture?.recording) return capture.recording.stop();
    const current = capture;
    if (!current || !('MediaStreamTrackProcessor' in window)) return setStatus('Start tracking in Chrome or Edge first.', 'warn');
    const folder = await (await showDirectoryPicker({mode: 'readwrite'}).catch(() => null))
      ?.getDirectoryHandle(`pickup-recording-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')}`, {create: true});
    if (!folder || capture !== current || current.recording) return;
    await current.track.applyConstraints({frameRate: {ideal: 15, max: 15}});
    const clone = current.track.clone(), reader = new MediaStreamTrackProcessor({track: clone}).readable.getReader();
    const out = await (await folder.getFileHandle('frames.bin', {create: true})).createWritable();
    const index = {region: null, frame: '', frames: []}, started = performance.now();
    let offset = 0, last = -1e9, stopped = false;
    const done = (async () => {
      for (;;) {
        const {value: frame, done: ended} = await reader.read().catch(() => ({done: true}));
        if (ended) break;
        const at = Math.round(performance.now() - started), W = frame.displayWidth, H = frame.displayHeight;
        // One region per recording: a resized window ends it.
        if (index.frame && index.frame !== `${W}x${H}`) { frame.close(); break; }
        if (stopped || at - last < 90) { frame.close(); if (stopped) break; continue; }  // ~10 fps is plenty.
        last = at;
        const {x, y, w, h} = regionBox(W, H);
        if (!index.frame) Object.assign(index, {region: {x, y, w, h}, frame: `${W}x${H}`});
        const canvas = new OffscreenCanvas(w, h);
        canvas.getContext('2d').drawImage(frame, x, y, w, h, 0, 0, w, h);
        frame.close();
        const png = await canvas.convertToBlob();
        await out.write(png);
        index.frames.push({at, offset, size: png.size});
        offset += png.size;
        button.textContent = `Stop recording (${index.frames.length} frames · ${Math.round(offset / 1e6)} MB)`;
      }
      clone.stop();
      await out.close();
      const file = await (await folder.getFileHandle('index.json', {create: true})).createWritable();
      await file.write(JSON.stringify(index)); await file.close();
      if (current.recording === recording) current.recording = null;
      if (!current.pickups) await current.track.applyConstraints({frameRate: {ideal: 5, max: 5}}).catch(() => {});
      button.textContent = 'Record pickups (debug)';
      setStatus(`Saved ${index.frames.length} frames to ${folder.name}.`, 'ok');
    })();
    const recording = current.recording = {stop() { stopped = true; reader.cancel().catch(() => {}); return done; }};
  });
  return button;
}

function setupDebug() {
  const button = Object.assign(document.createElement('button'), {type: 'button', textContent: 'Save HUD strip (debug)'});
  button.addEventListener('click', async () => {
    const frame = capture?.lastFrame; if (!isFull(frame)) return;
    const y0 = Math.floor(frame.height * .78), canvas = new OffscreenCanvas(frame.width, frame.height - y0);
    canvas.getContext('2d').putImageData(new ImageData(frame.data, frame.width, frame.height), 0, -y0);
    const link = Object.assign(document.createElement('a'), {href: URL.createObjectURL(await canvas.convertToBlob()), download: `msxp-hud-${frame.width}x${frame.height}-${Date.now()}.png`});
    link.click();
  });
  document.querySelector('.hud-actions').append(button, recordButton());
  setupPickupLog();
  // Diagnostics for the pickup-message milestone: raise or restore the share's frame rate (?debug only).
  // Measured 2026-11-10: asked 5/15/30 fps, Chrome delivered 4.7/14.8/29.0 on the same share, no new prompt.
  const setFrameRate = async (fps) => {
    if (!capture) return null;
    await capture.track.applyConstraints({frameRate: {ideal: fps, max: fps}});
    return capture.track.getSettings().frameRate;
  };
  window.msxpLocal = {setFrameRate, get lastScan() { return lastScan && {...lastScan, frame: undefined}; }, get capture() { return capture; }, get settings() { return settings; }, get engine() { return engine; }};
}

init();

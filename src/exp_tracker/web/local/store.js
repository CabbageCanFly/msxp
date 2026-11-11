// IndexedDB for the local tracker: characters, sessions, accepted readings, daily summaries, pickups and
// settings.
// Structured numbers and timestamps only; no frames or crops are ever stored.

const NAME = 'msxp-local', VERSION = 3;
// Retention like the live site: detailed readings for 24 hours (+5 minutes, plus one older boundary
// reading per character so the oldest interval keeps its start), then only one summary per character
// and local day, kept indefinitely (about 200 bytes each). Character totals live on the character.
export const DETAIL_MS = 24 * 3600e3 + 5 * 60e3;

let opening = null;
export function open() {
  return opening ??= new Promise((resolve, reject) => {
    const request = indexedDB.open(NAME, VERSION);
    request.onupgradeneeded = (event) => {
      const db = request.result;
      if (event.oldVersion < 1) {
        db.createObjectStore('characters', {keyPath: 'id', autoIncrement: true});
        db.createObjectStore('sessions', {keyPath: 'id', autoIncrement: true}).createIndex('character', 'characterId');
        const readings = db.createObjectStore('readings', {keyPath: 'id', autoIncrement: true});
        readings.createIndex('character_at', ['characterId', 'at']);
        readings.createIndex('at', 'at');
        db.createObjectStore('settings');
      }
      if (event.oldVersion < 2) {
        db.createObjectStore('days', {keyPath: ['characterId', 'day']});
        // Existing readings seed the daily history (an additive migration; nothing is deleted here).
        const tx = request.transaction, days = tx.objectStore('days');
        tx.objectStore('readings').openCursor().onsuccess = function () {
          const cursor = this.result;
          if (!cursor) return;
          const r = cursor.value, key = [r.characterId, dayOf(r.at)];
          days.get(key).onsuccess = function () { days.put(foldDay(this.result, r)); };
          cursor.continue();
        };
      }
      if (event.oldVersion < 3) {
        // Meso and item pickups read from the game's messages (approximate by design), kept like readings.
        db.createObjectStore('pickups', {keyPath: 'id', autoIncrement: true}).createIndex('character_at', ['characterId', 'at']);
      }
    };
    request.onsuccess = () => {
      // Another tab upgrading or deleting the database must not be blocked by this one.
      request.result.onversionchange = () => { request.result.close(); opening = null; };
      resolve(request.result);
    };
    request.onerror = () => { opening = null; reject(request.error); };
    request.onblocked = () => reject(new Error('Close other msxp tabs to open local history'));
  });
}

// The player's own calendar day (a personal tracker), not UTC as on the shared live site.
export function dayOf(at) {
  const d = new Date(at);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// A day's summary keeps its latest accepted reading and the EXP gained that day.
export function foldDay(day, r) {
  const later = !day || r.at >= day.at;
  return {characterId: r.characterId, day: dayOf(r.at), gain: (day?.gain || 0) + (r.gain || 0),
    ...(later ? {at: r.at, level: r.level, exp: r.exp, bp: r.bp} : {at: day.at, level: day.level, exp: day.exp, bp: day.bp})};
}

const done = (tx) => new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = tx.onabort = () => reject(tx.error); });
const result = (request) => new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });

async function run(stores, mode, body) {
  const db = await open(), tx = db.transaction(stores, mode), finished = done(tx);
  let value;
  try { value = await body(tx); } catch (error) { try { tx.abort(); } catch {} finished.catch(() => {}); throw error; }
  await finished;
  return value;
}

export const getSetting = (key) => run('settings', 'readonly', (tx) => result(tx.objectStore('settings').get(key)));
export const setSetting = (key, value) => run('settings', 'readwrite', (tx) => { tx.objectStore('settings').put(value, key); });
export const characters = () => run('characters', 'readonly', (tx) => result(tx.objectStore('characters').getAll()));
export const getCharacter = (id) => run('characters', 'readonly', (tx) => result(tx.objectStore('characters').get(id)));

export function saveCharacter(character) {
  return run('characters', 'readwrite', (tx) => result(tx.objectStore('characters').put({totalGain: 0, createdAt: Date.now(), ...character})));
}

export function startSession(characterId, at) {
  return run('sessions', 'readwrite', (tx) => result(tx.objectStore('sessions').add({characterId, startedAt: at, endedAt: null, counts: {}})));
}

export function endSession(id, at, reason) {
  return run('sessions', 'readwrite', async (tx) => {
    const store = tx.objectStore('sessions'), session = await result(store.get(id));
    if (session && !session.endedAt) store.put({...session, endedAt: at, endReason: reason});
  });
}

// Close sessions a crash or closed tab left open, at their last reading (never "now").
export function closeAbandoned() {
  return run(['sessions', 'readings'], 'readwrite', async (tx) => {
    const sessions = tx.objectStore('sessions'), index = tx.objectStore('readings').index('character_at');
    for (const session of await result(sessions.getAll())) {
      if (session.endedAt) continue;
      const cursor = await result(index.openCursor(IDBKeyRange.bound([session.characterId, session.startedAt], [session.characterId, Infinity]), 'prev'));
      sessions.put({...session, endedAt: cursor?.value?.at ?? session.startedAt, endReason: 'page_closed'});
    }
  });
}

/**
 * Persist one scan outcome atomically: accepted readings, their daily summaries, the tracker state
 * and status counts. The tracker state is stored on the character so a reload continues from it.
 */
export function record(characterId, sessionId, accepted, trackerState, status) {
  return run(['characters', 'sessions', 'readings', 'days'], 'readwrite', async (tx) => {
    const characters = tx.objectStore('characters'), sessions = tx.objectStore('sessions'), readings = tx.objectStore('readings'), days = tx.objectStore('days');
    const character = await result(characters.get(characterId)), session = await result(sessions.get(sessionId));
    if (!character || !session || session.characterId !== characterId) throw new Error('Character or session no longer exists');
    let gain = 0;
    for (const r of accepted) {
      const row = {characterId, sessionId, at: r.at, level: r.level, exp: r.exp, bp: r.bp, gain: r.gain, kind: r.kind};
      readings.add(row);
      days.put(foldDay(await result(days.get([characterId, dayOf(r.at)])), row));
      gain += r.gain ?? 0;
    }
    characters.put({...character, totalGain: (character.totalGain || 0) + gain, tracker: trackerState,
      last: trackerState.last ?? character.last ?? null});
    const counts = {...session.counts, [status]: (session.counts[status] || 0) + 1};
    sessions.put({...session, counts, lastStatusAt: Date.now()});
  });
}

// One pickup: {characterId, sessionId, at, kind: 'mesos', amount} or {..., kind: 'item', itemId, name, count};
// `approx` marks an amount rounded from unclear digits.
export const addPickup = (row) => run('pickups', 'readwrite', (tx) => { tx.objectStore('pickups').add(row); });

export function pickups(characterId, since = 0) {
  return run('pickups', 'readonly', (tx) => result(tx.objectStore('pickups').index('character_at')
    .getAll(IDBKeyRange.bound([characterId, since], [characterId, Infinity]))));
}

/**
 * Removes what was tracked between two times for one character, by kind. EXP readings keep their level
 * and EXP but lose their gain, so the time counts as unobserved (like a gap), not as zero EXP, and the
 * day and all-time totals drop by it. Mesos and items are deleted. Older days (`oldDays`, 'YYYY-MM-DD'
 * keys) have only a summary: removing their EXP deletes that day's history point and its gain.
 */
export function removeTracked(characterId, from, to, {exp = false, mesos = false, items = false, oldDays = []}) {
  return run(['characters', 'readings', 'days', 'pickups'], 'readwrite', async (tx) => {
    const range = IDBKeyRange.bound([characterId, from], [characterId, to]);
    if (exp) {
      const readings = tx.objectStore('readings'), days = tx.objectStore('days');
      let removed = 0;
      for (const r of await result(readings.index('character_at').getAll(range))) {
        if (r.gain == null) continue;
        readings.put({...r, gain: null, removed: true});
        const day = await result(days.get([characterId, dayOf(r.at)]));
        if (day) days.put({...day, gain: day.gain - r.gain});
        removed += r.gain;
      }
      for (const key of oldDays) {
        const day = await result(days.get([characterId, key]));
        if (day) { days.delete([characterId, key]); removed += day.gain || 0; }
      }
      const character = await result(tx.objectStore('characters').get(characterId));
      if (character) tx.objectStore('characters').put({...character, totalGain: (character.totalGain || 0) - removed});
    }
    const pickups = tx.objectStore('pickups');
    for (const p of await result(pickups.index('character_at').getAll(range))) {
      if ((p.kind === 'mesos' && mesos) || (p.kind === 'item' && items)) pickups.delete(p.id);
    }
  });
}

export function readings(characterId, since = 0) {
  return run('readings', 'readonly', (tx) => result(tx.objectStore('readings').index('character_at')
    .getAll(IDBKeyRange.bound([characterId, since], [characterId, Infinity]))));
}

export function days(characterId) {
  return run('days', 'readonly', (tx) => result(tx.objectStore('days').getAll(IDBKeyRange.bound([characterId, ''], [characterId, '￿']))));
}

// Drop detailed readings and pickups past the 24-hour window. Daily summaries were already folded in on record.
export function prune(now = Date.now()) {
  const cutoff = now - DETAIL_MS;
  return run(['characters', 'readings', 'pickups'], 'readwrite', async (tx) => {
    tx.objectStore('pickups').openCursor().onsuccess = function () {
      const cursor = this.result;
      if (cursor) { if (cursor.value.at < cutoff) cursor.delete(); cursor.continue(); }
    };
    const index = tx.objectStore('readings').index('character_at');
    for (const id of await result(tx.objectStore('characters').getAllKeys())) {
      const old = await result(index.getAllKeys(IDBKeyRange.bound([id, 0], [id, cutoff])));
      for (const key of old.slice(0, -1)) tx.objectStore('readings').delete(key);  // Keep one boundary reading.
    }
  });
}

export function exportAll() {
  return run(['characters', 'sessions', 'readings', 'days', 'pickups', 'settings'], 'readonly', async (tx) => ({
    format: 'msxp-local-v3', exportedAt: new Date().toISOString(),
    characters: await result(tx.objectStore('characters').getAll()),
    sessions: await result(tx.objectStore('sessions').getAll()),
    readings: await result(tx.objectStore('readings').getAll()),
    days: await result(tx.objectStore('days').getAll()),
    pickups: await result(tx.objectStore('pickups').getAll()),
  }));
}

export function deleteCharacter(id) {
  return run(['characters', 'sessions', 'readings', 'days', 'pickups'], 'readwrite', async (tx) => {
    tx.objectStore('characters').delete(id);
    tx.objectStore('pickups').index('character_at').openCursor(IDBKeyRange.bound([id, 0], [id, Infinity])).onsuccess = function () {
      const cursor = this.result;
      if (cursor) { cursor.delete(); cursor.continue(); }
    };
    for (const key of await result(tx.objectStore('sessions').index('character').getAllKeys(id))) tx.objectStore('sessions').delete(key);
    const index = tx.objectStore('readings').index('character_at');
    for (const key of await result(index.getAllKeys(IDBKeyRange.bound([id, 0], [id, Infinity])))) tx.objectStore('readings').delete(key);
    tx.objectStore('days').delete(IDBKeyRange.bound([id, ''], [id, '￿']));
  });
}

export async function clearAll() {
  const db = await open();
  db.close(); opening = null;
  await new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(NAME);
    request.onsuccess = resolve; request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('Close the overlay and other msxp tabs, then try again'));
  });
}

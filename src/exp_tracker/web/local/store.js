// IndexedDB for the local tracker: characters, sessions, accepted readings and settings.
// Structured numbers and timestamps only; no frames or crops are ever stored.

const NAME = 'msxp-local', VERSION = 1;
// Retention: accepted readings older than this are pruned when tracking starts. Character totals
// survive pruning because they are kept on the character record.
export const RETENTION_DAYS = 90;

let opening = null;
export function open() {
  return opening ??= new Promise((resolve, reject) => {
    const request = indexedDB.open(NAME, VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore('characters', {keyPath: 'id', autoIncrement: true});
      db.createObjectStore('sessions', {keyPath: 'id', autoIncrement: true}).createIndex('character', 'characterId');
      const readings = db.createObjectStore('readings', {keyPath: 'id', autoIncrement: true});
      readings.createIndex('character_at', ['characterId', 'at']);
      readings.createIndex('at', 'at');
      db.createObjectStore('settings');
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
 * Persist one scan outcome atomically: accepted readings, the tracker state and status counts.
 * The tracker state is stored on the character so a reload continues from the last accepted reading.
 */
export function record(characterId, sessionId, accepted, trackerState, status) {
  return run(['characters', 'sessions', 'readings'], 'readwrite', async (tx) => {
    const characters = tx.objectStore('characters'), sessions = tx.objectStore('sessions'), readings = tx.objectStore('readings');
    const character = await result(characters.get(characterId)), session = await result(sessions.get(sessionId));
    if (!character || !session || session.characterId !== characterId) throw new Error('Character or session no longer exists');
    let gain = 0;
    for (const r of accepted) {
      readings.add({characterId, sessionId, at: r.at, level: r.level, exp: r.exp, bp: r.bp, gain: r.gain, kind: r.kind});
      gain += r.gain ?? 0;
    }
    characters.put({...character, totalGain: (character.totalGain || 0) + gain, tracker: trackerState,
      last: trackerState.last ?? character.last ?? null});
    const counts = {...session.counts, [status]: (session.counts[status] || 0) + 1};
    sessions.put({...session, counts, lastStatusAt: Date.now()});
  });
}

export function readings(characterId, since = 0) {
  return run('readings', 'readonly', (tx) => result(tx.objectStore('readings').index('character_at')
    .getAll(IDBKeyRange.bound([characterId, since], [characterId, Infinity]))));
}

export function prune(now = Date.now()) {
  const cutoff = now - RETENTION_DAYS * 86400e3;
  return run('readings', 'readwrite', async (tx) => {
    const store = tx.objectStore('readings');
    for (const key of await result(store.index('at').getAllKeys(IDBKeyRange.upperBound(cutoff)))) store.delete(key);
  });
}

export function exportAll() {
  return run(['characters', 'sessions', 'readings', 'settings'], 'readonly', async (tx) => ({
    format: 'msxp-local-v1', exportedAt: new Date().toISOString(),
    characters: await result(tx.objectStore('characters').getAll()),
    sessions: await result(tx.objectStore('sessions').getAll()),
    readings: await result(tx.objectStore('readings').getAll()),
  }));
}

export function deleteCharacter(id) {
  return run(['characters', 'sessions', 'readings'], 'readwrite', async (tx) => {
    tx.objectStore('characters').delete(id);
    for (const key of await result(tx.objectStore('sessions').index('character').getAllKeys(id))) tx.objectStore('sessions').delete(key);
    const index = tx.objectStore('readings').index('character_at');
    for (const key of await result(index.getAllKeys(IDBKeyRange.bound([id, 0], [id, Infinity])))) tx.objectStore('readings').delete(key);
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

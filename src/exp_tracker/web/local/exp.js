// EXP parsing, arithmetic checks, conservative tracking and statistics for the local tracker.
// Pure functions (no DOM, no storage) ported from parsing.py, exp_consistency.py and validation.py.

// Strict HUD text parsing: never substitute likely digits. Percent is integer basis points (65.59% -> 6559).
export function parseExp(text) {
  const t = String(text).toUpperCase().replace(/\s+/g, '');
  const m = /^(?:EXP[.:]?)?([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,3}(?:\.[0-9]{3})+)[[(](\d{1,2})\.(\d{2})%[\])]$/.exec(t);
  if (!m) return null;
  const exp = Number(m[1].replace(/[,.]/g, ''));
  if (!Number.isSafeInteger(exp)) return null;
  return {exp, bp: Number(m[2]) * 100 + Number(m[3])};
}

export function parseLevel(text) {
  const m = /^(?:LV[.:]?)?(\d{1,3})$/.exec(String(text).toUpperCase().replace(/\s+/g, ''));
  const level = m && Number(m[1]);
  return level >= 1 && level <= 200 ? level : null;
}

// Community requirements (src/exp_tracker/data/community-exp-v2.json): to_next[level] for 1..99.
// Missing or disputed levels return null: never extrapolated, never a veto on their own.
export function requirement(table, level) {
  const value = table?.to_next?.[String(level)];
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

// Does the displayed percentage agree with EXP for this level, under either rounding the game might use?
// Exact integer arithmetic, both hypotheses as in exp_consistency.assess. Returns 'consistent',
// 'inconsistent' or 'unknown' (no published requirement).
export function consistency(table, level, exp, bp) {
  const total = requirement(table, level);
  if (total === null) return 'unknown';
  if (exp >= total) return 'inconsistent';
  const n = 10000n * BigInt(exp), T = BigInt(total);
  const truncated = n / T, nearest = (2n * n + T) / (2n * T);
  return truncated === BigInt(bp) || nearest === BigInt(bp) ? 'consistent' : 'inconsistent';
}

export function compatibleLevels(table, exp, bp) {
  const out = [];
  for (const key of Object.keys(table?.to_next || {})) if (consistency(table, Number(key), exp, bp) === 'consistent') out.push(Number(key));
  return out;
}

/**
 * Choose the level for an EXP/percentage pair. OCR level and arithmetic must agree; when the
 * badge is unreadable, the previous accepted level may continue, or the next one follow, only if the pair is
 * consistent with it.
 */
export function resolveLevel(table, ocrLevel, exp, bp, previousLevel) {
  if (ocrLevel !== null) {
    const verdict = consistency(table, ocrLevel, exp, bp);
    if (verdict === 'consistent') return {level: ocrLevel, evidence: 'ocr_and_table'};
    if (verdict === 'unknown') return {level: ocrLevel, evidence: 'ocr_only'};
  }
  if (previousLevel != null && consistency(table, previousLevel, exp, bp) === 'consistent') return {level: previousLevel, evidence: 'table_continuity'};
  // A level-up the badge didn't show (measured live: OCR reads nothing for a lone "4"): the next level, when
  // the EXP and percentage fit it exactly (8 EXP at 8.70% is level 4 alone among levels 1-10).
  if (previousLevel != null && consistency(table, previousLevel + 1, exp, bp) === 'consistent') return {level: previousLevel + 1, evidence: 'table_levelup'};
  return {level: null, reason: ocrLevel === null ? 'level_unreadable' : 'level_disagrees_with_exp'};
}

export const DEFAULTS = Object.freeze({maxGapSeconds: 120, deathDropBp: 1500, jumpBp: 2000});

export const maxGapFor = (intervalSeconds) => Math.max(DEFAULTS.maxGapSeconds, 4 * intervalSeconds + 10);

// Ordinary continuation: same level, never backwards, within the gap. Large jumps need a second look.
function continues(from, r, maxGap) {
  const seconds = (r.at - from.at) / 1000;
  return seconds > 0 && seconds <= maxGap && r.level === from.level && r.exp >= from.exp && r.bp >= from.bp
    && !(r.exp === from.exp && r.bp !== from.bp);
}
const quiet = (from, r) => r.bp - from.bp <= DEFAULTS.jumpBp;

function levelUpGain(table, from, r, maxGap) {
  const total = requirement(table, from.level), seconds = (r.at - from.at) / 1000;
  if (total === null || r.level !== from.level + 1 || seconds <= 0 || seconds > maxGap || from.exp >= total) return null;
  return total - from.exp + r.exp;
}

/**
 * One tracking step for the active character and session. `state` is {last, pending} (accepted
 * and candidate readings), `r` a level-resolved reading {at, level, exp, bp}.
 * Returns {state, accept: [{...reading, gain, kind}], status, reason}. Anything unusual (first reading,
 * level change, EXP loss, a large jump, a long gap) waits for a second agreeing reading. A confirmed
 * break starts a new baseline; its gain is never counted. Only a confirmed +1 level-up within the gap
 * with a published requirement counts its cross-level EXP. `trustedIdentity` (the character's own name
 * is on screen) skips the different-character pause.
 */
export function step(table, state, r, {maxGapSeconds = DEFAULTS.maxGapSeconds, trustedIdentity = false} = {}) {
  const {last, pending} = state;
  if (last && r.at <= last.at) return {state, accept: [], status: 'rejected', reason: 'non_increasing_time'};
  if (last && continues(last, r, maxGapSeconds) && quiet(last, r)) {
    return {state: {last: r, pending: null}, accept: [{...r, gain: r.exp - last.exp, kind: 'gain'}], status: 'accepted', reason: r.exp === last.exp ? 'unchanged' : 'same_level_gain'};
  }
  if (pending && continues(pending, r, maxGapSeconds) && quiet(pending, r)) {
    // The candidate is confirmed by a second, agreeing reading.
    let first;
    if (last && continues(last, pending, maxGapSeconds)) first = {...pending, gain: pending.exp - last.exp, kind: 'gain'};
    else {
      const gain = last ? levelUpGain(table, last, pending, maxGapSeconds) : null;
      first = gain === null ? {...pending, gain: null, kind: 'baseline'} : {...pending, gain, kind: 'level_up'};
    }
    const reference = last ?? state.reference;
    if (!trustedIdentity && reference && first.kind === 'baseline' && suspicious(reference, pending)) {
      return {state: {...state, pending: r}, accept: [], status: 'identity_check', reason: 'different_character_suspected', suspect: pending};
    }
    return {state: {last: r, pending: null}, accept: [first, {...r, gain: r.exp - pending.exp, kind: 'gain'}], status: 'accepted',
      reason: first.kind === 'baseline' ? (last ? 'new_baseline' : 'first_baseline') : first.kind};
  }
  const reason = !last ? 'awaiting_confirmation' : r.level !== last.level ? 'level_change_pending'
    : (r.at - last.at) / 1000 > maxGapSeconds ? 'gap_requires_new_baseline'
      : r.exp < last.exp || r.bp < last.bp ? 'exp_decrease_pending' : 'large_jump_pending';
  return {state: {...state, pending: r}, accept: [], status: 'pending', reason};
}

// Level drops, multi-level jumps or losses beyond a death penalty look like another character.
export function suspicious(last, r) {
  if (r.level < last.level || r.level > last.level + 1) return true;
  return r.level === last.level && last.bp - r.bp > DEFAULTS.deathDropBp;
}

// Force a confirmed candidate as a new baseline after the user says it is the same character.
export function acceptBaseline(r) {
  return {state: {last: r, pending: null}, accept: [{...r, gain: null, kind: 'baseline'}]};
}

/**
 * Statistics from accepted readings (oldest first) of one character. Intervals are consecutive
 * accepted readings in the same session whose later reading has a counted gain. Missing time is
 * never filled with zero: rates divide by observed interval time, and need coverage.
 */
export function intervals(readings) {
  const out = [];
  for (let i = 1; i < readings.length; i++) {
    const a = readings[i - 1], b = readings[i];
    if (b.gain == null || a.sessionId !== b.sessionId) continue;
    out.push({start: a.at, end: b.at, gain: b.gain, sessionId: b.sessionId, level: b.level});
  }
  return out;
}

export const MIN_COVERAGE = .8;

export function windowStats(list, now, seconds) {
  const cutoff = now - seconds * 1000;
  let gain = 0, covered = 0;
  for (const it of list) {
    if (it.end <= cutoff || it.start > now) continue;
    // Only whole intervals inside the window: boundary gains are never interpolated.
    if (it.start < cutoff) continue;
    gain += it.gain; covered += (it.end - it.start) / 1000;
  }
  const ok = covered >= seconds * MIN_COVERAGE;
  return {gain, covered, seconds, ok, perHour: covered > 0 ? gain * 3600 / covered : null};
}

export function sessionStats(list) {
  let gain = 0, covered = 0;
  for (const it of list) { gain += it.gain; covered += (it.end - it.start) / 1000; }
  return {gain, covered, perHour: covered >= 120 ? gain * 3600 / covered : null};
}

export function eta(table, last, perHour) {
  const total = last && requirement(table, last.level);
  if (!total || !perHour || perHour <= 0) return null;
  return Math.max(0, total - last.exp) / perHour * 3600;
}

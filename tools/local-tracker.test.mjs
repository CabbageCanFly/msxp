// Unit tests for the browser-only local tracker (/local): parsing, EXP-table checks, tracking and stats.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
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

test('level resolution needs OCR and table to agree, or continuity with the previous level', () => {
  const {exp, bp} = pair(20, 5000);
  assert.deepEqual(E.resolveLevel(table, 20, exp, bp, null), {level: 20, evidence: 'ocr_and_table'});
  assert.equal(E.resolveLevel(table, 26, exp, bp, null).level, null);  // Misread badge, no history.
  assert.deepEqual(E.resolveLevel(table, null, exp, bp, 20), {level: 20, evidence: 'table_continuity'});
  assert.equal(E.resolveLevel(table, null, exp, bp, null).reason, 'level_unreadable');
  assert.equal(E.resolveLevel(table, 150, 123, 0, null).evidence, 'ocr_only');
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

test('long gaps and level jumps start baselines; different characters pause for the user', () => {
  const gap = run([r(0, 20, 5000), r(20, 20, 5100), r(500, 20, 6000), r(520, 20, 6050)]);
  assert.deepEqual(gap.accepted.map((a) => a.gain), [null, 100, null, 50]);
  const other = run([r(0, 20, 5000), r(20, 20, 5100), r(40, 35, 100), r(60, 35, 200)]);
  assert.equal(other.out[3].status, 'identity_check');
  assert.equal(other.state.last.level, 20);  // The accepted state is preserved.
  // A new session keeps the previous reading only as a reference for this check.
  const fresh = run([r(1000, 35, 100), r(1020, 35, 200)], {last: null, pending: null, reference: r(0, 20, 5000)});
  assert.equal(fresh.out[1].status, 'identity_check');
  assert.deepEqual(E.acceptBaseline(fresh.out[1].suspect).accept[0].kind, 'baseline');
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

test('HUD geometry: labels bind to one status bar; brackets are found by colour', () => {
  const frame = {width: 1368, height: 800};
  const w = (text, x0, y0, x1, y1) => ({text, x0, y0, x1, y1});
  const words = [w('HP(223', 504, 769, 542, 778), w('MP!', 613, 769, 634, 778), w('EXP', 725, 769, 747, 778),
    w('5.477127.09%1', 750, 771, 824, 778), w('LV.', 297, 775, 315, 788)];
  const found = H.locate(words, frame);
  assert.equal(Math.round(found.exp.x0), 723);  // The label stays in the box; each scan trims it in pixels.
  assert.ok(found.level.x0 >= 315);
  assert.ok(H.locate(words.filter((t) => t.text !== 'LV.'), frame).level.x1 < 504);  // Orange-tile search left of HP.
  assert.ok(found.level.x0 >= 315);
  assert.equal(H.locate(words.filter((t) => t.text !== 'EXP'), frame).reason, 'exp_label_not_found');
  assert.equal(H.locate([...words, ...words.map((t) => ({...t, y0: t.y0 - 300, y1: t.y1 - 300}))], frame).reason, 'multiple_huds');
  // A synthetic strip: white digits on grey with two olive brackets.
  const width = 40, height = 10, data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) data.set([90, 90, 90, 255], i * 4);
  for (const x of [12, 30]) for (let y = 2; y < 9; y++) data.set([160, 185, 130, 255], (y * width + x) * 4);
  assert.deepEqual(H.brackets({width, height, data}, {x0: 0, y0: 0, x1: width, y1: height}), [{x0: 12, x1: 13}, {x0: 30, x1: 31}]);
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

test('daily summaries keep the last reading of each local day and add up its gains', async () => {
  const S = await import(new URL('store.js', web));
  const morning = new Date(2026, 10, 10, 8).getTime(), evening = new Date(2026, 10, 10, 21).getTime();
  let day = S.foldDay(undefined, {characterId: 1, at: evening, level: 21, exp: 50, bp: 20, gain: 300});
  day = S.foldDay(day, {characterId: 1, at: morning, level: 20, exp: 900, bp: 4000, gain: 100});  // An older reading arrives later.
  assert.deepEqual(day, {characterId: 1, day: '2026-11-10', gain: 400, at: evening, level: 21, exp: 50, bp: 20});
  assert.equal(S.dayOf(new Date(2026, 0, 2, 23, 59).getTime()), '2026-01-02');
  assert.ok(S.DETAIL_MS > 24 * 3600e3 && S.DETAIL_MS <= 25 * 3600e3);
});

test('overlay options use the live URL parameters; unknown values fall back', () => {
  const o = V.overlayOptions('?layout=chart&theme=blue&name=twitch&interval=1800&range=60&background=ABCDEF&bg=green&evil=1');
  assert.deepEqual([o.layout, o.theme, o.name, o.interval, o.range, o.background, o.bg], ['chart', 'blue', 'character', '1800', '1440', 'abcdef', 'green']);
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

test('panel lines beside the level badge give stable per-line keys', async () => {
  const G = await import(new URL('glyphs.js', web));
  const width = 200, height = 40, data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) data.set([50, 55, 60, 255], i * 4);
  const paint = (x0, y0, x1, y1, rgb) => { for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) data.set([...rgb, 255], (y * width + x) * 4); };
  paint(10, 15, 30, 28, [240, 130, 30]);  // Orange badge.
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

test('pickup messages: outlined text lines, stack shifts and parsing', async () => {
  const P = await import(new URL('pickups.js', web));
  const width = 200, height = 60;
  const frame = (lines) => {
    const data = new Uint8ClampedArray(width * height * 4);
    for (let i = 0; i < width * height; i++) data.set([120, 170, 220, 255], i * 4);  // Sky, no pure black.
    // Like the game font: 1-pixel light strokes, each with a pure-black outline on both sides.
    lines.forEach(([y, seed]) => {
      for (let x = 60; x < 196; x += 3) if ((x + seed) % 7 !== 0) for (let yy = y; yy < y + 7; yy++) {
        data.set([0, 0, 0, 255], (yy * width + x - 1) * 4); data.set([235, 235, 235, 255], (yy * width + x) * 4); data.set([0, 0, 0, 255], (yy * width + x + 1) * 4);
      }
    });
    return {width, height, data};
  };
  const a = P.messageLines(frame([[48, 1]]));
  assert.equal(a.length, 1);
  const twoSame = P.messageLines(frame([[36, 1], [48, 1]]));  // Same message again pushes the first up.
  assert.equal(P.newLines(a, twoSame), 1);
  const plusTwo = P.messageLines(frame([[12, 1], [24, 1], [36, 2], [48, 3]]));  // Two new lines in one frame.
  assert.equal(P.newLines(twoSame, plusTwo), 2);
  assert.equal(P.newLines(plusTwo, plusTwo), 0);
  assert.equal(P.messageLines(frame([])).length, 0);
  assert.deepEqual(P.parseMessage('You have gained mesos (+10)'), {kind: 'mesos', amount: 10});
  assert.deepEqual(P.parseMessage('You have gained mesos (+1,250)'), {kind: 'mesos', amount: 1250});
  assert.deepEqual(P.parseMessage('Orange Mushro... x1 earned. (Etc)'), {kind: 'item', name: 'Orange Mushro', cut: true, count: 1, tab: 'Etc'});
  assert.equal(P.parseMessage('Arrows for Bows x3 earned. (Use)').count, 3);
  assert.equal(P.parseMessage('Hello world'), null);
  const items = [{name: 'Orange Mushroom Cap', tab: 'Etc'}, {name: 'Green Mushroom Cap', tab: 'Etc'}, {name: 'Blue Mushroom Cap', tab: 'Etc'}, {name: 'Blue Mushroom Hat', tab: 'Equip'}];
  assert.equal(P.resolveItem(items, {name: 'Orange Mushro', cut: true, tab: 'Etc'}).name, 'Orange Mushroom Cap');
  assert.equal(P.resolveItem(items, {name: 'Blue Mushroom', cut: true, tab: 'Etc'}).name, 'Blue Mushroom Cap');  // The tab separates the cap from the hat.
  assert.equal(P.resolveItem(items, {name: 'Blue Mushroom', cut: true, tab: null}), null);  // Ambiguous without the tab: no guess.
});

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
  const S = await import(new URL('pickup-session.js', web));
  assert.deepEqual(S.lineParts('Leather:1 eamed. (Etc)'), {amount: null, name: 'Leather', count: 1, tab: 'Etc'});  // "x1" read as ":1".
  assert.deepEqual(S.lineParts('Tree Branch x2 earned. (Etc)'), {amount: null, name: 'Tree Branch', count: 2, tab: 'Etc'});
});

test('pickup message font: learned glyphs read later lines, misaligned lines are refused', async () => {
  const F = await import(new URL('message-font.js', web));
  // Three made-up 3x7 glyphs drawn into a line mask, two empty columns apart (five for a space).
  const shapes = {a: ['111', '101', '101', '101', '101', '101', '111'], b: ['100', '100', '111', '101', '101', '101', '111'], 1: ['010', '110', '010', '010', '010', '010', '111']};
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
  assert.equal(F.learnLine(font, line('ab'), 'ab'), true);
  assert.equal(F.readLine(font, line('ba')), 'ba');
  assert.equal(F.readLine(font, line('b1 a')), 'b? a');  // An unknown glyph is "?", never a guess.
  assert.equal(F.learnLine(font, line('ab'), 'ba'), false);  // Glyphs that look like other characters.
  assert.equal(F.learnLine(font, line('a1'), 'a'), false);  // Glyph and character counts differ.
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

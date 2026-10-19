import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../src/exp_tracker/web/admin-time.js', import.meta.url), 'utf8');
const {localCandidates, localTimestamp, localFields, offset, timezone, when} = await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
function inZone(zone, run) {
  const before = process.env.TZ; process.env.TZ = zone;
  try {run();} finally {if (before === undefined) delete process.env.TZ; else process.env.TZ = before;}
}
test('local date and seconds convert to an aware UTC instant with seasonal offsets', () => inZone('America/Toronto', () => {
  assert.equal(timezone(), 'America/Toronto');
  assert.equal(localTimestamp('2026-10-19','17:30:04'), '2026-10-19T21:30:04.000Z');
  assert.equal(localTimestamp('2026-01-19','17:30:04'), '2026-01-19T22:30:04.000Z');
  assert.equal(localTimestamp('2026-01-19','17:30'), '2026-01-19T22:30:00.000Z');
  assert.deepEqual(localFields('2026-10-19T21:30:04.123456Z'), {date:'2026-10-19',time:'17:30:04'});
  assert.equal(offset('2026-10-19T21:30:04Z'), 'UTC-04:00');
  assert.match(when('2026-10-19T21:30:04Z'), /2026/);
}));
test('repeated fall time requires a deliberate choice, never the default Date interpretation', () => inZone('America/Toronto', () => {
  const values = localCandidates('2026-11-01', '01:30:05');
  assert.deepEqual(values, ['2026-11-01T05:30:05.000Z','2026-11-01T06:30:05.000Z']);
  assert.throws(() => localTimestamp('2026-11-01','01:30:05'), /occurs twice/);
  assert.throws(() => localTimestamp('2026-11-01','01:30:05','wrong'), /occurs twice/);
  assert.equal(localTimestamp('2026-11-01','01:30:05',values[1]), values[1]);
  assert.equal(offset(values[0]), 'UTC-04:00'); assert.equal(offset(values[1]), 'UTC-05:00');
}));
test('nonexistent spring time is rejected instead of moving the clock forward', () => inZone('America/Toronto', () => {
  assert.deepEqual(localCandidates('2026-03-08','02:30:00'), []);
  assert.throws(() => localTimestamp('2026-03-08','02:30:00'), /does not exist/);
}));
test('half-hour DST folds also require an explicit choice', () => inZone('Australia/Lord_Howe', () => {
  assert.deepEqual(localCandidates('2026-04-05','01:45:00'), ['2026-04-04T14:45:00.000Z','2026-04-04T15:15:00.000Z']);
  assert.throws(() => localTimestamp('2026-04-05','01:45:00'), /occurs twice/);
}));
test('quarter-hour zones and UTC work without assuming whole-hour offsets', () => {
  inZone('Asia/Kathmandu', () => {
    const stamp = localTimestamp('2026-10-19','17:30:00');
    assert.equal(stamp,'2026-10-19T11:45:00.000Z'); assert.equal(offset(stamp),'UTC+05:45');
  });
  inZone('UTC', () => assert.equal(localTimestamp('2026-10-19','17:30:00'), '2026-10-19T17:30:00.000Z'));
});
test('a skipped calendar day cannot become a different date', () => inZone('Pacific/Apia', () => {
  assert.throws(() => localTimestamp('2011-12-30','12:00:00'), /does not exist/);
}));
for (const [date,time] of [['',''],['2026-02-30','12:00:00'],['2026-10-19','24:00:00'],['2026-10-19','12:60:00'],
  ['2026-10-19','12:00:60'],['2026-1-19','12:00:00'],['0000-01-01','12:00:00'],['2026-10-19','noon']])
  test(`invalid or missing local time ${date} ${time} never defaults to now`, () => assert.throws(() => localTimestamp(date,time)));

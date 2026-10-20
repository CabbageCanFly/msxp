# Rolling EXP history

The [schema-8 retention feature](24h-retention.md) adds persistent causal checkpoints
and expires old raw evidence. Its policy supersedes the original no-deletion
implementation notes below; public window/endpoint calculations remain unchanged.

The player page now has **EXP tracked · Last 24h** and a **30 min** bar view
covering a rolling 24 hours. The existing 1-minute/30-minute-axis and
5-minute/2-hour-axis views, Level % chart, recent pace and strict ranking rules
remain separate. This is captured EXP history, not exact EXP earned today.

## What contributes

`GET /api/players/CHANNEL/history` returns 48 compact buckets and a total for the
explicitly selected character, including that character's earlier sessions.
An individual interval must pass the existing source, freshness, assignment,
level, chronology, adjacency, crop and numerical-quarantine gates. Both endpoints
must lie within the rolling window. Whole intervals straddling its lower boundary
are excluded rather than guessing how much was earned inside it.

The shared `product.interval_gain()` preserves the existing bar interpretation:
consistent strict EXP endpoints use their integer difference; otherwise supported
same-level percentage endpoints use exact rational conversion with the community
requirement. Strict and recovered evidence still pass the same existing safeguards.
Missing/disputed requirements cannot supply an EXP amount. Two-decimal percentage
precision and OCR uncertainty remain; a displayed zero does not prove zero actual
gain. Requirement versions and interval-basis counts are retained in the API.

There is no interval across a manual restart, character/session/source change,
failed or missing capture, stale-at-capture frame, quarantine, loss or level-up.
Confirmed losses start a new baseline; they are neither earned EXP nor subtracted
from this sum of eligible positive/zero intervals. Only the existing validated
coordinator-owned scheduled rotation can link run 60 to next-run 1. Separate
eligible pieces may be summed without connecting them or assigning gains to holes.

The rolling axis uses aware UTC timestamps and always spans 86,400 seconds,
including daylight-saving changes. Stopping capture does not stop the clock:
old intervals age out. Calendar-day totals and session averages remain absent.
The short charts retain their existing saved-capture axes and 640-attempt limit.

Orange bars show eligible gains; faded bars have partial captured coverage;
baseline dashes mean unknown. An orange zero requires a real comparable zero
interval. Within each eligible interval only, a boundary-straddling gain is
distributed by elapsed overlap for visualization. That allocation is not observed
gain timing, trusted accounting or input to pace/ranking. The total sums whole
eligible intervals, independently of their visual allocation. Tooltips retain
coverage, date/time and approximation details; the summary stays compact.

## Bounded implementation

No schema migration, materialized totals or historical payload edits. The existing
`diagnostic_time(session_id, attempted_at, id)` index selects relevant runs.
Each run is decoded through the existing sanitized snapshot decoder, at most 60
attempts at a time. Level confirmation and percentage quarantine retain their
causal state across batches; a page boundary cannot reset a pending decrease.
Manual/unlinked runs reset that state. Clean rotation chains replay from their
actual beginning, including earlier context, so an unresolved anomaly before the
window cannot become an accepted baseline just because it aged out of a page.

Limits: 1,024 contextual runs, 65,536 contextual attempts and 128MiB raw attempt
payloads. Exceeding a limit returns `history_limit`, unknown buckets and no total,
rather than a partial figure or zero. Very long continuous chains can eventually
reach these limits; a separately designed persisted causal checkpoint would be
needed to avoid that. There is no silent retention/deletion.

### Run-size / pagination audit

The 60-row snapshot does **not** truncate any run created by supported ingestion.
Schema 3 creates
`CHECK(attempt_index BETWEEN 1 AND 60)` plus `UNIQUE(run_id, attempt_index)`;
schema 4 retains both constraints. `Diagnostics._append()` additionally requires
integer indices inside 1..60 and contiguous attempt order, enforcing at most 60
rows through supported ingestion. The coordinator
rotates to a new run instead of extending this domain.

Regression tests attempt indices 61, 100 and 150 through both the API and direct
SQL, and duplicate an existing SQL index. Every insertion is rejected, original
rows remain unchanged, and the sanitized snapshot returns all 60 event IDs in
chronological order. Legal 61/100/150-attempt histories across scheduled rotations
are also compared with full causal replay, including a pending decrease at run
60 followed by loss confirmation at next-run 1, and a large unresolved anomaly
across that boundary. Totals, interval counts, coverage and bucket sums agree.
The existing >640-attempt, restart/identity and work-limit tests remain in place.

The SQLite table is not `STRICT`: direct SQL can store fractional indices that
satisfy the range CHECK and uniqueness. A synthetic 61-row run using this loophole
reproduced a `ready` result from only its last 60 rows. The reader now checks its
existing full-run count before decoding and returns `history_limit`, unknown
buckets and no total for **any** oversized run. Tests cover 61, 100 and 150 rows
of this unsupported SQL data. No original database was modified; both saved
databases pass `integrity_check` and have maximum run lengths 55 and 60.

No pagination code or schema change is justified for supported runs. The only
runtime change is this fail-closed count guard and its comment. If a future
migration permits more than 60 attempts per run,
it must introduce bounded chronological pagination before changing that constraint;
these regression tests intentionally fail if the invariant is weakened.

The final private audit is `private/rolling-history/pagination-audit-final/audit.json`.
All three actual summaries exactly equal the original audit: single-stream
Telfer1 57,442.9428 EXP / 97 intervals; multi-stream Telfer1 156,762.4334 / 210;
Shiphtur 25,265 / 103. All six original input hashes match. Query times were
37–44ms, 65–67ms and 38–39ms respectively. The unchanged synthetic 6,000-attempt
workload took 2.02–2.06s, 1.82MiB incremental traced Python peak, ~49MiB process
RSS and a 13,564-byte response. Differences from earlier timing are ordinary
workstation measurement variation, not a changed algorithm.
Final Chrome evidence is under `private/rolling-history/pagination-browser-final/`:
saved SQLite polling, 24h expiry, desktop/mobile charts and the overlay pass.
Follow-up changes are confined to the count guard/comment in `rolling_history.py`,
12 synthetic regression cases in `tests/test_rolling_history.py`, and this audit
section. No frozen inputs, schema, recognition code or UI behavior changed.
Follow-up validation: **1,311 Python tests passed, zero skipped**; **65 Node
tests passed**; **38 focused history tests passed**; `git diff --check` passed.

```powershell
.\.venv\Scripts\python -m pytest tests/test_rolling_history.py -q
.\.venv\Scripts\python private/rolling-history/audit.py private/rolling-history/pagination-audit-new
node tools/product.browser.mjs http://127.0.0.1:8781 private/rolling-history/pagination-browser-new --verify-rolling telfer1
```

The read-only endpoint is opt-in with the existing product server. It returns no
raw OCR, frame hashes, local paths, playback URLs or credentials. An eight-entry
compact server cache expires after 30s and invalidates on new committed attempts
or selected-character changes. Aggregations are serialized; normal player/overlay
polling does not wait on this history lock. The player makes one separate history
request at a time, on new observations or every 30s. Cached request failures keep
their dated value visibly saved. A standalone history query does not start capture.

## Actual saved evidence

No new OCR inference or Twitch connection was used. Results below are read-time
availability/derived sums on familiar saved evidence, not independently verified
earned EXP or new OCR accuracy scores. Clocks in browser replay are explicitly
as-of original source timestamps; observations are never retimed.

| Telfer1 capture | Attempts | Eligible percentage observations | Gain intervals | Tracked EXP | Captured interval time |
|---|---:|---:|---:|---:|---:|
| 03:01 run, completed | 40 | 36 | 31 | ~26,428 | 464.893s |
| 03:20 run, interrupted | 10 | 9 | 7 | ~6,273 | 105.038s |
| Both new runs | 50 | 45 | 38 | ~32,701 | 569.931s |

Five unavailable percentages remain unavailable; no grammar/model rules changed.
The 585.127-second receipt-time gap between these runs contributes **no** EXP or
coverage. Interruption preserves eligible historical intervals already captured.

At 03:23:15 UTC, the existing single-stream database contains 193 attempts over
eight runs for the selected character. Its 24h projection is **~57,443 EXP** from
97 intervals / 982.769 captured seconds: 92 percentage-derived intervals and five
direct EXP intervals. The rest of the day remains unknown. Existing multi-stream
history separately gives Telfer1 ~156,762 EXP / 210 intervals and Shiphtur 25,265
EXP / 103 intervals. Telfer1's two validated scheduled-rotation edges account for
two additional intervals, not manually restarted-run gaps. The earlier 65→66
transition supplies no cross-level gain. No databases were silently merged.

Private detailed audit: `private/rolling-history/audit-01/audit.json`.
Both source databases and the four new capture/operator logs retained their
SHA256 hashes. Original observations, models, annotations and requirements are
unchanged; no trusted observations were written.

## Performance and checks

On this workstation, three uncached projections took 40–43ms for the 193-attempt
single-stream history, 41–43ms for multi-stream Shiphtur and 71–76ms for multi-stream
Telfer1. A separate synthetic 6,000-attempt / 100-rotation-run SQLite history
returned 5,760 eligible intervals covering 24h in 2.16–2.46s; mean process CPU
was ~1.96s/query. Incremental traced Python peak allocation was 1.82MiB; whole
process RSS after projection ~48.8MiB. Database size 3.52MiB; response 13.2KiB.
The actual query plan uses the existing time/session indexes. Synthetic payloads
are smaller than many live OCR payloads; these are projection measurements, not
capture benchmarks, concurrent 25-player capacity or low-end VPS guarantees.

SQLite-backed Chrome checks passed for the saved new Telfer1 runs: loading all
48 buckets, polling the second committed run into the total and chart without
navigation, retaining missing buckets, and expiring history after two days to
unknown rather than zero. The separate existing two-stream/clean-rotation browser
regression passed all four comparison windows, bucket controls, stale states and
the unchanged transparent 500×160 overlay. No console errors, external browser
requests or horizontal overflow were observed.

Reviewed screenshots, all private:

- `private/rolling-history/browser-final/rolling-24h-desktop.png`
- `private/rolling-history/browser-final/rolling-24h-mobile.png`
- `private/rolling-history/browser-final/rolling-expired.png`
- `private/rolling-history/browser-final/rolling-overlay.png`
- `private/rolling-history/browser-windows/` for the two-stream regression.

Tests cover >640 attempts, streaming/full causal decision parity, scheduled
rotations, manual restarts, same-character archived sessions, character isolation,
missing/stale/multiple-HUD frames, source changes, losses/anomalies/level changes,
unsupported requirements, large and zero gains, exact bucket conservation, UTC/DST,
rolling edges, limits, cache invalidation, polling and legacy schema-3 read access.
Final validation: **1,299 Python tests passed, zero skipped**; **65 Node tests
passed**; the final focused history suite passed 26 tests. `git diff --check`
passed. An earlier restricted run skipped the localhost socket test and could not
launch Chrome; the final full suite and Chrome checks ran with localhost access.
Character changes also suppress any previously cached different-character total
while its replacement request is pending.

Changed files: `src/exp_tracker/rolling_history.py`, `diagnostic_evidence.py`,
`diagnostic_percentage.py`, `diagnostics.py`, `product.py`, `server.py`;
`src/exp_tracker/web/player.html`, `product.js`;
`tests/test_rolling_history.py`, `test_diagnostic_history.py`;
`tools/product.test.mjs`, `product.browser.mjs`, `product_updates_fixture.py`;
`README.md`, `docs/product-experience-principles.md`,
`docs/gaming-companion-statistics.md` and this guide. The audit script, results,
source hashes, replay databases and screenshots remain ignored under
`private/rolling-history/`.

## Try it

```powershell
# Read existing actual data; this does not initiate capture.
.\.venv\Scripts\python -m exp_tracker.server --db private/local-alpha/live/telfer1.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/stream/telfer1'
# Select 30 min under EXP history for the rolling 24-hour axis.

# Non-overwriting private replay, original timestamps and explicit as-of clock.
node tools/product.browser.mjs http://127.0.0.1:8781 private/rolling-history/review-new --verify-rolling telfer1
node tools/product.browser.mjs http://127.0.0.1:8782 private/rolling-history/windows-new --verify-windows telfer1
.\.venv\Scripts\python private/rolling-history/audit.py private/rolling-history/audit-new
.\.venv\Scripts\python -m pytest -q -rs
node --test tools/*.test.mjs
```

The private audit script requires the saved local datasets and writes a new
synthetic benchmark database only. When original capture timestamps leave the
real current 24h window, the ordinary server correctly shows no tracked amount;
use the explicit as-of browser replay to inspect these historical examples.
Archived raw history remains available through Advanced. Exact all-day earnings,
unobserved gameplay, level-up boundary EXP, session average and trusted totals
cannot be inferred from this diagnostic history.

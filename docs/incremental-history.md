# Incremental causal history and shared player cards

Follow-up to the [homepage performance investigation](homepage-performance.md). Public
numbers, eligibility policy and APIs are unchanged; the work per request is not.
Timings are **synthetic local latency** on the same Windows desktop, not a VPS claim.

## Root cause

Both the 24h tracked history (`aggregate`) and the 65-minute recent view
(`recent_snapshot`) rebuilt level, quarantine and interval state by replaying every
run of the continuous rotation chain from the session start. Every new attempt changed
the cache key, so one capture cost a whole-session replay, which grew with uptime. The
character API had no cache at all: each 2-second poll repeated the replay, the 640-row
snapshot and `player()` for every viewer.

## Architecture

`rolling_history.replay()` is the only path for both projections. It runs the exact
full-replay sequence (`select_runs`: time-range runs plus verified rotation
predecessors, in rowid order) and the same per-run `step`. Its state is that of
`project(state=)`, `review(state=)` and `collect(state=)`, plus intervals or recent rows.

After a run is **settled**, a deep copy of the state is saved as the channel's
checkpoint. Settled means all of the run's attempts were read, the run is closed or no
longer the last run, and its final row's quarantine deadline has passed (`review()`
re-labels an unexpired final row from the clock). A later request resumes from that
checkpoint and replays only the runs after it: normally just the open run, at most 60
attempts. Settled runs are replayed again only when the checkpoint is invalid.

Window-dependent output is never checkpointed. Totals, nested windows, 30-minute
buckets, chart intervals and boundary counts are recomputed from the retained
intervals at each request's `now`, so windows expire with no new capture. The recent
view retains its rows and reapplies the request's 65-minute cutoff.

Checkpoints live in `server.checkpoints` (two per channel, at most 64, oldest evicted,
guarded by one lock). Callers that pass no store, such as tests and tools, keep the
original full replay.

## Validity, invalidation and pruning

Attempts are INSERT-only and contiguous inside an unfinished run. A summary is written
once and closes the run, and the HTTP server opens SQLite read-only. A checkpoint is
reused only when **all** of the following hold; otherwise the request is a full replay
from the first run and replaces the checkpoint:

| Condition | Detects |
|---|---|
| Key = (kind, channel, selected character[, open session]) | Character or session change; a process restart has no checkpoints |
| `now` ≥ checkpoint time | Clock regression |
| The full-replay run sequence still **begins with** the covered runs | Restart chains leaving the window, backfilled or newly linked predecessors |
| Each covered run keeps its configuration, summary, attempt count and last attempt ID | Late appends to an older unfinished run, a summary written later, out-of-band row insert or delete |
| Work limits are re-applied with the restored receipt | `history_limit` stays identical to a full replay; never a truncated total |

Readings before the 24h start are pruned when saved, except the last usable endpoint
before it. A later window's boundary-crossing pair begins there, and
`boundary_intervals_excluded` counts that pair. Until the parity fix described in
[VPS readiness](vps-readiness.md#saved-telfer1-log-failures), a checkpoint saved at
the comparison clock dropped that reading. Pairs ending earlier never re-enter a
window's gains. Duplicate-detection sets, quarantine anchors and level context
are kept exactly, bounded by the existing 1,024-run and 65,536-attempt limits.
An in-place SQL edit that keeps a covered run's count and last ID is outside the
persistence model and is not detected until the process restarts.

## Shared player cards

The homepage directory cache entry is now `(revision, card, extras)`, built by
`Diagnostics.card()`. The character API uses the same entry, with chart history and
lifecycle in `extras`, and the same revision key and 10-second rolling-window expiry.
`refresh()` ages it per request, as the homepage already did, so every viewer of a
channel shares one `snapshot(640)` + `player()` computation per revision or expiry.
The directory now also passes the existing per-revision historical ETA cache (bound
raised from 8 to 25 channels).

A homepage request rebuilds stale cards for at most `REBUILD_BUDGET_SECONDS=1.5`:
channels without a card first, then changed revisions, then the oldest expired cards.
Remaining cards are served as their last completed card, with real ages. Tracked-EXP
packets are computed after `directory_lock` is released, so character pages wait only
for card rebuilds.

## Parity evidence

Acceptance condition: incremental output **equals** full causal replay for the same
evidence and `now`. Compared: the entire tracked packet (intervals, exact gain
fractions, nested windows, current-level windows, 48 buckets, chart intervals,
exclusion counts, receipts, current level), the entire recent snapshot (rows, reviews,
receipts, historical ETA inputs) and the resulting `player()` output.

| Saved log (private) | Streamed steps | Full comparisons | Result |
|---|---:|---:|---|
| Emmies | 418 | 97 | exact |
| Niru | 1,458 | 195 | exact |
| Telfer1 | 1,874 | 250 | exact |

Each sweep then advances the clock by 1 s, 10 min, 65 min, 2 h and 25 h without new
captures, then regresses it. The logs contain missing and malformed OCR, level-ups,
rotations, unvalidated restarts and multi-hour inactivity.
`private/incremental-work/sweep.py` reproduces them. The suite runs bounded versions in
`tests/test_incremental_history.py`, plus synthetic cases: every append across
rotation, manual restart, duplicate frame, two-capture loss and recovery, level-up and
source change; window expiry and clock regression; resumption of only the open run;
late appends, late summaries and out-of-band row loss; character change and work limit;
bounded store; one shared card per revision; and a spent rebuild budget.

## Measurements

`tools/benchmark_homepage.py` builds full-day 20-second synthetic channels (4,321
attempts, 73 rotated runs). It reports CPU and RSS, and runs a bounded viewer load:
20 browser-like clients (5 s timeout, next poll 2 s after each response) while one
capture per channel is appended every 20 s. It waits for abandoned requests to drain
before the next measurement. "Before" is the previous commit (`13b883e`).

| Per changed channel | Before | After |
|---|---:|---:|
| 24h tracked replay | ≈0.8–1.7 s | ≈85 ms |
| 65-minute recent view | ≈0.6–1.3 s | ≈25 ms |
| Card (`snapshot(640)` + `player()`, unchanged code) | ≈0.25 + 0.3 s | same, now shared |
| Character API, no new data | 0.82–1.78 s | 19–34 ms |

| Channels | Before: homepage, all new | After: homepage, all new | Before: 20 viewers | After: 20 viewers (completed / timed out) |
|---:|---:|---:|---|---|
| 1 | 1.6–3.4 s | 0.6 s | 0 / 95 | 297 / 0, p95 ≈ 0.2 s |
| 5 | 8.4 s | 2.4 s | 0 / 96 | 191 / 0, p95 ≈ 2.7–3.7 s |
| 10 | 16.2 s | 3.1 s | 0 / 95 | 82 / 39 |
| 25 | 42.0 s | 4.2 s | not run: ≈42 s per request | see below |

The before runs for 5–10 channels under load completed no requests. The before
1-channel row overlapped another local replay process, which is why it is higher than
the investigation's 1.6 s. Cold start is still a full replay per channel: ≈18 s at
5 channels, 37 s at 10 and 94 s at 25. Process RSS was 90–383 MiB. Retained
checkpoints for one full-day channel measured 7.4 MiB (24h) + 2.1 MiB (recent), mostly
interval records.

A second run after moving tracked packets outside `directory_lock` measured:

| Channels | Homepage, all new | Character page while homepage rebuilds | 20 viewers (completed / timed out) | CPU s/s |
|---:|---:|---:|---|---:|
| 5 | 2.1 s | 1.6 s (1.9 s before the lock change) | 198 / 3, p95 2.5–4.5 s | 0.63 |
| 25 | 4.1 s | 2.1 s (3.9 s) | 2 / 95 | 0.96 |

At 25 channels one process is CPU-bound. Card rebuilds keep the GIL near one core, so
most viewer requests still exceed the 5-second browser timeout. In that run, abandoned
requests took 67 s to drain after the load ended.

The homepage main thread is not a bottleneck. At 25 cards, headless Chrome measured
12.6 ms of task time per second (2.1 ms script, 2.7 ms layout) and 5.3 ms per
`renderBoard()` including forced layout, with 1,034 DOM nodes. The wholesale 1-second
rebuild was left unchanged.

## Remaining limits

- **The fixed card cost is now the ceiling.** `snapshot(640)` + `player()` is ≈0.5 s
  of CPU per rebuild, independent of history length. Under the GIL, revision changes
  plus the existing 10-second rolling-window expiry exceed one core beyond roughly
  10 active channels. The budget bounds request latency, but cards then age beyond
  10 s and queued viewers still time out under load.
- **The historical-ETA fallback still replays the session.** When a channel has no
  eligible interval in the last 65 minutes, restoring its dated ETA replays the whole
  session once per new attempt (cached per revision). Its 4,096-row window (≈12.5 KiB
  per decorated row, ≈50 MiB) is too large to checkpoint.
- **Some changes rebuild from scratch.** Cold start, restart chains whose earliest run
  leaves the window, and any invalidation rebuild once (≈0.8 s per full day).
- **Abandoned requests still run** to completion. They now usually find a warm cache.

## Recommended next milestone toward a VPS

1. Make the card cheap: reuse the incremental recent rows for the 640-row snapshot
   inputs, or checkpoint `player()`'s window collectors, with the same parity harness.
2. Move card and tracked refresh to one background refresher per process, so request
   threads only read immutable published snapshots, and pre-serialize the homepage
   body once per refresh for all viewers.
3. Then measure 100 synthetic viewers on a 4-vCPU Linux VM. Use one process per core
   only after the shared snapshot exists; per-process caches would multiply cold
   starts.

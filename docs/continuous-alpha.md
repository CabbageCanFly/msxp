# Continuous local tracking and history

The multi-alpha coordinator supports **2–25 explicit assignments**, bounded mode
and opt-in continuous capture. One acquisition/OCR job runs at a time, with one
shared database and localhost server. All neural/grammar evidence and percentage
progress remain **EXPERIMENTAL / UNVERIFIED**. No OCR rule/model, EXP requirement,
trusted ingestion, accounting, OBS overlay or leaderboard behavior was changed.

## Run modes

Use the existing private configuration described in [multi-alpha.md](multi-alpha.md).
The sanitized `configs/multi-alpha.example.json` still uses two local videos.
Always run from the repository root with the existing venv/models/tools.

```powershell
# Original finite mode: configured count remains 1..60 per channel.
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --check
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json

# Continuous: configured count is replaced by 60-attempt run rotation.
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --continuous

# Explicit continuous stop conditions: per-channel total and/or monotonic seconds.
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --continuous --max-attempts 125 --exit-after-capture
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --continuous --stop-after-seconds 300 --exit-after-capture
Start-Process 'http://127.0.0.1:8765/streams'
```

Without `--exit-after-capture`, a normally stopped capture leaves the read-only
viewer open until Ctrl+C. Ctrl+C during capture closes owned workers, connections
and HTTP. A time limit stops scheduling new work; an in-flight attempt can finish
within its existing timeouts. No catch-up queue is created. `--check` never
connects or writes. Twitch still requires explicit per-assignment `authorized:true`.

For **local videos only**, `--offline-fast-test` explicitly lowers the interval
floor to three seconds. Normal defaults/range remain 15s / 5–300s. It rejects the
entire configuration if any source is Twitch, including an authorized source.

```powershell
# Existing private smoke config requests 3s and 8s; preserve it and its output DB.
# For another capture, copy/edit the config to use a NEW private database path.
.\.venv\Scripts\python tools/multi_alpha.py --config private/continuous-alpha/actual-01/config.json --offline-fast-test --check
.\.venv\Scripts\python tools/multi_alpha.py --config private/continuous-alpha/actual-01/config.json --continuous --max-attempts 3 --offline-fast-test --exit-after-capture

# Fast scheduler/SQLite rollover checks, no video or real waiting:
.\.venv\Scripts\python -m pytest tests/test_multi_alpha.py tests/test_diagnostic_history.py tests/test_diagnostic_progress.py -q
```

| Development workload | Suggested requested interval |
|---|---|
| Virtual-clock rollover | Simulated; no real waiting |
| Single-video investigation | 3–5s with explicit fast mode; bounded multi-alpha requires at least two assignments, or use the existing standalone runner at >=5s |
| Two videos | Start at 8–10s, then inspect achieved cadence |
| Permitted Twitch trial | 15–30s initially |
| Continuous operation | Capacity-dependent; never assume the request is achieved |

Fast mode changes scheduling eligibility, not decoder/model speed. Video offsets
remain `start + real coordinator elapsed time`; playback is **not** advanced by
an artificial multiplier. Real monotonic scheduling, UTC attempt/receipt times,
requested offsets and unverified source PTS remain distinct. Broadcast delay and
character identity are unknown. Virtual tests mark attempts `timing_mode:simulated`,
use no fabricated requested UTC schedule time, and cannot produce progress/pace.
Their databases are isolated pytest fixtures, not capture benchmarks.

## Rotation and restart safety

Each channel has one active run and consecutive indices 1..60. Just before the
next capture, a fresh UUID and exclusive private output directory are allocated.
The old summary declares `scheduled_rotation` and its successor; the new header
declares its predecessor, coordinator-instance UUID, hashed explicit source
identity and unchanged requirements/OCR configuration. Finalization and successor
binding are **one SQLite transaction**. The next index is 1; the channel's session,
character and due time are retained. Old handles close at rotation, so handles
and queued jobs do not accumulate with uptime.

Only that validated lifecycle permits percentage continuity across run IDs. It
also requires previous index 60 → new index 1, matching source/instance/assignment,
increasing real receipt times and every existing freshness, same-level, ambiguity,
gap and missing-attempt check. A restart gets a new instance and process-start
header, never a rotation exception. A failed/stale attempt, unknown/conflicting
level, decrease, character/session change or excessive gap still breaks progress.
No level-up or exact cross-level gain is inferred.

The existing OS-level DB ownership lock stays held by the coordinator. On restart,
selections are checked, committed history remains, unfinished runs are reported
and new identities start. Historical runs are not rewritten, resumed or silently
marked complete. A persistence failure stops the affected lane and leaves its run
unfinished; other lanes continue where possible. Logs and SQLite have separate
success reporting. A crash between file flush and transaction commit can leave
extra lifecycle lines in private files: preserve them for explicit replay/review,
not automatic recovery. Replay predecessor logs before successors when restoring
a clean rotation chain. Duplicate identical replay remains idempotent.

Per-attempt logs/API now retain requested time, actual monotonic start interval,
whole work duration, delay, skipped deadlines and real/simulated timing mode.
Final summaries report capture/OCR failure counts, committed attempts and achieved
cadence. Terminal warnings identify missed cadence. Skipped deadlines are not
invented captures, and an inaccessible source is not confirmed offline.

## Historical browsing

Open `/dashboard/CHANNEL`, choose **Browse sessions**, select an explicit character
session, optionally select a run and/or UTC time bounds, then **View selection**.
**Earlier attempts**, **Older sessions** and **Older runs** use keyset cursors;
**Return to current** clears filters. Session/run lists return 30 at a time (maximum
50); attempt pages return at most 120. Session ownership is checked against the
channel, and run ownership against the selected session. Closed characters'
history stays accessible. No complete multi-day history is loaded into memory.

Read-only API examples:

```text
GET /dev/api/streams/CHANNEL/sessions?before=SESSION_ID
GET /dev/api/streams/CHANNEL/runs?session=SESSION_ID&before=RUN_CURSOR
GET /dev/api/streams/CHANNEL/diagnostics?session=SESSION_ID&run=RUN_UUID
GET /dev/api/streams/CHANNEL/diagnostics?session=SESSION_ID&before=ATTEMPT_CURSOR
GET /dev/api/streams/CHANNEL/diagnostics?session=SESSION_ID&start=2026-10-17T07:00:00Z&end=2026-10-17T08:00:00Z
```

Use returned `next_before` values unchanged. Time filters use original **attempt**
timestamps, start inclusive/end exclusive; paired bounds may span at most 31 days.
Progress still uses original **receipt** timestamps. Pages preserve insertion/read
order and original event IDs, including failures/out-of-order evidence. The start
of each page is a baseline, not an inferred comparison with excluded history.

Archived pages explicitly suppress current pace while retaining eligible historical
segments, quantization bounds and provisional EXP ranges in the API and segment
details. Strict/recovered markers, sampling gaps, failures and known/unknown-level
boundaries remain distinct; charts draw no interpolated curves. Cached errors age
values and make worker activity unknown. Historical filters never retime data or
change the selected character/session in SQLite.

The directory identifies local videos as videos, shows character/activity/level/
percentage/full EXP/movement and age, and folds raw reason codes into details.
Only in-process coordinator state establishes running/waiting/delayed/failing.
A standalone server reports stopped or previous unfinished/activity unknown;
an unfinished database row does not establish a running worker or Twitch status.

## SQLite, backup and measured cost

Schema **4** adds a diagnostic-attempt session lookup, backfilled solely from its
immutable run assignment, plus recent/time/session/run indexes. Payloads, source
timestamps, UUIDs and trusted tables are preserved. Writer `Store` initialization
applies the transactional migration. HTTP remains read-only and supports schema
3 (slower legacy query) and 4. It never migrates an existing/frozen database.
Back up an existing schema-3 DB before reopening it with a writer. No
retention/deletion is automatic.

Create a consistent new backup, including committed WAL content:

```powershell
.\.venv\Scripts\python tools/backup_database.py private/multi-alpha/tracking.sqlite3 private/backups/snapshot-01.sqlite3
```

The destination must be new and ignored; integrity/FK checks run before success.
An unsuccessful output is retained for inspection, not claimed as a good backup.
For recovery: stop the coordinator/server; preserve the original DB, marker, logs
and config; inspect the backup using the read-only server and `PRAGMA integrity_check`;
then point a copied private config at the backup. For an **exact backup of the same
coordinator-owned DB only**, copy its matching `.sqlite3.multi-alpha.json` marker
beside the restored DB. Never use this to adopt a different/single-stream DB, and
never run the original and restored capture coordinators simultaneously. Restart
creates new run identities; old unfinished evidence remains. The backup tool does
not copy private crops/configuration/logs, which need separate private backups.

Private measurements: `private/continuous-alpha/validation-final.json`,
`history-large-01/measurements.json`, `actual-01/`, and `browser-*/`.

- **Actual two-video run:** six 1920×1080 frames acquired/committed, five unique HUDs
  and five strict pairs. Requested 3s/8s achieved mean start intervals **14.124s /
  14.204s**, with **9 / 3 skipped deadlines**. Mean work **5.669s / 8.172s**. Total
  **41.660s**, sampled CPU **17.094s**, peak process-tree **200.28 MiB** (50ms samples).
  One HUD was missing; no synthetic capture success or accuracy claim.
- **Virtual integration:** 125 attempts per channel, two rotations each, unequal
  intervals, overload/failure isolation and restart are tested with actual SQLite
  lifecycle writes and zero real scheduling waits. Separate tests cover 25 sources,
  interruption, rollback, migrations, old-session ownership and clean rotation pace.
- **Large simulated history:** 25 channels × 12,000 attempts = **300,000 rows**,
  representing 50 video-timing hours/channel at 15s. DB **213,708,800 bytes**.
  Recent SQL median/p95 **0.241 / 0.491ms**, time-window SQL **0.070 / 0.277ms**,
  full bounded projection **12.670 / 24.059ms** (10 samples; p95 reported as max).
  Old joined/sorted query median **122.091ms**. Cached 25-card directory median/p95
  **11.432 / 39.577ms**, cold **585.620ms**. Generation/read workload peak **37.45 MiB**;
  this is not OCR memory or a production stream benchmark.
- At 25 × 15s, the request is **144,000 attempts/day**; at 30s, 72,000. Minimal
  synthetic rows/indexes imply roughly 98 MiB/day at 15s, but actual compact payloads
  averaged **3,804 bytes** in the six-attempt run: roughly **522 MiB/day of payload
  alone**, plus indexes, WAL and roughly 564 MiB/day of JSONL at that cadence.
  Crops/backups add more. These are volume estimates, not measured sustained load.
  A future explicit archive/retention policy is needed before long unattended use.

All figures are workstation measurements. Twenty-five channels are configurable,
but current ~7s sequential work cannot sustain 15s per channel. Slower cadences
also exceed the progress engine's 120s continuity ceiling. Do not treat source
capacity, continuous remote reliability or 1-vCPU VPS performance as validated.

## Validation and next trial

The [unattended failure/recovery audit](unattended-capture-reliability.md) documents
scheduled retries, outage/rotation fault injection, stopped-worker status fixes,
bounded resource-monitor bookkeeping and remaining operational limits.

Validation: **140 focused Python tests plus the final simulated-header regression
passed**, **1,127 full-suite passes** in 127.31s, **zero skips/failures**, and
**39 Node tests passed**. Four final Chrome
checks plus a compact-label recheck produced **37 screenshots** across the simulated
multi-session/25-source data and real six-attempt video data. Mobile directory and archived-session views
were visually inspected. `git diff --check` passed.
Chrome covers a 25-source simulated directory, multiple character sessions, earlier
pages/run filtering, real offline values, polling, stale/cached errors and mobile
overflow. Synthetic data is labeled and never generates authentic progress. All
66 checked original private evidence files remain unchanged. New databases contain
zero trusted observations. No Twitch connection, model download, commit or push
was made during development.

```powershell
.\.venv\Scripts\python -m pytest -q
node --test tools/shadow.test.mjs tools/streams.test.mjs tools/overlay.test.mjs tools/leaderboard.test.mjs
# The size/query benchmark is explicitly synthetic; choose a new output directory:
.\.venv\Scripts\python tools/benchmark_diagnostic_history.py --directory private/continuous-alpha/history-next --attempts-per-channel 12000
```

Next: James can configure **two authorized Twitch sources**, first use `--check`,
then conduct a bounded 12-attempt/15–30s trial. Inspect achieved cadence, failures,
memory, both dashboards and frozen human review. After that, explicitly choose a
continuous stop duration. Do not promise 25-channel cadence or promote neural
values based on this engineering validation. Level recognition, clipped numeric
fields, unknown identity/source freshness and display semantics remain uncertain.

Changed files: `tools/multi_alpha.py`, `shadow_capture.py`,
`benchmark_diagnostic_history.py`, `backup_database.py`; `src/exp_tracker/diagnostics.py`,
`diagnostic_progress.py`, `schema.py`, `store.py`, `server.py`, `shadow_view.py`;
`src/exp_tracker/web/shadow.html`, `shadow.js`, `shadow.css`, `streams.js`;
`tests/test_multi_alpha.py`, `test_diagnostic_progress.py`, `test_diagnostic_history.py`,
`test_backup_database.py`; `tools/shadow.test.mjs`, `streams.test.mjs`,
`shadow.browser.mjs`; `README.md`, `docs/multi-alpha.md`, `tracking.md`, `design.md`,
and this guide.

# 24-hour granular-data retention

Implemented on `feat/24h-retention`; not deployed or run against live data.
The Windows production database remains untouched. The successful VPS capture/API
trial predates this feature; the production tracker service is not yet enabled.
Validation here uses disposable synthetic data only.

## Why additional state is necessary

Deleting old attempts alone breaks causal inference. `rolling_history` follows
verified run rotations back to their beginning, carrying level inference,
percentage quarantine, invalidation barriers and endpoint context. Its existing
checkpoints are process memory and cannot survive deletion/restart. Schema 7
trusted invalidation also replays original accepted/baseline observations;
`tracking_state` alone cannot reconstruct revised accounting or session gains.

Schema **8** adds `retention_state`, `trusted_checkpoints` and `retention_meta`.
Schema **9** adds `daily_character_exp`. Both migrations are additive and do
**not** prune or generate snapshots. Update every reader, writer and admin
installation before enabling retention. Readers still accept schemas 3–8
without migrating them. Existing schema-8 copies upgrade through the separate
schema-9 migration; older code cannot open a schema-9 database.

Maintenance checkpoints a chronological prefix of complete runs and removes its
raw attempts in one transaction. Only the owning coordinator may also expire
abandoned unfinished runs: it holds the existing ownership lease and supplies
actual active run IDs. Standalone maintenance protects unfinished runs.
Retention never infers identity or changes OCR recognition rules.

| Data | Retention |
|---|---|
| Diagnostic attempts / trusted observations | About 24 hours, with boundary allowances below |
| Character IDs/names, selection, sessions | Preserved |
| Last known public reading, level, numerical EXP, timestamps/provenance | Compact dated display per character, preserved indefinitely |
| Causal level/quarantine/barrier state | Checkpointed; never supplied as a new reading |
| Rolling boundary | One older usable endpoint, not a historical attempt sequence |
| Saved pace/ETA | Compact dated summaries; expired windows remain unavailable |
| Daily character EXP status | At most one compact observed status per character/UTC day, preserved indefinitely |
| Trusted tracking | Revised anchor, continuity/missing counts, original/revised accumulated gains, minimal FK anchors |
| Corrections, renames, invalidation batches/memberships/commits | Append-only audit preserved |
| Capture/operator JSONL and saved OCR crops | Owned, inactive, expired files only |

The cutoff is **24h + 5m**, allowing existing causal warmup. A run crossing it stays
intact (at most 60 attempts). The VPS timer runs maintenance once a day, so expired data can wait
up to a further day before it is folded. At the usual 20s cadence the
allowance is approximately 25h25m; at the supported 300s maximum it can approach
30h05m. Active runs are always protected. Backlogs advance at most 200 runs per
transaction; batch-limited sweeps repeat after 60 seconds. Reports identify each batch. Late/misordered runs can hold
back a prefix and are not silently skipped.

Retained 5/10/15/30/60-minute and 24-hour calculations use the existing endpoint,
level-up and real-timestamp rules. The checkpoint preserves inference/quarantine
across rotation. Under the [rolling-window policy](rolling-window-gaps.md), an
eligible interval ending inside a window contributes its whole nonnegative gain
when its duration fits that window, even if its earlier endpoint precedes the
window. This does not change the retention cutoff or recover deleted evidence;
calculations require supported retained endpoints/checkpoints. No intermediate
readings are invented, and last-known display values never enter interval inputs.
Public URLs and JSON shapes remain unchanged. Retention revisions
invalidate publisher cards and in-memory replay keys include the frozen prefix.

## Daily character snapshots (storage only)

`daily_character_exp` uses `(character_id, utc_date)` as its composite primary key
and references the persistent character ID. Renaming a character, switching
sessions, archiving it or restarting capture does not change its snapshots.
The table is `WITHOUT ROWID` to avoid a redundant index/row identifier.

Each row stores only the actual observation timestamp, supported level (nullable),
numeric current EXP (nullable), percentage in integer basis points (nullable),
and four short provenance fields: source, level basis, EXP basis and percentage
basis. No raw OCR JSON, source events, frame hashes, images or diagnostic payloads
are stored. Numeric EXP remains an integer through SQLite's full range.

The row represents the **last usable observed status of that UTC day**. A final
eligible October 19 reading at **23:42 UTC** remains timestamped 23:42; it is not
retimed to midnight. Diagnostic times use the existing capture receipt timestamp;
trusted observations use their original observation time. Times are normalized
to UTC before selecting the calendar date. A day with no eligible observation
produces no row. Neither yesterday's status nor permanent last-known state fills
an empty day. There is no inferred daily EXP gain or implied playtime.

Snapshots are created from the source prefix **inside the pruning transaction,
before deletion**. Diagnostic rows pass the same causal level/quarantine and
public-reading eligibility checks, plus the existing freshness, ordering and
crop gates. Trusted sources use revised accepted/baseline replay. Known
invalidations are excluded. Historical point fixes supply their corrected values
at the original source timestamp with `manual_correction` provenance, including
explicit fixes of rejected trusted observations. Standalone set/clear baselines
do not create an observed day. Superseded/undone corrections do not override OCR.

Percentage-only readings retain their percentage and supported/inferred level,
without inventing numeric EXP from an experimental estimate. A contradictory
numeric EXP is withheld while independently eligible percentage evidence can
remain. `level_basis` distinguishes reader support, retained/inferred context
and manual input; integer EXP provenance distinguishes strict OCR, grammar
recovery and manual supply. A percentage derived from a manual integer is labelled
`derived_from_manual_exp`, rather than presented as a displayed percentage.
Existing eligible conditional punctuation recoveries retain `conditional_symbol`
EXP/percentage provenance and `conditional_context` level provenance: these values
remain experimental, not exact or trusted OCR. Recovery uses the existing causal
endpoint collector; retention adds no recognition or evidence rule.
Observed numeric OCR is not a guarantee that OCR was correct.

Repeated cycles upsert only a later eligible timestamp for the same character/day.
For equal timestamps, manual corrections take precedence, then trusted OCR, then
diagnostic evidence; otherwise the existing row stays. If a day's runs expire in
different sweeps, its snapshot is provisional until its last eligible retained
reading is pruned. Transaction rollback also rolls back snapshot updates.

Daily snapshots are **never read** by live inference, rolling 5/10/15/30/60-minute
or 24-hour calculations, trusted accounting, public publishing or permanent
last-known state. No historical API, leaderboard, frontend or graph is added.
The existing approximately 25–30-hour run-boundary allowance is unchanged.

Example footprint: an isolated in-memory SQLite measurement with **25 characters
observed every day for 365 days** stored **9,125 rows**, using **1,073,152 additional
bytes** (about **1.02 MiB**, **118 bytes per row**, or **42 KiB per character/year**).
That example used compact strict-OCR provenance and 4 KiB SQLite pages. Actual
page utilization, integer sizes and provenance mix vary; WAL and other tracker
tables are excluded. Inactive/empty days add no rows. Storage still grows with
observed character-days because snapshots currently have no expiry.

Schema-8 history already deleted before this feature cannot be reconstructed into
daily snapshots. Compact checkpoints and old snapshot restores do not recreate
missing observed days. Frozen source readings retain the existing admin expiry
rules: snapshots are not a new correction/restoration target and cannot recover
the deleted original. Append-only administration audits remain separate.

## Administration after expiry

An audit entry does not imply its original source still exists. Expired
invalidations remain inspectable with `expired: true`, `original: null`; the admin
page explains expiry and omits individual Restore for those rows.
An expired retained FK anchor is also marked expired, even while its scalar source
row still exists. History reports `expired_count` over the complete batch, not
just currently excluded members. Any expired member suppresses whole-batch
Restore and explains why; individual Restore remains available for retained
readings in the Invalidated readings list. The backend still revalidates on save.
Past readings also labels retained-but-expired anchor rows and omits actions that
the expiry boundary would reject.

Corrections/baselines, amendment/undo of frozen corrections, invalidation and
restoration at/before a character's checkpoint cutoff are rejected. They could
otherwise change causal history whose source no longer exists. Ranges crossing
the floor are rejected rather than partially reviewed. A restore batch containing
expired members is rejected atomically; restore retained members individually.
Existing retry receipts remain idempotent. Retained corrections and
invalidate/restore still replay normally. Supply new information using an
explicit current baseline.

Observation/attempt IDs and run rowids never recycle after pruning, preventing
old audit identities from attaching to new readings. Trusted FK anchors retain
scalar original evidence; expired interval links/missing counts are detached and
their accounting is preserved in checkpoint totals.

## Operation and reporting

Retention runs as its own process beside the coordinator, never inside the capture loop.
Measured 2026-10-22: inline maintenance froze the live coordinator 19–41 s per round and skipped
captures, so the coordinator now refuses `--retention-24h` and points to this worker. Measurements
and design: [retention-capture-interference.md](retention-capture-interference.md).

How a pass works (`python -m exp_tracker.retention --apply`):

- **Snapshot, then a short write.** Planning, the checkpoint replay and the foreign-key check read
  one WAL snapshot with `PRAGMA query_only=ON`, so they hold no write lock. Each character prefix is
  then written in its own `BEGIN IMMEDIATE` transaction that first re-reads everything the replay
  depended on (retention revision, that character's checkpoint, audit maxima, open session,
  `tracking_state`, the prefix runs' attempt counts). If anything changed, nothing is written and
  the prefix is recomputed. The write covers only daily snapshots, the checkpoint, id high-water
  marks and deletions: about 0.1 s regardless of batch size.
- **Which unfinished runs are protected, without a heartbeat.** Each streamer's newest run while it
  has no summary. A coordinator has one lane per streamer, so an older unfinished run was
  superseded (e.g. a killed process) and expires like a finished one. With capture stopped this
  keeps at most one extra run per streamer.
- **Bounded and repeatable.** Batches of `--batch-runs` (default 10) until no backlog or
  `--max-seconds` (default 600; the unit uses 900), pausing `--pause-seconds` between batches. The
  remainder continues on the next pass. Re-running is idempotent; a killed pass loses only its open
  batch (SQLite rolls it back).
- **One revision bump per pass, only when something changed.** The publisher rebuilds every page
  when the retention revision changes, keeping each old page and Characters-list summary on show
  until its rebuild (a fold changes no shown value); per-batch bumps would keep it rebuilding during
  catch-up. Rebuilds resume their checkpoints across the fold ([incremental history](incremental-history.md)).
- **Files after SQLite, outside any transaction** (only with `--log-root`). A capture log goes only
  when it is older than the cutoff, its folder is owned by this database, it isn't a protected run's
  log, and none of its attempts remain in SQLite. The newest operator log of the newest coordinator
  directory is kept, since it may still be open. A file that can't be removed (e.g. open on Windows)
  is counted in `file_errors` and left for a later pass. Then a passive WAL checkpoint.
- **No overlap, no migration.** `<db>.retention.lock` admits one worker per database (another exits
  75). The worker refuses databases that would need a schema migration.

Output: one JSON line per batch (`runs`, `attempts`, `compute_s`, `lock_ms`, `stale`) and a summary
(`chunks`, `max_lock_ms`, `busy_errors`, `stale_snapshots`, `complete`, `revision_bumped`, `files`,
`bytes`, `file_errors`, `oldest_attempt_hours`, `attempts_kept`, `unfinished_runs`, `protected_runs`,
`db_mb`, `wal_mb`). Exit 0 also when backlog remains (`complete: false`); 75 = busy or locked, try later.

```sh
# Read-only report (default), safe beside a running coordinator:
.venv/bin/python -m exp_tracker.retention --db private/vps/tracker.sqlite3
# One pass, SQLite and owned log files:
.venv/bin/python -m exp_tracker.retention --db private/vps/tracker.sqlite3 --apply --log-root private/multi-alpha/runs
# Windows: repeat hourly in a separate terminal (Ctrl+C stops between statements):
.\.venv\Scripts\python -m exp_tracker.retention --db private\multi-alpha\live-local.sqlite3 --apply --log-root private\multi-alpha\runs --every-minutes 60
```

On the VPS: `deploy/msxp-retention.service` (oneshot, low CPU/IO priority) and
`deploy/msxp-retention.timer` (daily at 04:45 Toronto time, the quietest hour: each pass slows site
updates for a few minutes and ends with one full page rebuild). Neither is
installed by `install-ubuntu.sh`. Not enabling the timer disables retention completely. The
coordinator units no longer pass any retention option, and `MSXP_RETENTION` is unused.

Coordinator directories always record their database owner. Legacy directories are adopted only
while all capture headers identify runs in that DB. Cleanup never follows symlinks/junctions,
crosses the owned root or touches unrelated files. Known `exp.png` / `level.png` crops expire with
their log. Operator output rotates hourly. Malformed/unowned legacy evidence stays untouched.
No automatic `VACUUM` or backup runs; SQLite reuses freed pages, so the file stops growing rather
than shrinking (see the rowid note below before considering any shrink).

## Snapshots and remaining limits

**Never `VACUUM` (or `VACUUM INTO`, or dump/reload) a tracking database.** `diagnostic_runs` has a
TEXT primary key, so its `rowid` is implicit, and SQLite may renumber implicit rowids when it
rebuilds a table. Checkpoints store `through_run` as a rowid, run order uses `rowid`, and
`retention_meta.run_id` is a rowid high-water mark. Renumbering would make replays skip or repeat
runs. Normal inserts are safe: `next_id` assigns rowids above the high-water mark, so deletions
never recycle them. `tools/backup_database.py` uses SQLite's page-copy backup API, which preserves
rowids. Shrinking a file safely first needs an explicit `INTEGER PRIMARY KEY` column on
`diagnostic_runs`, a schema migration that hasn't been done.


Use the provider's existing **seven-day automatic snapshots** for MVP. Do not
enable `msxp-backup.timer`; no off-site infrastructure or new backup timer is added.
Snapshots may contain expired readings/logs and credentials until the provider
expires them. Retention is not secure erasure of freed SQLite pages or snapshots.

Restore with capture/admin stopped and keep the DB, WAL/SHM and ownership marker
consistent. Rehearse in a disposable location, validate integrity/FKs and serve
read-only with schema-9-capable code first. Restore rewinds readings, corrections,
invalidations and last-known state to snapshot time. Later events are lost unless
separately recovered; never merge diverged capture histories. Startup retention
ages restored evidence against current UTC while preserving dated last-known
values, including only the daily snapshots present in that snapshot. Older code
cannot reopen a migrated schema-9 DB. File-owner markers
bind absolute DB paths; relocated directories are left alone. No production
restore/migration was performed here.

Audit, session metadata and daily snapshots still grow intentionally. Transition
evidence is now bounded as detailed below. This is raw-evidence retention, not a
fixed disk quota. Monitor maintenance
failures, DB/WAL and private directory sizes. Sustained VPS maintenance latency,
hard process termination and filesystem-failure recovery have not been measured.

## Bounded duplicate-frame checkpoint history

The original `pace_intervals.collect()` kept every distinct frame hash in
`seen_frames`. Retention cleared `seen_events` but serialized the complete frame
set in `tracked.interval_state.diagnostic`. This was unbounded even with successful
pruning: 1,576,800 distinct frames per year at a 20-second cadence require about
**105.6 MB/year/character** of compact JSON hashes alone (67 bytes per hash).

The collector now stores a hash-to-last-seen-time mapping ordered by last sighting.
It evicts entries older than **24 hours plus five minutes**, inclusively preserving
the lower boundary. Time advances with the maximum valid, nonfuture observation
timestamp processed by replay, rather than the later API/maintenance query time.
This preserves duplicate rejection while replaying historical rows, including
rows on opposite sides of a scheduled rotation or pruning boundary. Repeating a
hash refreshes its expiry even when that repeated capture is rejected, so a frozen
frame repeated continually cannot age into eligible evidence. Future/malformed
timestamps cannot advance the clock and prematurely remove protection.

At 20-second cadence, a steady stream of unique hashes holds at most **4,336
entries**, about **347 kB** for the mapping with typical epoch timestamps. The
bound is elapsed time, not an attempt-count cap: faster imported timestamps can
hold more entries. The map and its monotonic replay clock survive checkpoint
serialization and cold restarts. Inactivity leaves a fixed dated window of hashes;
the next observation ages it forward. Public API shapes, numerical eligibility,
quarantine, continuity, level inference and the granular run-boundary allowance
are unchanged. Hashes outside the horizon no longer veto a new capture solely
because that image appeared in arbitrarily old history.

No SQLite schema migration is needed. Existing undated hash sets load
conservatively: all receive the checkpoint's final attempt time once. Unseen
legacy hashes expire after one horizon of subsequent **prefix replay progress**;
serialization/restart does not renew that grace. A genuinely repeated hash gets
its real new last-seen time. Consequently an already oversized checkpoint may
remain oversized temporarily, including during inactivity or a pruning backlog.
Instantly trimming its undated hashes would discard unknown recent duplicate
evidence. Update all processes that read checkpoints together; older code expects
a set and cannot consume the new mapping. Restoring an old provider snapshot
uses the same conservative conversion; no live copy was migrated here.

Other checkpoint fields were checked for per-attempt growth:

- `seen_events`, percentage-review `seen` sets and missing-event `holes` lists
  are already cleared when a prefix is frozen. Without successful maintenance,
  replay memory/raw history can still grow to the existing replay limits.
- Recent reader samples (3), context hashes (12), conditional support (2), and
  competing-level samples (3) are bounded. Anchors, barriers, pending quarantine,
  trusted totals and missing counts use fixed records/scalars, not attempt lists.
- `level_state.derived.transition.samples` previously accumulated every distinct
  post-wrap observation. The bounded evidence budget described below now prevents
  this last known lifetime-proportional checkpoint list from growing indefinitely.

Focused regressions exercise five synthetic days at 20-second cadence with hourly
serialization/restarts, exact expiry, refreshed duplicates, legacy sets and future
timestamps. Five further daily pruning/restart cycles span nearly seven days of
synthetic runs and match an unpruned reference's 5/10/15/30/60-minute and 24-hour
metrics, including missing readings and the initial level-up. Their final full
checkpoint was **112,705 bytes**, including **290 fingerprints / 23,201 bytes** at
300-second cadence; full checkpoint sizes stayed within 2 kB across those cycles.
These measurements predate the bounded-transition follow-up below. A separate
experimental-punctuation duplicate regression deletes its
original frame's run, reopens SQLite and still rejects recovery across the retained
run boundary. This verifies an actual evidence veto as well as rolling parity.

Follow-up validation: **7 new fingerprint tests passed**; **176 existing focused
tests passed**, with **4 private-recording skips** reported separately and **2 HTTP
cases deselected**. Two of those existing tests check incremental/full replay and
the older window endpoint; the multi-day regression also passed a final repeat.
No full suite, private recording replay, live database change or deployment was
performed. `git diff --check` passed.

## Bounded level-transition evidence

A percentage wrap remains a **hypothesis**, with the existing possible,
provisional, corroborated and abandoned phases. `exp_derived_level_v4` retains at
most **64 distinct post-wrap samples** in active transition evidence. The wrap
itself is separate. Until that budget is exhausted, inference uses the original
complete chain: at least three independent frames, cumulative forward progress,
every numeric pair ordered, and a supported destination-level requirement.
`_chain()` and raw OCR recognition are unchanged. Flat samples do not prove a
level-up; reused frame hashes never supply additional independent samples.

If a 65th distinct sample would be added while still unresolved (including an
already provisional transition), the transition becomes `evidence_exhausted`.
Its phase and dated proof stay available, but further percentage-only observations
return unavailable with `transition_evidence_limit`. They cannot promote the
level, renew live level evidence or supply new EXP estimates through this
transition. The full retained chain is frozen; it is not replaced by a rolling
three-sample tail. A valid selected reader level or unique EXP/percentage pair
can still corroborate the new level, and contradictory evidence can still abandon
the hypothesis or revert to the previous level under the existing rules. The
existing 120-second continuity expiry is unchanged. Restarting or pruning does
not replenish the budget. Permanent dated last-known display remains independent.
The public player and tracked-history current-level selectors also ignore an
exhausted possible candidate: they retain the previously supported level rather
than selecting `to_level`. Ordinary non-exhausted possible transitions keep their
existing candidate filter. Previously supported provisional levels remain dated
last-known evidence; later independent corroboration selects the confirmed level
normally. Four integration cases cover both prior phases and EXP-pair/reader
resolution, including public/tracked current-level windows and chart intervals.
The targeted integration selection passed **88 tests**, with **one unavailable
private-capture skip** and **six cases deselected**; the four new selector cases
also passed separately. No full-suite run was needed.

This intentionally trades availability for safety in long-lived obscured-HUD
transitions. At 20-second cadence, 64 new distinct post-wrap captures span roughly
21 minutes. Flat evidence followed by progression within that budget still
promotes normally; progression after exhaustion is withheld until independent
resolution. A provisional transition also stops renewing percentage estimates
after exhaustion. Exact lifetime-wide frame uniqueness cannot be maintained with
bounded hashes; recycling a window could let old frames count again, and simply
dropping old numeric samples could erase a contradiction. No Bloom filter or new
inference infrastructure is introduced.

Resolved provenance and public `level_context` keep at most **three representative
samples** (first two and last), with `sample_count` when samples were omitted.
These are explanatory summaries, never fed back into `_chain()`. Active proof
retains all of its budgeted samples; provenance omits the rollback `before` state.
The rollback anchor and previous resolved transition also remain bounded.

Compatibility needs no SQLite/schema or daily-snapshot migration. Checkpoint
decoding compacts every transition copy, including old endpoints, saved display
and `last_transition` for inactive characters. An oversized active legacy chain
keeps its first 63 and final sample, is marked exhausted **before any inference**,
and cannot promote because discarded evidence made the shortened chain look
valid. Existing possible/provisional phase labels remain provenance. Resolved and
public copies shrink to three samples. The next checkpoint write persists this
compaction; old SQLite blobs can remain until then. Initially parsing an already
large legacy JSON blob still temporarily costs memory proportional to that blob.
Update all checkpoint readers/writers together. Older code ignores the exhaustion
flag and must not read rewritten checkpoints; a binary downgrade needs a matching
older provider snapshot. No production database was opened or migrated here.

Synthetic measurements use retained Python object sizes (`sys.getsizeof`, shared
objects counted once), not process RSS or interpreter/parser cache memory:

| State after observations | Serialized JSON bytes | Retained Python heap bytes |
|---|---:|---:|
| Possible transition, full level state, 1,000 | 15,190 | 41,543 |
| Possible transition, full level state, 10,000 | 15,193 | 42,799 |
| Provisional transition, full level state, 1,000 | 15,351 | 41,685 |
| Provisional transition, full level state, 10,000 | 15,354 | 43,007 |

Both states still held 64 proof samples and at most three public samples after
cold serialization/restart. The small byte differences include longer event IDs
and JSON reload object sharing, not accumulated evidence. A four-day synthetic
SQLite run at 120-second cadence exercises three daily prefix-pruning/restart
cycles; live inference and every rolling metric match the unpruned reference,
including later exact-pair corroboration. Its final full checkpoint measured
**160,685 JSON bytes / 407,690 retained heap bytes**; the level-state portion was
**18,302 / 54,940 bytes**. This whole-checkpoint measurement also includes the
bounded frame-hash map and other retained state.

Against the committed pre-change implementation, seven normal synthetic sequences
(159 observations) matched level values/status, numerical eligibility and EXP/
percentage readings, including normal promotion, flat-then-progress, duplicates,
contradiction, exact-pair and reader corroboration. A 1,000-flat-sample sequence
followed by progress deliberately changes from provisional promotion to withheld
inference. Legacy compaction tests preserve a numeric veto that naive truncation
would remove. Raw observations, trusted accounting and daily snapshot format are
unchanged; unavailable inference never generates invented gain.

Validation: **10 new transition regressions passed** and **128 existing focused
level-inference, rolling-history, retention, fingerprint, daily-snapshot,
incremental-checkpoint and publisher regressions passed**. **Eight private
saved-recording cases were deselected; zero tests/sample tests skipped.** The
concurrent-viewer publisher case initially hit sandbox `WinError 10013`, then
passed with permitted localhost sockets. Full-checkpoint JSON/heap measurements
across the three pruning cycles were **155,629 / 386,580**, **160,685 / 407,690**,
and **160,685 / 407,690 bytes**; the first prefix was still filling the separate
24-hour fingerprint window. `git diff --check` passed. No full suite or production
operation was run.

Synthetic checks cover window parity, level-ups, rotations, missing frames,
inactivity/cold reads, corrections, invalidation/restoration/audit, atomic failure,
FK anchors/totals, ID reuse, owned file/crop cleanup, operator rotation, read-only
schema-7 reporting and coordinator integration.

## Local validation and changed files

Current schema-9 validation: **200 focused Python tests passed** across daily
snapshots, retention, invalidations/admin, Store migrations and rolling/diagnostic
history. A separate publisher/incremental-checkpoint selection passed **35 tests**,
with **7 private saved-recording cases deselected**. **17 Node tests passed**, including
three expiry-action rendering regressions and the existing date/time checks.
There were **zero skips**, including **zero sample skips**; no private source
fixtures or full suite were run. Admin JavaScript syntax and `git diff --check`
passed. Admin preview temporary copies stayed under ignored workspace artifacts;
publisher concurrency used permitted localhost sockets.
The final daily/retention/rolling follow-up passed **55 tests**, including an
existing supported conditional-recovery case. Counts across these selections overlap.

Review checks include three retention cycles with cold writer restarts compared
against an unpruned synthetic reference, exact rolling windows across level-ups
and missing captures, inactive last-known values, failure after snapshot creation
and deletion, active-run protection, immutable audits, FK anchors, monotonic source
IDs and daily-table isolation from public/trusted metrics. No broad checkpoint
refactor or OCR algorithm change was needed.

Files changed:

- New implementation: `src/exp_tracker/retention.py`, `retention_files.py`, `daily_snapshots.py`.
- Persistence/replay: `src/exp_tracker/schema.py`, `store.py`, `trusted_replay.py`,
  `rolling_history.py`, `diagnostics.py`, `diagnostic_progress.py`, `product.py`,
  `invalidations.py`.
- Admin expiry presentation: `src/exp_tracker/admin_server.py`,
  `src/exp_tracker/web/admin-invalidations.js`, `src/exp_tracker/web/admin.js`.
- Automatic operation: `tools/multi_alpha.py`, `deploy/msxp-tracker.service`,
  `deploy/install-ubuntu.sh`.
- Tests: new `tests/test_retention.py`, `tests/test_daily_snapshots.py`,
  `tools/admin-invalidations.test.mjs`; `tests/test_invalidations.py`, `tests/test_multi_alpha.py`.
- Documentation: `README.md`, this guide, `docs/continuous-alpha.md`,
  `docs/manual-exp-admin.md`, `docs/rolling-exp-history.md`, `docs/vps-deployment.md`.

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
intact (at most 60 attempts); maintenance runs hourly. At the usual 20s cadence the
allowance is approximately 25h25m; at the supported 300s maximum it can approach
30h05m. Active runs are always protected. Backlogs advance at most 200 runs per
transaction; batch-limited sweeps repeat after 60 seconds. Reports identify each batch. Late/misordered runs can hold
back a prefix and are not silently skipped.

Retained 5/10/15/30/60-minute and 24-hour calculations use the existing endpoint,
level-up and real-timestamp rules. The checkpoint preserves inference/quarantine
across rotation. Boundary-straddling intervals remain excluded; unobserved time
does not acquire invented gain. Last-known display values never enter interval
inputs. Public URLs and JSON shapes remain unchanged. Retention revisions
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

The proposed `msxp-tracker.service` includes `--retention-24h` with `--continuous`.
Nothing has been installed, started or enabled here. Maintenance runs before
scheduled captures, including startup and repeated capture failures. SQLite
failures roll back the transaction, print `Retention postponed`, and retry after
60 seconds while capture continues. Reports include cutoff, raw attempt/run
candidates and artifact file/byte counts.

Read-only report, without creating/migrating a database:

```sh
PYTHONPATH=src .venv/bin/python -m exp_tracker.retention --db private/disposable/tracker.sqlite3
```

Deliberate rehearsal on a **disposable synthetic/copy database** after updating all
code that opens it:

```sh
PYTHONPATH=src .venv/bin/python -m exp_tracker.retention --db private/disposable/tracker.sqlite3 --apply
```

`--apply` migrates that explicitly selected database if needed. Standalone
maintenance handles SQLite only and protects unfinished runs. The coordinator
also handles files after successful DB retention, then issues a passive WAL
checkpoint. No automatic `VACUUM` or backup runs. SQLite reuses freed pages; its
existing high-water file size may remain. Shrinking an already large file is a
separate stopped-service operation requiring free disk space.

Coordinator directories record their database owner. Legacy directories are
adopted only while all capture headers identify runs in that DB. Cleanup never
follows symlinks/junctions, crosses the owned root, deletes active handles or
unrelated files, or removes logs whose raw attempts remain in SQLite. Known
`exp.png` / `level.png` crops expire with their log. Operator output rotates hourly.
Malformed/unowned legacy evidence stays untouched and may require operator review.

## Snapshots and remaining limits

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

Audit, session metadata and daily snapshots still grow intentionally. Exceptional
unresolved inference state can also grow, as detailed below. This is raw-evidence
retention, not a fixed disk quota. Monitor maintenance
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
- **Remaining exception:** `level_state.derived.transition.samples` appends unique
  post-wrap samples while a level-up remains possible or provisional. Repeated
  flat percentage-only evidence can keep this unresolved indefinitely. A synthetic
  1,000-frame check retained all 1,000 samples; resolved transition provenance and
  last-known display/context can also retain that list. This is separate from
  `seen_frames`. Arbitrarily truncating it could change duplicate, numeric-chain
  or level-up decisions, so this small fix leaves inference unchanged. A future
  exact inference-summary change is needed for an overall fixed checkpoint bound.

Focused regressions exercise five synthetic days at 20-second cadence with hourly
serialization/restarts, exact expiry, refreshed duplicates, legacy sets and future
timestamps. Five further daily pruning/restart cycles span nearly seven days of
synthetic runs and match an unpruned reference's 5/10/15/30/60-minute and 24-hour
metrics, including missing readings and the initial level-up. Their final full
checkpoint was **112,705 bytes**, including **290 fingerprints / 23,201 bytes** at
300-second cadence; full checkpoint sizes stayed within 2 kB across those cycles.
These measurements use ordinary supported levels, not the unresolved-wrap
exception. A separate experimental-punctuation duplicate regression deletes its
original frame's run, reopens SQLite and still rejects recovery across the retained
run boundary. This verifies an actual evidence veto as well as rolling parity.

Follow-up validation: **7 new fingerprint tests passed**; **176 existing focused
tests passed**, with **4 private-recording skips** reported separately and **2 HTTP
cases deselected**. Two of those existing tests check incremental/full replay and
the older window endpoint; the multi-day regression also passed a final repeat.
No full suite, private recording replay, live database change or deployment was
performed. `git diff --check` passed.

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

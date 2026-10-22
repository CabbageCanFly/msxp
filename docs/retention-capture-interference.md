# Retention without missed captures

Investigation, 2026-10-22. Retention is **off** again on the local tracker; nothing here is
deployed. Companion to [24h-retention.md](24h-retention.md).

## Summary

- Turning on `--retention-24h` on the local live tracker (12 streamers, 20 s cadence) made every
  streamer miss about one reading per minute during the one-time catch-up. Each cleanup round froze
  the whole tracker for 19–41 s.
- Cause: the cleanup runs **inside the tracker process, in its capture loop**. That process is
  already maxed out on Python's single interpreter lock (GIL), so cleanup ran about 10× slower than
  the same work in its own process. The SQLite engine is not the bottleneck.
- Recommendation: run the cleanup in **its own process** with small chunks. The expected cost is a
  write lock of at most ~3 s per chunk, which is less than one capture interval, so no reading is
  missed. Small change, no new infrastructure, $0. Migrating to Postgres would not fix this by
  itself (see below).

## Measurements

| What | Result |
|---|---|
| Backlog when enabled | ~65.6k raw attempts older than 24 h (oldest 104.9 h) |
| 200-run chunk, own process, copy of live DB | 15–25 s (≈0.1 s per run) |
| 25-run chunk (`BATCH_RUNS`, `dafd778`), own process, copy, live tracker running alongside | 2.9–3.5 s |
| 25-run chunk **inline in the live tracker** | whole-tracker silences of 19–41 s every ~80 s (≈0.8–1.6 s per run) |
| Effect during catch-up (10 min after restart) | 6–8 missed readings per streamer, worst delay 35–47 s |
| Live tracker process CPU | 109% of one core, 16 threads, on a 24-core machine |
| File-cleanup scan (dry run, 1,761 logs) | 1.4 s, so not the cause |
| Progress before it was stopped | oldest data 104.9 h → 71.3 h in ~20 min; integrity ok afterwards |

Before/after numbers come from `tools/tracker_health.py` (read-only; reports missed readings and
worst delay per streamer, plus kept-data age).

## Why it blocks

1. `maintain()` runs in the coordinator's scheduler loop (`tools/multi_alpha.py:416`). While a round
   runs, no new capture starts and finished captures aren't saved. Readings keep their capture-time
   timestamps. A slot is skipped only if the pause exceeds one interval (`tools/multi_alpha.py:388-391`).
2. The expensive part of `retention.prune` is folding the runs being removed into a checkpoint: it
   replays them (`rolling_history.replay` via `recent_snapshot`/`aggregate`). That work happens inside
   the write transaction.
3. Capture workers (`tools/multi_alpha.py:446`) and the publisher (`:627`) are threads in the same
   process. At ~109% CPU the process is GIL-bound, so the main thread's replay gets a small share. This
   is inferred from the CPU sample, the thread layout, and the 10× gap against a separate process
   running at the same time. It has not been profiled inside the live process.
4. SQLite's one-writer rule only matters because the write transaction is long. Capture saves are
   milliseconds; the busy timeout is 5 s (`src/exp_tracker/store.py:36`).

## Options

| Option | Change | Effort | Cost | Expected effect on captures |
|---|---|---|---|---|
| **1. Separate cleanup process** (recommended) | Run `retention.prune` + file cleanup in its own Python process (a loop or timer: every 60 s while a backlog exists, hourly after) | Small | $0 | Its own interpreter and core, so ~3 s per 25-run chunk. Saves wait ≤ that; no missed slot at 20 s. Use 10-run chunks for ≤ ~1.5 s |
| 2. Short write transaction | Compute the checkpoint from a read-only snapshot first (WAL readers don't block), then take a brief write lock to re-check revisions and delete/upsert | Medium | $0 | Lock in milliseconds. Pairs with option 1 |
| 3. Time-budgeted inline rounds | Stop a round after ~2 s, continue next round | Small | $0 | No misses, but a ~2 s stutter every minute during backlog; still GIL-slow. Stopgap only |
| 4. Quiet-hours schedule | Run cleanup once a day in a low-traffic window | Config only | $0 | Misses concentrated in that window; anyone live then still loses readings |
| 5. No deletion | Keep everything, monitor disk | None | Disk (~100 MB/day at 12–15 streamers) | None, but the DB and replay costs keep growing |
| 6. Postgres | Replace SQLite | Large (weeks) | VPS self-host $0 but ~100–300 MB RAM plus backups/upgrades/auth; managed roughly $15–30/month (rough, not quoted) | Concurrent inserts during deletes, but an inline cleanup would still freeze the loop, so option 1 is needed anyway |
| 7. Other engines | libSQL/Turso concurrent writes, DuckDB, per-day SQLite files | Medium–large | varies | Same inline-CPU problem; per-day files make deletion cheap but complicate every cross-day query |

### Notes on option 1

- **Entry point:** extend the existing `python -m exp_tracker.retention --db … --apply` (it already
  runs without the coordinator's writer lease) with a repeat mode, or have the coordinator spawn it as
  a subprocess. On the VPS it could be its own systemd unit.
- **Unfinished runs:** standalone mode already protects all of them. Expiring abandoned ones needs the
  coordinator's active run IDs. The `--runtime-state` heartbeat already publishes them
  (`src/exp_tracker/capture_runtime.py:40`), or a rare inline pass can keep doing it.
- **Files:** cleanup already refuses to delete logs whose attempts are still in SQLite, so active logs
  stay protected without the coordinator's list.
- **Verify live:** use `tools/tracker_health.py` for 10-minute windows during catch-up. Target: missed
  0, worst delay a few seconds.

### Postgres, in detail

- **Coupling today:** 24 `src/`+`tools/` files use `sqlite3`; ~346 `execute` calls; SQLite-specific
  `rowid` ordering (50 uses, including run order), `PRAGMA` (33), `user_version` schema versioning,
  `INSERT OR REPLACE`, `json_extract`, read-only URI connections. 55 of 114 test files build SQLite
  databases.
- **Migration:** rewrite the store/diagnostics SQL, add a Postgres test setup or a dual backend, and
  migrate the live databases.
- **When it would pay off:** many independent writer processes, multiple machines, or write rates far
  above today's few writes per second. Not this problem.

## Open questions

- Confirm the GIL explanation by profiling the live process (e.g. py-spy), or by timing a
  separate-process chunk against the live database while the tracker runs.
- VPS: 4 vCPU; a separate process gets its own interpreter but competes with OCR subprocesses. Measure there.
- **Local state:** catch-up stopped part-way (oldest data 71.3 h); retention off. Pre-retention backup:
  `private/manual-backups/live-telfer-shiphtur-pre-retention-20261022.sqlite3` (410 MB).

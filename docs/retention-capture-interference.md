# Retention without missed captures

Investigation, 2026-10-22. Retention is **off** again on the local tracker; nothing here is
deployed. Companion to [24h-retention.md](24h-retention.md).

## Outcome (implemented)

Retention now runs as a separate worker (`python -m exp_tracker.retention --apply`; on the VPS the
opt-in `msxp-retention.timer`). The coordinator refuses `--retention-24h`. Moving to a separate
process alone was **not** enough. Measured on fresh copies of the local live DB, with a second
process making one tiny write every 50–100 ms under the same 5 s busy timeout as capture saves:

| Write lock held per batch | 1 run | 5 runs | 10 runs | 25 runs |
|---|---|---|---|---|
| Old: everything inside `BEGIN IMMEDIATE` | 0.7–1.6 s | 1.0–2.2 s | 1.5–3.5 s | 4.1–7.0 s, **3 writer failures** |
| New: snapshot compute, checked short write | — | max 126 ms | max 115 ms | max 132 ms, 0 failures |
| Writer's longest wait (new) | — | 42 ms | 90 ms | 179 ms |

A writer failure matters more than a delay: a capture save that raises `sqlite3.Error` stops that
lane until restart (`tools/multi_alpha.py`, `persistence_failed`). Inside the old lock, a 5-run batch
spent 0.2–0.5 s planning, 0.6–1.2 s replaying, 0.2–0.5 s on a full `foreign_key_check`, and ~0.01 s on
the writes themselves. The new design moves all but the writes into a read snapshot. The checkpoint
computation is unchanged code; the daily snapshots it produces are buffered and written in the same
short transaction as the deletions. Details: [24h-retention.md](24h-retention.md#operation-and-reporting).

## Summary (investigation)

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
worst delay per streamer, plus kept-data age). "Missed" also counts slots paused while a streamer is
live outside MapleStory and restart gaps; only its `behind` part is the tracker falling behind schedule.
The `read / no HUD / unclear / no frame / offline` columns say what each capture got.

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

### Notes on option 1 (as implemented)

- **Entry point:** the existing `python -m exp_tracker.retention` (it never took the coordinator's
  writer lease), now with bounded `--apply` passes, `--log-root`, `--every-minutes`, its own
  `<db>.retention.lock`, and no schema migration. On the VPS: a systemd oneshot + daily timer.
- **Unfinished runs:** the `--runtime-state` heartbeat was rejected. Only capture-only mode writes it,
  and its reader returns an empty active set when the file is missing or stale, which is
  indistinguishable from "nothing running". Instead, `live_runs()` protects each streamer's newest
  unfinished run, from the database alone. The local DB had one superseded unfinished run (12 h old,
  from a killed process). Protecting every unfinished run, the old standalone default, would have
  stalled that character's retention forever.
- **Files:** besides "no attempts left in SQLite", the worker skips protected runs' logs (a paused
  lane's header-only log has no attempts) and the newest operator log of the newest coordinator
  directory (it may be open after a quiet day). Delete errors are counted, not raised.
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

## Remaining risks

- **Measured locally only** (24-core PC). The VPS has 4 vCPUs shared with OCR/FFmpeg: compute will be
  slower, and the write lock may be somewhat longer. Nothing guarantees zero missed captures there
  until the validation below passes.
- **Each revision bump makes the publisher rebuild every page** (existing behaviour). Now once per pass
  with changes; before, every inline call, even with nothing pruned. Also, each batch that advances a
  character's `through_run` changes the publisher's replay key, so that streamer is replayed from
  scratch: on the VPS, site updates slowed from ~90 s to 2–4 min during the pass. Hence a daily timer
  at a quiet hour, until the publisher can resume across a fold.
- **Trusted-tracking anchors** (`_trusted`, the `observations` table) still replay inside a write
  transaction. The roster coordinator writes no observations (local DB: 0). Check the VPS count in
  the inventory below before enabling.
- **Never VACUUM** these databases (implicit `diagnostic_runs.rowid`; see 24h-retention.md).
- **Local state:** catch-up stopped part-way (oldest data 71.3 h); retention off. Pre-retention backup:
  `private/manual-backups/live-telfer-shiphtur-pre-retention-20261022.sqlite3` (410 MB).

## VPS results (measured 2026-10-23, 4 vCPU, 27–28 streamers, ~13 live)

| | Copy rehearsal (`nice -n 10` from SSH) | Live pass (`msxp-retention.service`) |
|---|---|---|
| Wall / CPU | 695 s / 507 s | 905 s (hit `--max-seconds 900`) / 329 s |
| Folded | 1,757 runs, 86,741 attempts; oldest 121 h → 24.5 h | oldest 121 h → 59 h (incomplete) |
| Lock | max 166 ms, 0 busy, 0 stale | no `locked`/`persistence` errors in the tracker journal |
| Captures per 10 min | −28% (all streamers) | live ~15 before and during; offline 30 → 28–30 |

Live MapleStory lanes were already capped at about every other 20 s slot (`behind` = missed) before
retention; offline lanes poll at full rate. `nice` from an SSH session did not protect capture,
probably because CPU is shared between cgroups first; the unit's `CPUWeight=20` did. Integrity check
of the rehearsal copy: `ok`, no FK rows.

## VPS validation plan

**1. Read-only inventory** (no writes, no restarts). Paste the output back:

```sh
cd /opt/msxp/app && git log --oneline -1
systemctl cat msxp-tracker msxp-api 2>/dev/null | grep -nE 'ExecStart|EnvironmentFile|retention|RETENTION|capture-only|runtime-state'
systemctl list-timers --all --no-pager | grep -i msxp
sudo grep -hE '^MSXP_(DATABASE|RETENTION|CAPTURE_LIMITS|RUNTIME_STATE)=' /etc/msxp/roster.env /etc/msxp/split.env 2>/dev/null
DB=$(sudo grep -h '^MSXP_DATABASE=' /etc/msxp/roster.env | cut -d= -f2-); echo "$DB"
sudo -u msxp sqlite3 -readonly "$DB" "SELECT (SELECT COUNT(*) FROM diagnostic_attempts),(SELECT MIN(attempted_at) FROM diagnostic_attempts),(SELECT COUNT(*) FROM observations),(SELECT COUNT(*) FROM diagnostic_runs WHERE summary_json IS NULL);"
ls -la "$DB"* ; du -sh /opt/msxp/app/private/multi-alpha/runs 2>/dev/null
nproc; free -m; uptime; df -h /opt/msxp
```

**Hard gate before deploying this code:** no live unit may still pass `--retention-24h` (the new
coordinator refuses it and would not start). `MSXP_RETENTION` in an env file is now ignored.

**2. Rehearsal on a copy, beside the running tracker** (after deploying the code; destructive only to the copy):

```sh
cd /opt/msxp/app; R=private/retention-rehearsal; sudo -u msxp mkdir -p "$R"
sudo -u msxp .venv/bin/python tools/backup_database.py "$DB" "$R/tracker.sqlite3"
sudo -u msxp env PYTHONPATH=src .venv/bin/python -m exp_tracker.retention --db "$R/tracker.sqlite3"   # report
sudo -u msxp env PYTHONPATH=src nice -n 10 .venv/bin/python -m exp_tracker.retention --db "$R/tracker.sqlite3" --apply --max-seconds 3600 | tee "$R/pass.jsonl"
sudo -u msxp sqlite3 -readonly "$R/tracker.sqlite3" 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

Accept if: the summary shows `complete: true`, `busy_errors: 0` and `max_lock_ms` under ~500, and the
integrity check prints `ok` with no FK rows. Note `elapsed_s`: that's the expected catch-up time.

**3. Live trial, one manual pass** (after approval; the tracker keeps running):

```sh
sudo -u msxp .venv/bin/python tools/tracker_health.py --db "$DB" --minutes 60 | tee ~/health-before.txt
sudo -u msxp .venv/bin/python tools/backup_database.py "$DB" "private/backups/tracker-pre-retention-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
sudo install -m 0644 deploy/msxp-retention.service deploy/msxp-retention.timer /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl start --no-block msxp-retention.service; journalctl -u msxp-retention -f   # chunk + summary lines
# During and after (every ~10 min): compare with the baseline.
sudo -u msxp .venv/bin/python tools/tracker_health.py --db "$DB" --minutes 10
journalctl -u msxp-tracker --since -30min | grep -iE 'locked|persistence|Traceback' || echo 'no capture errors'
```

Accept if, in 10-minute windows during the pass: missed readings match the baseline (0 when streams
are steady), worst delay stays within ~1 s of the baseline, no lane stops, and no `database is
locked` appears in the tracker journal. After the pass, `oldest_attempt_hours` should be about
24–25. Then: `sudo systemctl enable --now msxp-retention.timer`.

**Rollback:** `sudo systemctl disable --now msxp-retention.timer` (retention off). Data already
expired stays expired; restore the pre-retention backup only with capture stopped, per 24h-retention.md.

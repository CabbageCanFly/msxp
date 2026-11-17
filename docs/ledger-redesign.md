# Publisher CPU: ledger redesign (handoff, 2026-11-17)

Status and plan for freeing the API's pinned publisher core. Read with
[background publishing](background-publishing.md) (its "Production CPU pass" section) and
[incremental history](incremental-history.md).

## Problem

`msxp-api`'s background publisher thread holds one core at ~96% (Python, one thread). It
rebuilds each streamer's card and 24h totals; every rebuild recomputed its whole recent
history (640 captures, a day of reading pairs) from raw rows. The tracker's OCR workers share
the same 4 cores, so the pinned core also slows captures (asked 20 s, actual median ~30 s).

## Where things stand

| State | Commits | Notes |
|---|---|---|
| Deployed on the VPS (main) | `9797a0a` list copies, `44a5e9c` latest-run lookup (was 56% of the thread), `ceacbc4` integer window sums, `73bba10` idle channels every 10 min, spaced behind live work | `ecbe889` (first idle attempt) was reverted by `3af5e52`: it delayed live updates to ~5 min |
| Deployed 2026-11-17 | `51c9c7d` settings decoded once per run, `cc6ef03` deploy units read `MSXP_FRONTEND_ORIGIN` (no server effect) | |
| Branch `ledger-redesign`, merged and deployed 2026-11-17 | `915327c` decode each attempt once (content-keyed marshal cache), `7578928` reading-pair intervals remembered between rebuilds and shared by card and totals; caps raised to 192 MB and 512 MB for up to ~80-100 live channels (owner's budget for both: ~1.5 GB), `c5ce99a` card reuses the recent history's point collection, `ed3c4ba` clock-only refresh every 30 s instead of 10 s | Output byte-identical to main for the first three (synthetic full day, 10 rebuilds) |

Measured locally, synthetic full-day channel, CPU per warm rebuild: main 594 ms, branch 453 ms
(−24%). Real captures are 9–14 KB against 0.5 KB synthetic, so phase 1 saves more there:
decode of 640 real captures 140–160 ms → ~7 ms (measured read-only on the VPS).

### VPS baseline before the branch (2026-11-16, ~19 live, 116 channels)

- Publisher thread ~95–98% of one core; load average ~5.8 on 4 cores.
- Live channels rebuilt every ~22 s (median gap 24 s, p90 30 s); idle refreshes ~1% of the core.
- Live rebuild ~1 s; build time ~70% of the thread, the rest cache saves, step overhead and views.
- Warm-up after an API restart ~4 min.

## Deployed 2026-11-17 09:01 UTC (main `53475d4`)

The 04:00 America/Toronto unattended upgrade (package `sos`) had restarted `msxp-api` at
09:00:31 on the old code; the deploy restarted it once more at 09:01. Measured 09:05–09:11 UTC,
14–16 live (fewer than the 19–21 of the baseline, so part of the gain is load):

| | Before (2026-11-16) | After |
|---|---|---|
| Publisher thread | 95–98% | 60–78% |
| CPU per live rebuild | ~1.0 s | 0.59 s median, 0.75 s p90 |
| Live rebuild gap | median 24 s, p90 30 s | median 20 s, p90 31 s |
| Capture gap (asked 20 s) | median 30 s | median 20 s, p90 28 s |
| API memory | ~950 MB | ~1,250 MB (decode and interval caches, within their caps) |
| Warm-up after restart | ~4 min | ~4 min |

Idle channels were not yet due in that window (rebuilt at warm-up, every 10 min after). Re-measure
at peak load before deciding on phase 2.

## Deploy and measure (procedure, needs the owner's go-ahead)

1. Merge the work branch into main and run the **full** suite in the main checkout (private
   fixtures exist only there; a worktree skips ~100 more tests). Worktrees go beside the
   repository (`H:/Desktop/codex/<name>`), never inside it.
2. Check traffic first (Caddy journal, last 5 min: OBS overlays and pages); the owner prefers a
   quiet moment because the restart blips overlays. Ask before pushing or restarting.
3. Push; on the VPS `cd /opt/msxp/app && sudo git pull --ff-only origin main` and
   `sudo systemctl restart msxp-api` (API only; the tracker keeps running).
4. Measure against the baseline: publisher thread CPU (`/proc/<pid>/task/<tid>/stat` deltas,
   thread name `publisher`), rebuilds per channel from the publication cache's `built_at`, live
   overlay update gaps from distinct `history=…&tracked=…` revisions in `journalctl -u msxp-api`,
   and capture cadence (gaps between `diagnostic_attempts.attempted_at`).
5. Decide whether phase 2 below is still needed. If the core already has headroom, stop.

## Phase 2 (branch `ledger-phase2`, worktree `H:/Desktop/codex/msxp-ledger-phase2`, not merged)

| Commit | Change | Output |
|---|---|---|
| `694c32a` | Card window judged continuously: a per-channel ledger keeps the 640 judged rows (packed, ~2.1 MB per channel, 256 MB cap) and the `barriers`/`project` fold state; each rebuild judges only attempts newer than its cursor | Identical on a 122-capture live-style stream (3 runs, rotations); tests compare it with a cold window through rotation, interrupted restart, level-up, loss and source change |
| `1fecd70` | 24h totals add whole EXP and microseconds as integers | Identical |

Rebuild key (any change judges the window from scratch): database path, channel, character, session,
window size, manual-correction and invalidation revisions, retention revision and floor, level-floor
proof, the session's interrupted runs. The ledger also resumes only if its last attempt's payload digest
is still present (a database replaced at the same path reuses IDs). Only the card's 640-row window uses
it; `progress(now)` still runs over the whole window.

Live-style stream, CPU per rebuild: main `13bae97` 453 ms → 359 ms (−21%; −40% against the
pre-redesign 594 ms). Judging fell from ~11% to ~2% of a rebuild. Cache caps now total 960 MB
(decode 192 + intervals 512 + ledger 256), inside the owner's 1.5 GB budget; the decode cap could
shrink now that the card no longer decodes its window.

Still open, each ~5–10%: `percentage_point` is called ~7 times per row per rebuild (results are mutated
by callers, so a memo must hand out copies); the 640-row point collection for the 5-minute pace (its
outputs cover the whole window, and `percentage_review` of the newest rows is clock-dependent); an
indexed `window_endpoints` (prefix sums per window width and level filter).

## Remaining plan (if the measurement says it is worth it)

**Phase 2: continuous card judging.** The card re-judges its 640-capture window from scratch
every rebuild (`Diagnostics._snapshot`: annotate, `barriers`, `project`, `progress`). Keep a
per-channel ledger instead: query only attempts newer than a cursor, judge them once with the
saved fold state (`project(state=)`, `barriers(state)`), keep the last 640 judged rows. Only
`progress(now)` is clock-dependent. The owner accepted (2026-11-17) that verdicts at the
window's oldest edge may differ: today the first ~2 rows of the window are judged without
memory; a continuous fold judges them with context (measured on synthetic data: only positions
0–1 differ for any start shift). Every other output must stay identical; verify with a
comparison that allows exactly those edge differences. Rebuild the ledger from scratch on any
head revision change (manual, rename, invalidation, retention, job) or session change.

Remaining shares of a warm rebuild after the branch (synthetic): card judging ~18%, point
collection ~16% (the 640-row `collect_observed` for the 5-minute pace is ~11%), chart history
~7%, window comparisons ~6%, 24h aggregate's own loops ~30%. Making `progress`, the 640-row
collection, history and comparisons incremental means rewriting functions whose outputs are
whole-window lists (`progress()` segments and comparisons). That is the large, riskier part.

**Smaller items.** Save the restart cache every few rebuilds plus once on clean shutdown (systemd
sends SIGINT with 60 s; the nightly 04:00 America/Toronto unattended-upgrade restarts are clean
stops). Optional production shadow check: every ~50th rebuild also runs the old path and logs
differences.

**Skipped or shelved.** Sharing run lookups between the three replays (fiddly, ~5%); slim
character/overlay endpoints (request CPU ~0; bandwidth only); Caddy per-IP rate limit (shelved).

## Working notes

- Worktree runs: the venv's editable install points at the main checkout, so scripts need
  `PYTHONPATH=src`; pytest's `pythonpath` already puts the worktree first.
- The main checkout's `src/exp_tracker/data/community-exp-v2.json` has CRLF line endings, so its
  table SHA differs from the committed (and VPS) file. Compare old against new with
  `git archive HEAD src | tar -x -C <tmp>` as "old", not the main checkout.
- Synthetic day: `PYTHONPATH="src;tools" python tools/benchmark_homepage.py --directory
  private/bench-ledger --attempts 4321 --channels 1` writes `channels-01.sqlite3`, then fails
  later with "Publication did not arrive"; the database is still usable.
- Measurement scripts (git-ignored): `private/perf-handoff/` in the main checkout:
  `compare_card.py` (byte comparison), `cpubench.py` (CPU per rebuild; Windows CPU time has
  ~16 ms steps), `hits.py` (interval computations per rebuild), `breakdown.py` (profile shares),
  `cadence.py` (VPS capture gaps, read-only), `msxp_sampler.py` (30 s in-process stack sample of
  the live publisher via `sys.remote_exec`; Python 3.14, run as root; the API's private `/tmp`
  means the script must exist at the same path on the host and in the service's private tmp).
  Live sampling and any remote action need the owner's explicit OK each time.
- VPS: a reboot is pending for kernel 7.0.0-43 and libc; the owner plans it for a MapleStory
  Classic maintenance window.

# Layout-first HUD recognition

With `--resident-tesseract`, layout-first HUD recognition is now on by default.
Existing VPS roster/capture service commands already have that flag. Pull the
code and restart **only `msxp-tracker`**. No environment, database or API-service
changes are required.

Locally, run `msxp tracker --resident-tesseract`. Append `--no-layout-first-hud`
to compare with the previous detector. On the VPS, that switch can go in the
existing `MSXP_CAPTURE_LIMITS` in `/etc/msxp/roster.env`; preserve its other
options and restart the tracker. Remove the switch to re-enable the faster path.
Plain CLI Tesseract and explicit HUD-region caching keep their previous behavior.

## What changes

Both whole-frame scales still receive layout analysis. The worker recognizes
likely HP/MP/EXP/LV labels first and applies the existing HUD geometry and badge
checks. Original RGB EXP/level crops go through the existing neural reader. A
unique HUD with a complete full EXP or percentage-only field can take this path.
Incomplete, ambiguous or imperfect results finish ordinary OCR on the retained
full-frame pages and use the original binder.

Only the exact current-frame field response can be reused, once. No position,
reading or identity is carried across frames. Character-name checks, EXP/level
validation, freshness, database writes and publication keep their existing rules.

The pool still owns at most `min(workers, 4)` processes. Each lazily adds two
native handles for retained pages; its original handle reads crops and ordinary
fields. Native calls stay outside the coordinator. A two-page request has a
20-second limit (two existing 10-second budgets); cleanup has one second. A failed,
malformed or timed-out request fails the attempt and kills its worker. The next
attempt starts a fresh worker. Each worker is exclusively leased during
localization and released before field OCR, including on early return/shutdown.

## Verification

Full suite: **3341 passed, 75 skipped, 1 known expected failure**. Clean main had
3311 passes with the same skips/expected failure; the integration adds 30 passing
tests. Skips are 68 missing private crop cases, six Linux-only cases and one
Windows symlink-permission case. Worker checks cover concurrent leases, failure,
malformed replies, recovery, stale/unused attempts, preflight and rollback.

The prototype used 225 existing fixtures, then 42 fresh frames from 14 live
authorized streamers, then another 56 fresh frames (four each). Fresh EXP and
level labels were visually checked. Neither fresh batch lost a correct baseline
reading or introduced an incorrect reading. The first shared one incorrect raw
pair with baseline, rejected by the EXP table. The second had no incorrect raw
readings, including correct rejection of a black transition and an obscuring tooltip.

After integration, all **323 frames** were replayed through the real
`capture_attempt` and isolated workers in both modes. EXP, percentage-only fields,
visual/neural levels, raw neural text and status matched the frozen replays on
every image. The faster path handled 257/323; 66 fell back. Process-tree CPU fell
**673.016 to 498.594 seconds (25.9%)**. Local elapsed time averaged 2.109 to 1.559
seconds, with some concurrent test load; these are not VPS cadence predictions.
Maximum sampled native-worker RSS was 121.4 MiB, not a peak-memory bound.

A low-priority, in-memory check on the existing Linux/Tesseract 5.5.0 VPS also
passed three saved frames: ordinary EXP, the 720p extra-level recovery, and a
black transition. It changed no services, files or database. Private images and
results remain excluded from Git. This was compatibility verification, not a
loaded-server performance trial.

Rare competing HUDs remain a limitation: 22 synthetic cases added no unique-HUD
acceptance relative to baseline, but baseline can miss tiny secondary panels.
Fallback adds overhead; an earlier mostly-fallback stress batch cost about 11%
extra CPU. Neither method guarantees perfect OCR.

## Observing a rollout

Startup logs say `Layout-first HUD: enabled, with full-frame OCR fallback.`
Run headers record `layout_first_hud: true`. Private capture JSONL attempts add
`hud_layout.path` (`selective` or `full`), its reason and per-page probe counts.
Timings add `tesseract_layout_requests` and retain recognition, capture, scheduler,
freshness and queue-wait measurements. Field confirmation now sits inside
localization timing, so compare **total recognition time** and actual intervals.

Allow workers to warm up, then compare CPU per completed capture, actual capture
intervals, fallback frequency and rejection/staleness rates with similar live
rosters. An overloaded VPS may remain at 100% CPU while completing more captures.

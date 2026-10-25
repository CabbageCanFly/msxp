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
unique HUD with a complete full EXP or percentage-only field can take this path,
including an existing, uniquely supported grammar recovery.
Incomplete, ambiguous or imperfect results finish ordinary OCR on the retained
full-frame pages and use the original binder.

The fast gate now uses the same `interpret_exp` parser as normal reading, rather
than requiring clean punctuation before those repairs can run. This covers the
existing bracket/grouping rules, one supported S/O/B glyph, complete standalone
percentages and known EXP-label tails. Raw OCR text is never rewritten. Existing
EXP-table, level, identity and temporal checks still decide whether readings are
usable; this gate only confirms that localization found a readable field.

Fallback remains deliberate for clipped fields, ambiguous interpretations,
missing percent signs and repairs needing independent arithmetic/history. These
include a leading S/B in numerical EXP, an ungrouped numeral-like opener and a
leading `1` in percentage-only text. A recoverable percentage beside an incomplete
absolute EXP field still takes the full path, which might recover the absolute
value. Context requirements attached to future parser proposals are also honored.

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

Full suite: **3373 passed, 75 skipped, 1 known expected failure**. Skips are
68 missing private crop cases, six Linux-only cases and one
Windows symlink-permission case. Worker checks cover concurrent leases, failure,
malformed replies, recovery, stale/unused attempts, preflight and rollback. The
shared-grammar checks cover existing repair families, context-dependent abstention
and normal downstream numeric/percentage eligibility.

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

### Follow-up: avoid recoverable-field rescans

A live rollout exposed repeated full fallback on Streamer_A despite a relatively
uncluttered scene: the small HUD's brackets/grouping were misread, so the fast gate
rescanned both pages before normal grammar repaired the field. On one fresh frame,
layout returned 158/212 word boxes and label recognition made 107 probes. The
avoidable cost was the subsequent full OCR and duplicate EXP request.

Six fresh frames from Streamer_A plus eight frames from two comparison streams
were captured locally and visually labelled. A paired replay of **359 images**
(the prior 323, these 14, and 22 regenerated competing-HUD cases) compared the
deployed gate with shared-grammar confirmation. No new incorrect interpreted
EXP/percentage or level appeared, and no correct usable value was lost. One
additional correct full EXP reading and two additional correct reader levels
were recovered. Existing incorrect readings remained unchanged. The competing-HUD
cases added no acceptance relative to the original detector.

Four clean raw pairs became grammar-supported pairs with identical numbers.
Single-observation projection/percentage-eligibility checks found no loss of
eligibility; two observations gained usable level/numeric evidence. Raw text and
the later validation policy remain unchanged. This does not measure long-running
history behavior under every possible capture sequence.

On the same six target frames, an interleaved local three-way run measured:

| Detector | Mean elapsed recognition | Total process-tree CPU |
| --- | ---: | ---: |
| Original detector, layout-first disabled | 2.968 s | 17.516 s |
| Deployed strict fast gate | 3.407 s | 20.094 s |
| Shared-grammar fast gate | 2.134 s | 12.641 s |

All six used the fast path with the fix; the deployed version fell back on five.
Across all 14 fresh frames, the fixed gate used about 25% less CPU than the
deployed gate in that run. Across the 359-image paired replay, CPU fell
925.109 to 891.375 seconds (3.6%); fallbacks fell from 91 to 72. Different local
runs varied in absolute timing. These results support the targeted fix, not a
promise of an equivalent whole-VPS gain.

Rare competing HUDs remain a limitation: 22 synthetic cases added no unique-HUD
acceptance relative to baseline, but baseline can miss tiny secondary panels.
Fallback adds overhead; an earlier mostly-fallback stress batch cost about 11%
extra CPU. Neither method guarantees perfect OCR.

### Missing EXP label recovery

Sometimes whole-page segmentation groups the small EXP label with the bar artwork,
although a cropped label is readable. If neither scale binds any HUD, the worker
now checks a small EXP-label region beside already-read HP, MP and LV anchors.
The actual label must be recognized with at least 0.4 confidence. Line mode is
tried first, then word mode if needed; the latter also recovered a missed frame
on Linux/Tesseract 5.5.0 without lowering the threshold.

Existing successful, partial and competing HUD geometry bypass this retry. Both
scales still participate in uniqueness, and the ordinary field, grammar, table,
identity and history checks still decide whether a reading is usable. The retry
is limited to eight in-bounds regions per scale and uses the existing native
worker and timeout. It temporarily holds both prepared images; it adds no native
engines or state shared between frames. Page diagnostics report the number of
regions retried during selective recognition as `anchor_label_retries`.

Full-page fallback also runs the same bounded label retry if neither scale binds
a HUD. Full OCR can find HP, MP and LV anchors that the selective probes missed.
HP/MP labels use the ordinary HUD parser, including labels joined to their numeric
values. The missing EXP label must still be read from pixels at the same confidence
threshold; this does not combine anchors across scales or change EXP grammar.
The original frame is held only until confirmation or fallback finishes.

Initial label-recovery validation: **3391 passed, 75 skipped, 1 known expected failure**. A final replay
of 499 saved images, including 22 competing-HUD cases and a 36-frame live sequence,
lost no correct readings, introduced no incorrect readings, and added no unique-HUD
acceptance in the competing-HUD checks. The target sequence improved from 30/36
to 35/36 correct EXP pairs; one frame remained unreadable by the detector.

Another 104 fresh images (eight each from 13 live authorized streams) matched the
deployed detector's interpreted EXP, percentage and level outputs exactly, including
its existing errors. Interleaved local three-way timings averaged 3.496 s for the
original detector, 2.366 s for deployed, and 2.365 s with label recovery. Total
process-tree CPU was 358.500, 243.047 and 242.188 seconds respectively: essentially
unchanged cost versus deployed, about 32% below the original path in this batch.
An in-memory Linux/Tesseract 5.5.0 check recovered the missed EXP pair and level,
preserved ordinary gameplay, and rejected a browser page without the game HUD.
These saved-frame checks do not measure loaded-VPS capture cadence.

Follow-up full-page retry validation: **3400 passed, 75 skipped, 1 known expected
failure**. Replaying 603 previously reviewed images plus a fresh 36-frame stream
sequence lost no correct readings, introduced no new wrong readings, changed no
unlabelled outputs, and preserved the competing-HUD rejections. In the new sequence,
34 of 35 readable EXP pairs were recovered, versus 17 with the deployed detector
and 16 with the original detector before layout-first optimization. An additional
frame had its EXP covered by an inventory tooltip and was correctly rejected;
one otherwise readable frame still could not be localized. An isolated
Linux/Tesseract 5.5.0 replay confirmed the accept/reject decisions on eight selected
frames, including both remaining failures. No stream-specific coordinates or new
digit substitutions were added.

An interleaved 48-frame local comparison used identical pixels and frozen deployed
code. The 36-frame target sequence averaged 1.525 s deployed versus 1.600 s with
the fix (about 0.074 s extra); total process-tree CPU increased 4.6%. Twelve
controls, four each for selective, full fallback and competing-HUD cases, differed
by less than 1% CPU in each group. This is a reliability improvement with a small
measured local cost, not a loaded-VPS throughput measurement.

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

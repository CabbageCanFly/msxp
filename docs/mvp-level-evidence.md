# Responsive level and recovered EXP evidence

2026-10-19, post-merge MVP policy. This supersedes the initial three-pair,
rising-percentage seed requirement in the EXP-derived level evaluation.
It changes read-time public estimates, not acquisition, OCR, grammar, requirements,
identity assignment, schema or trusted accounting.

## What blocked useful observations

- Arithmetic inference admitted only strict pairs. Grammar recovery already
  supplied EXP/percentage readings, but could not establish or renew that level.
- A level needed three distinct frames with both numeric EXP and percentage
  progression. Small real gains inside a rounding bin could not establish it.
- Arithmetic-derived level agreement deliberately stays `indeterminate` rather
  than independent verification. Numeric interval selection required `consistent`,
  discarding those EXP changes in favor of rounded percentage changes, often zero.
- Chart history also required strict-pair classification for numeric subtraction.
  Complete recovered pairs could not confirm a quarantined lower baseline.

## Focused policy change

`experimental_level_v7` / `exp_derived_level_v3` accepts the first fresh, hashed,
unique-HUD complete pair that identifies exactly one supported table level across
the existing rounding hypotheses. A unique bounded punctuation recovery is eligible
too. Repeated or stationary EXP may display that level; it never implies a gain.

The existing state machine still handles retention, reader precedence, competing
levels, wraps and expiry. Competing levels and provisional wraps still require
distinct forward observations; numeric progression now also counts when the
percentage is unchanged. Fresh arithmetic may independently reestablish a level
after a context break. It cannot connect different identities. A reader conflict
without unique arithmetic support remains a conflict and breaks continuity.

`full_reading()` is reused to decode public numerical EXP from the raw text;
supplied proposal objects are not treated as authoritative. `supported_exp()`
permits public endpoint arithmetic for a consistent pair or a pair whose level
was derived from that same arithmetic. Its validity remains `indeterminate`,
with reason `level_derived_from_exp_pairs`; `trusted` and `verified` remain false.

Both public interval paths prefer those numeric endpoints, including recovered
ones, over rounded percentage deltas. `tracked_endpoint_exp_v3` records that
policy. `percentage_continuity_v2` also permits a complete, mathematically
consistent recovery to corroborate a changed baseline using separate captures.
The loss/reset boundary still contributes no gain. Percentage-only grammar
recovery does not gain this complete-pair privilege.

Stale/duplicate frames, suspect crops, competing HUDs, invalid timestamps,
assignment changes, ambiguous or incomplete grammar, incompatible numbers and
unsupported table coverage retain their exclusions. Missing digits are never
invented. Unknown level transitions remain gaps. Reader-supported strict-window
criteria and trusted observations are unchanged; public tracked totals and pace
use their separately recorded eligible endpoint evidence.

Public levels use ordinary upright text, without a dotted underline or question
mark. Inferred level-up announcements say `Level N reached`. Hover explanations,
Advanced evidence and all underlying classifications remain available.

## Measured saved-log replay

Read-only input directory:
`private/multi-alpha/runs/20261019T080326Z-f4f3d659/`.
Both runs contain 60 attempts. Every prefix was replayed causally through the
existing diagnostics/player/history code using saved receipt timestamps and new
in-memory stores. Source SHA-256 values match before/after. No active database or
coordinator was opened or modified, and no Twitch connection was started.

| Run / result | Before | After |
| --- | --- | --- |
| CharC: first public level 43 | Attempt 37 | Attempt 1, `08:03:44.123741Z` |
| CharC: attempts 1–4 | EXP shown, level unavailable, no comparable gains | Level 43; 82,330→82,342 at fixed 21.05%; +12 EXP |
| CharC: full-run tracked estimate | 39.116 EXP / 20 intervals | 92 EXP / 55 intervals |
| streamer_g: first public level 59 | Attempt 3 | Attempt 1, recovered `381,477133.25%1` |
| streamer_g #31 | 415,930 / 36.26% visible, no resolved level/progression endpoint | Same reading; derived 59; public/progress eligible |
| streamer_g #32 | 416,913 / 36.34% visible, no resolved level/progression endpoint | Same reading; derived 59; public/progress eligible |
| streamer_g: full-run tracked estimate | 55,088 EXP / 31 intervals | 59,704 EXP / 38 intervals |

The #31→#32 interval uses **983 EXP / 26.41636 seconds**, with the original event
IDs and `grammar_recovered` provenance. #31 starts a fresh chart baseline after
failed acquisition #30; that failure is not filled with an invented observation.

Full-run totals are eligible captured estimates, not gross EXP earned throughout
every missing/uncertain period. The saved logs demonstrate projection and
mathematical support; source pixels were not re-OCRed or independently relabeled
for this task.

The wider regression replay also admits previously excluded CharE endpoints:
18,315→19,173 (+858), 159,241→159,512 (+271), and 166,503→167,413 (+910).
Each is a saved same-level interval whose first level was previously pending.
The 56→57 transition still contributes no fabricated gain.

## Validation and operation

New synthetic regressions cover the actual CharC/streamer_g strings, initial
recovery, retention/renewal, stationary EXP, fixed-percentage gains, losses,
level-ups, incomplete/competing text, source/crop/freshness checks and real
character/session/source/run boundaries. A background publisher test verifies
the homepage and character API, chart history, tracked totals, Advanced route
and OBS route against the recovered readings without trusted observations.

The existing headless browser check passed on real saved prefixes (CharC
through #4 and streamer_g through #32), with seven screenshots each. The real
pages show ordinary level 43/59 labels, numerical EXP and useful public pace.
Existing card/checkpoint/publisher parity tests remain part of the full suite.

Final validation: **1,993 Python tests passed, 1 skipped** (Windows symlink
permission); there were **no private-sample skips** in this checkout. The full
suite took 578.35 seconds with the available private fixtures. All six frontend
test files passed: **88 tests**. The 23 new MVP regressions, background publisher
integration, saved-history checks and unchanged trusted-accounting tests are
included in the Python result. `git diff --check` passed.

Ignored evidence is under `private/mvp-level-policy/`: `before.json`,
`verified.json`, replay consoles, the CharE endpoint audit, isolated browser
databases, screenshots and test outputs. No generated evidence belongs in Git.

Restart the **Python serving process** to load the new projection code and clear
its in-memory publications/checkpoints. If `multi_alpha` owns the HTTP server,
that means a controlled restart of that coordinator process; a separate web
server needs only its own restart. Capture acquisition code is unchanged. Reload
open pages for the CSS/JS changes. No migration or historical-log rewrite is
required. This task does not restart anything automatically.

The deliberate MVP tradeoff is earlier display from one plausible pair: a
self-consistent OCR mistake can therefore appear sooner. This is conditional
community-table support, not character identification or numerical verification.

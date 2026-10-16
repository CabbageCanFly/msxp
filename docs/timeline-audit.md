# OCR timeline coverage audit

The grayscale hybrid improves some useful endpoints, but does **not** resolve the
longest complete-observation gaps. The extra ten fixed-crop pairs are seven
proximity episodes, mostly near existing successes. The clearest pair-gap repair
(780 s) supplies no recognized level with either existing level recognizer.

## Reproduce

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python tools/audit_timeline.py
.\.venv\Scripts\python -m pytest tests/test_audit_timeline.py -q --basetemp private/timeline-audit/pytest-target
.\.venv\Scripts\python -m pytest -q --basetemp private/timeline-audit/pytest-full
```

The audit reuses six saved evaluations; it runs no OCR, training, capture or database
writes. `private/timeline-audit/report.json` contains every correct/incorrect/
unavailable timestamp, ranked success gaps, per-level counts, all nine transition
brackets, recovered/lost timestamps, five-second recovery episodes and conditional
numeric-guard checks. Input file SHA-256 hashes are included. The tool checks saved
scores against the frozen labels and unchanged level outputs, requiring matching
manifest/level-input hashes. It does not require historical source hashes to match
today's recognizer source.

Inputs are `private/levelup-evaluation/manifest.json`,
`private/exp-digits/levels-{fixed,adaptive}.json`, and:

| Mode | Fixed crops | Automatic HUD regions |
|---|---|---|
| Strict valleys | `private/exp-digits/recording-valleys-final.json` | `private/exp-digits/recording-adaptive.json` |
| Grammar suffix | `private/grammar-suffix/recording.json` | `private/grammar-suffix/recording-adaptive.json` |
| Grayscale hybrid | `private/numeric-classifier/recording.json` | `private/numeric-classifier/recording-adaptive.json` |

The corrected final classifier outputs are used, not the older
`*-before-source-fix.json` files. Manifest SHA-256 remains
`5ad4f858f4bcd8e5b3846704f88bda091c93a78e9b8bf16a0e710fa697dc842c`.

## Complete observations

Each cell is **correct / incorrect / unavailable**, out of 117. A pair requires an
experimental complete candidate, not merely correct EXP. A triple additionally
requires the saved recognizer's actual level output; label levels are never used
to fill missing level OCR. These are recognition results, not production ingestion
accepts: the experimental classifier/suffix inference is not approved trust evidence.

| Regions | Mode | EXP + percentage | + Tesseract level | + pixel level |
|---|---|---:|---:|---:|
| Fixed | Strict | 50 / 0 / 67 | 35 / 0 / 82 | 31 / 0 / 86 |
| Fixed | Grammar | 54 / 0 / 63 | 39 / 0 / 78 | 32 / 0 / 85 |
| Fixed | Grayscale | 64 / 0 / 53 | 46 / 0 / 71 | 37 / 0 / 80 |
| Automatic | Strict | 46 / 0 / 71 | 31 / 0 / 86 | 27 / 0 / 90 |
| Automatic | Grammar | 50 / 0 / 67 | 35 / 0 / 82 | 29 / 0 / 88 |
| Automatic | Grayscale | 59 / 0 / 58 | 41 / 0 / 76 | 33 / 0 / 84 |

No correct pairs or triples are lost in either strict → grammar or grammar → hybrid.
No incorrect complete results appear in these outputs. This does **not** vindicate
level OCR: cached fixed-crop Tesseract still independently misreads level 8 as 3 at
599 s and level 9 as 8 at 1061.75 s. Missing percentages happen to prevent complete
candidates at those timestamps; EXP rejection is not evidence of correct level OCR.

## Newly recovered episodes

Seconds are relative to recording start. An episode groups successive recoveries
within five seconds at the same labeled level. This is an explicit descriptive
grouping, not a claim of independent trials or a production continuity threshold.

| Fixed-crop hybrid recovery | Level | EXP / percentage | Effect relative to grammar |
|---|---:|---|---|
| 239 | 4 | 7 / 7.61 | Between existing pairs at 238 and 240; Tesseract triple added |
| 384.25, 384.5 | 6 | 57 / 15.32 | Existing pair at 384.75; Tesseract triple added only at 384.5 |
| 420 | 6 | 66 / 17.74 | Splits pair gap 385–450 into 35 + 30 s; both triples added |
| 452, 453, 453.5 | 6 | 66 / 17.74 | Repeats the same plateau; improves last pre-level-up endpoint; both triples added |
| 780 | 8 | 280 / 33.33 | Splits pair gap 660–840 from 180 to 120 + 60 s; neither triple added |
| 1065 | 9 | 9 / 0.72 | Existing pair at 1064; neither triple added |
| 1380 | 9 | 644 / 51.85 | Splits pair/pixel-triple gap 1320–1440 from 120 to 60 + 60 s; both triples added |

Seven of ten new pairs are within 1.25 s of an existing successful pair; only 420,
780 and 1380 are more isolated. Six recoveries are level 6, and the ten frames
contain just six distinct EXP/percentage values. Four repeat `66 / 17.74`, already
recognized at 450 and 451. They are useful endpoint corroboration, not four new
independent HUD conditions.

Automatic regions recover the same list **except 420**, where the saved locator
provides no crop. That leaves nine pairs in six episodes. Fixed hybrid adds seven
Tesseract triples (239, 384.5, 420, 452, 453, 453.5, 1380) and five pixel triples
(420, 452, 453, 453.5, 1380). Automatic regions add the same triples except 420.

For context, strict → grammar adds pairs at 142.5, 142.75, 145 and 1770 in both
region modes: two proximity episodes. The first three also add Tesseract triples;
1770 adds a Tesseract triple too. Pixel gains differ by crop geometry and are fully
listed in the JSON.

## Success gaps and levels

Longest time between sampled correct complete results, in seconds. Maxima below
are identical for fixed and automatic regions; their first successes differ
(fixed 0 s, automatic 18 s). All series last succeed at the final sampled 1819 s.
Start/end coverage is reported separately and is not silently treated as a success gap.

| Observation | Strict | Grammar | Hybrid | Longest same-level gap: strict / grammar / hybrid |
|---|---:|---:|---:|---|
| Pair | 180 | 180 | 150 | 180 / 180 / 120 |
| Tesseract triple | 480 | 450 | 390 | 240 / 240 / 240 |
| Pixel triple | 420 | 420 | 420 | 180 / 180 / 180 |

Hybrid's largest pair gap is 1620–1770 (level 9 → 10). Its largest Tesseract gap
is 1380–1770 (also crosses levels); pixel remains 660–1080 (level 8 → 9).
Within-level triple gaps 1080–1320 (Tesseract) and 1440–1620 (pixel) remain beyond
the 120 s guard. Thus the most striking pair-gap repair does not fix either
level recognizer's longest within-level gap.

Fixed-crop correct counts below use **strict / grammar / hybrid**. All other
results at each level are unavailable; incorrect counts are zero.

| Level | Samples | Pairs | Tesseract triples | Pixel triples |
|---|---:|---|---|---|
| 1 | 7 | 7 / 7 / 7 | 7 / 7 / 7 | 7 / 7 / 7 |
| 2 | 12 | 8 / 8 / 8 | 8 / 8 / 8 | 6 / 6 / 6 |
| 3 | 10 | 5 / 8 / 8 | 5 / 8 / 8 | 3 / 4 / 4 |
| 4 | 13 | 3 / 3 / 4 | 3 / 3 / 4 | 0 / 0 / 0 |
| 5 | 9 | 1 / 1 / 1 | 0 / 0 / 0 | 0 / 0 / 0 |
| 6 | 10 | 4 / 4 / 10 | 2 / 2 / 7 | 2 / 2 / 6 |
| 7 | 14 | 6 / 6 / 6 | 1 / 1 / 1 | 4 / 4 / 4 |
| 8 | 13 | 5 / 5 / 6 | 5 / 5 / 5 | 1 / 1 / 1 |
| 9 | 25 | 9 / 9 / 11 | 2 / 2 / 3 | 7 / 7 / 8 |
| 10 | 3 | 2 / 3 / 3 | 2 / 3 / 3 | 1 / 1 / 1 |

The remaining sample is the black/missing HUD at 454 s. Automatic-region differences:
all modes lose four early level-1 successes; hybrid also loses 420 s at level 6;
grammar and hybrid gain one pixel triple at level 10 (1770 s) because the saved
automatic level crop recognizes it whereas the fixed level crop does not. Fixed
and automatic level outputs therefore are not interchangeable.

## Nine level-transition neighborhoods

The label bracket is the last sampled old level and first sampled new level,
not a frame-exact event time. Each result cell is hybrid's **last correct old-level
timestamp → first correct new-level timestamp**, fixed crops. A dash means no
complete result anywhere in that level, not EXP zero.

| Change | Label bracket (s) | Pair endpoints | Tesseract triple endpoints | Pixel triple endpoints |
|---|---|---|---|---|
| 1 → 2 | 19.25–19.5 | 19.25 → 19.5 | 19.25 → 19.5 | 19.25 → 20 |
| 2 → 3 | 142.25–142.5 | 120 → 142.5 | 120 → 142.5 | 120 → 144 |
| 3 → 4 | 236.25–236.5 | 236 → 238 | 236 → 238 | 236 → — |
| 4 → 5 | 284.5–284.75 | 281 → 360 | 281 → — | — → — |
| 5 → 6 | 384–384.25 | 360 → 384.25 | — → 384.5 | — → 420 |
| 6 → 7 | 453.5–454.25 | 453.5 → 454.25 | 453.5 → 454.5 | 453.5 → 454.75 |
| 7 → 8 | 598.75–599 | 480 → 600 | 454.5 → 600 | 480 → 660 |
| 8 → 9 | 1061.5–1061.75 | 960 → 1064 | 960 → 1080 | 660 → 1080 |
| 9 → 10 | 1769.75–1770 | 1620 → 1770 | 1380 → 1770 | 1620 → 1819 |

Strict → grammar moves the first level-3 pair/Tesseract triple from 143 to 142.5 s
and the first level-10 pair/Tesseract triple from 1800 to 1770 s. Hybrid chiefly
improves 5 → 6 and 6 → 7: earlier new-level-6 evidence and later old-level-6
evidence. Tesseract's old-level endpoint for 6 → 7 moves from 385 to 453.5;
pixel's moves from 451 to 453.5. At 9 → 10, Tesseract's last level-9 endpoint moves
from 1320 to 1380, still far from the boundary. Other brackets remain unchanged.
Automatic-region endpoints are identical except pixel's first level-6 result is
450 instead of 420 and its first level-10 result is 1770 instead of 1819.

Using a descriptive five-second neighborhood on **each side** of the label bracket,
hybrid has Tesseract triples on both sides of only 1 → 2, 3 → 4 and 6 → 7
(grammar had the first two). Pixel has only 1 → 2 and 6 → 7 in every mode.
This is not sufficient confirmation evidence for a general automatic level-up policy.

## Tracker implications and priorities

The audit calls existing `validate_transition` for correct triple endpoints, never
for pairs with oracle-filled levels. Checks assume an explicitly selected unchanged
character/session, an operator-confirmed baseline at each level, calibrated trust
evidence, and exclusively soft OCR interruptions between endpoints. Known intervening
level changes, numeric decreases or incorrect candidates are flagged conservatively.
Offline/hard-pause history and real identity/session continuity cannot be established
from these screenshots. These checks are conditional opportunities, not a production
replay or a claim of persisted gains.

- At 780 s, pairs could split a 180 s gap into 120 + 60, but missing recognized
  level prevents using that repair for guarded ingestion. The 120 s limit alone
  never establishes identity, continuity or trust.
- At 1380 s, pixel already had compatible same-level endpoints at 1320 and 1440
  exactly 120 s apart. Splitting their verified 227 EXP net difference into
  121 + 106 improves freshness, not total countable EXP. No timing inside either
  interval may be invented. Across both region modes, hybrid adds **no** net
  same-level EXP opportunity over grammar using pixel triples in this conditional check.
- With Tesseract, 1380 provides a genuine additional level-9 endpoint (121 EXP
  after 1320); later level-9 triples are still missing. At level 6, the earlier
  384.5 baseline permits observing 57 → 60 at 384.75 and then 60 → 66 at
  420 (fixed) or 452 (automatic). Repeated later 66s add corroboration, not EXP.
  These would matter only after the selected character's new-level baseline is
  explicitly confirmed; production currently flags level changes as ambiguous
  and preserves its old trusted baseline until a new session is explicitly started.
- Neither recognizer now repairs its worst within-level triple gap. There is no
  new basis for relaxing trust, carrying levels indefinitely, inferring hidden
  digits, bridging hard pauses, or counting any cross-level EXP.

Five consequential remaining regions, referencing saved diagnostics rather than
new threshold experiments:

1. **236.25–384 s, levels 3–5:** percentage suffix/segmentation fails at 236.5,
   236.75 and 237 (`no_separate_percent_suffix`, 3.26%); other percentage digits
   remain unverified at 284.5 (97.83%), 284.75 (0.00%) and 384 (82.96%). Level 5
   has only one pair (360), no triples; pixel also has no level-4 triples.
2. **480–660 s, level 7 → 8:** 99.29/99.64% digits fail at 598–598.75; at 599
   the percentage segmentation fails and Tesseract independently says level 3.
   The hybrid does not improve this transition or late-level-7 coverage.
3. **660–1080 s, level 8 → 9:** the rescued 33.33% at 780 has neither level
   output. 19.88% (720), 91.07% (1020), and both fields near 839 / 99.88%
   (1061–1061.5) still fail. Pixel's complete-observation drought remains 420 s.
4. **1080–1620 s, level 9:** Tesseract gap 1080–1320 is 240 s; pixel gap
   1440–1620 is 180 s. Correct pairs at 1500 lack either level, and 1560's EXP
   (897) is unverified despite a correct percentage. Extra EXP recognition alone
   cannot repair these level/EXP combinations.
5. **1620–1770 s, level 9 → 10:** EXP and percentage fail at 1680/1740, then
   bracket verification fails at 1769–1769.75 with four-digit EXP (1237–1241).
   The final old-level endpoint remains distant; 1770's good new-level pair
   cannot establish the missing cross-level gain.

Details are in `private/numeric-classifier/recording{,-adaptive}.json`; corresponding
crops are under `private/levelup-evaluation/evaluation-crops/recording-crops/` in
millisecond-named directories, e.g. `0780000/exp-crop.png` and
`1769750/exp-crop.png`. No private imagery was copied to tracked directories.

For practical tracking, **level-recognition coverage is the next major blocker**:
64 fixed pairs reduce to 46 Tesseract or 37 pixel triples. Prioritize diverse,
verified level examples, with numeric examples targeting these persistent high-
percentage/four-digit regions rather than more repeats of the level-6 plateau.
Segmentation needs a bounded fix for its known cases; this audit does not make it
the dominant global failure. Temporal evidence may confirm an already readable
transition, but cannot supply missing numbers or prove character identity.
Reserve a genuinely independent labeled stream for validation before integration;
another round on this same recording cannot establish generalization.

## Limits and checks

These 117 frames span sampled timestamps 0–1819 s, with 116 readable HUDs and one
black frame. Of 116 adjacent sample intervals, 74 are at most one second; 20 are
60 s. Many quarter-second transition frames repeat unchanged values. Success gaps
are gaps between **sampled correct observations**, not measured continuous OCR
blackouts; unsampled seconds are unknown. These results cannot predict 10/15/30 s
worker success rates, outage duration, time-weighted coverage or real reacquisition
latency. No footage was collected or resampled for this audit.

Development/calibration overlaps this recording, and labels were independently
transcribed before OCR by one reviewer, not double-labeled. Zero known complete
errors is benchmark evidence, not an error-rate guarantee. Accounting, recognition,
models, thresholds, profiles and labels are unchanged.

Validation: 12 focused audit tests passed; the full suite passed **502 tests, zero
skips**. The tests use synthetic records and cover score/input validation, lost
readings, episode grouping, unavailable versus incorrect results, transition
brackets, the inclusive 120 s boundary, large gains and contrary intermediate evidence.

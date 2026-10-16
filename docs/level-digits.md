# Experimental level-digit recognition

This is an isolated Pillow prototype in `tools/level_digits.py`, not production
OCR or automatic level-up support. Capture, EXP profiles/guards, tracking,
SQLite, statistics and overlay are unchanged. No dependencies were added.

## Method and calibration

Bright orange tile cores separate digits even when darker tile borders touch
(notably level 10). Each core gets a one-pixel border. White digit ink uses the
minimum RGB channel at thresholds 160/180/200; no glyph resizing is performed.
Native bitmap matching allows one-pixel alignment shifts, at most three differing
pixels and a two-pixel margin over the next digit class. These are experimental
matching distances, not confidence probabilities.

The default requires two agreeing thresholds; any matched disagreement or
ambiguous threshold vetoes the digit. Every digit must pass, with no leading zero,
and the complete level must be 1–200. Unknown geometry, damaged/clipped tiles,
extra orange fragments and incomplete digit families are rejected. A different
native size requires another complete ten-digit family; a synthetic two-size
test exercises this bank. There is no Tesseract fallback or temporal smoothing.

The [MapleLand reference README](https://github.com/myungwoo/mapleland-exp-tracker-web)
describes separate orange level-tile glyph matching. Its
[MIT license](https://github.com/myungwoo/mapleland-exp-tracker-web/blob/main/LICENSE)
was checked. Only the concept informed this independent implementation; no
third-party implementation or glyph assets were copied. Its actual source
implementation was not retrieved during this task. Game-derived templates here
remain private regardless of that project's code license.

## Evaluation protocol

Eleven existing, visually labeled development frames at 5, 50, 160, 250, 320,
400, 500, 700, 1250, 1700 and 1805 seconds supplied the native digit templates.
These timestamps are disjoint from the frozen 117-frame benchmark. Training
uses manual per-field levels and verified tile counts, never OCR predictions.
All eleven development levels pass both variants; this is resubstitution.

**These are same-recording measurements, not independent cross-stream validation.**
Repeated glyph rasters, encoder and font are shared. The recording has already
been inspected in earlier experiments; the four known-error regression cases
were checked before this full run. No model changes followed those checks.
The two matcher variants, development annotations and profile were hashed before
full scoring and stayed unchanged. Frozen benchmark labels were not edited or
used for calibration. Existing labels have one visual reviewer, not a second
independent human verification pass.

Scoring is level-only: EXP recognition and guard results provide no evidence
for level correctness. All 117 inputs count, including one black/missing HUD.
Unavailable includes both an ambiguous match and absent/unsupported input.

| Same saved native level crops | Exact correct | Incorrect accepted | Unavailable |
| --- | ---: | ---: | ---: |
| Current adaptive Tesseract level helper | 68 | **2** | 47 |
| Native matcher, threshold 180 only | 58 | **1** | 58 |
| Native matcher, default threshold consensus | **57** | **0** | 60 |

The single-threshold alternative is unsafe: it reads true level 6 as 5 at
384.25 s. Default consensus rejects it. The matcher was not retuned after scoring.

| True level | Frames | Tesseract correct / wrong / unavailable | Default correct / wrong / unavailable |
| --- | ---: | --- | --- |
| 1 | 7 | 7 / 0 / 0 | 7 / 0 / 0 |
| 2 | 12 | 12 / 0 / 0 | 9 / 0 / 3 |
| 3 | 10 | 10 / 0 / 0 | 6 / 0 / 4 |
| 4 | 13 | 10 / 0 / 3 | 0 / 0 / 13 |
| 5 | 9 | 0 / 0 / 9 | 2 / 0 / 7 |
| 6 | 10 | 7 / 0 / 3 | 6 / 0 / 4 |
| 7 | 14 | 2 / 0 / 12 | 5 / 0 / 9 |
| 8 | 13 | 11 / 1 / 1 | 1 / 0 / 12 |
| 9 | 25 | 6 / 1 / 18 | 20 / 0 / 5 |
| 10 | 3 | 3 / 0 / 0 | 1 / 0 / 2 |
| Missing HUD | 1 | 0 / 0 / 1 | 0 / 0 / 1 |

At 599 s, Tesseract accepts 3 instead of 8; at 1061.75 s, it accepts 8 instead
of 9. Default native matching rejects both. At 1064/1065 s, previously reported
9→5 errors are unavailable with the current Tesseract helper and the prototype.
Thus neither recognizer corrected these four frames into accepted true levels.

On the *prior automatically located regions*, the cached Tesseract baseline is
63 correct / 1 wrong / 53 unavailable; the new default is **53 / 0 / 64**.
Eight inputs lack a unique previous HUD location. No localization algorithm was
changed or rerun. Different crop borders explain differences from the controlled
fixed-crop comparison, including two versus one successful level-10 readings.

Fixed-crop default rejections: 53 unverified glyphs, four ambiguous glyphs, two
clipped tiles and one missing HUD. Most processed recording tiles are 16×18;
some are 15×18. That native geometry has substantial encoder/pixel variation
despite matching dimensions. Level 4 and 8 coverage is particularly poor.

Original screenshot 1 (level 60) has 13×15/13×14 tiles; screenshot 2 (56) has
17×18/16×19 tiles. Both are rejected by the recording profile. The Tesseract
helper reads 60 correctly and rejects 56 on those same saved adaptive regions.
No complete game-derived alphabet exists for those other geometries in this
experiment. Synthetic scale-bank success does not establish real cross-scale
or fractional-pixel rendering accuracy. No three-digit game levels were evaluated.

## Measured cost

Windows, Python 3.14.7, Pillow 12.3, Tesseract 5.4.0; separate processes,
10 ms process-tree sampling, one OCR thread requested. Image loading, FFmpeg,
HUD localization and profile loading are excluded from recognition timing.

| Level-only measurement, 117 fixed crops | Tesseract | Single | Default consensus |
| --- | ---: | ---: | ---: |
| Mean / p95 milliseconds | 409.29 / 536.11 | 1.12 / 1.66 | **2.77 / 9.14** |
| Sampled total CPU seconds | 51.266 | 0.141 | 0.266 |
| Peak process-tree RSS MiB | 64.27 | 31.63 | **31.80** |

Automatic-region default mean/p95: 2.68/9.45 ms, peak RSS 33.57 MiB. Prepared
input crops and interpreter/dependencies are included in RSS; it is not incremental
model memory. The private profile is 5,591 bytes. A separate `tracemalloc` diagnostic
loading the profile and doing 100 reads peaks at 149,427 bytes of Python allocations;
this excludes Pillow/native allocations. Short process sampling is approximate.
No Linux/VPS or live end-to-end performance was measured.

## Reproduce locally

Inspection/calibration need only the existing Pillow dependencies. Benchmarks
also use the existing optional capture dependencies for `psutil`; replaying prior
automatic regions additionally needs FFmpeg and the original local recording.
All commands below use ignored private output locations.

```powershell
# Existing private manual annotations; regenerates an equivalent separate profile:
.\.venv\Scripts\python tools/train_level_digits.py private/level-digits/training.json private/level-digits/profile-repeat.json
# Input is a cropped candidate level field, not a full screenshot:
.\.venv\Scripts\python tools/level_digits.py private/levelup-evaluation/evaluation-crops/recording-crops/599000/level-crop.png --profile private/level-digits/profile.json
.\.venv\Scripts\python tools/evaluate_level_digits.py private/levelup-evaluation/manifest.json --engine consensus --profile private/level-digits/profile.json --output private/level-digits/consensus-repeat.json
# Same command with --engine tesseract or single compares the other variants.
# Optionally add --adaptive-results private/adaptive-ocr/benchmark-final.json
.\.venv\Scripts\python -m pytest -q tests/test_level_digits.py --basetemp=artifacts/pytest-level-digits-targeted -rs
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-level-digits-full -rs
```

Benchmark exit 1 means at least one incorrect level was accepted, not necessarily
an execution failure. Inspection emits a diagnostic status, not trusted persistence.
New calibration JSON has `examples` containing `id`, relative `image` path,
pixel `box: [left, top, right, bottom]`, manually verified integer `level`,
`split: "development"`, and `family`. Every native family needs all ten digits;
level 10 can provide zero. Keep both annotations and generated profile ignored.
The CLI does not discover a complete HUD; it consumes the candidate level ROI.

Private evidence is in `private/level-digits/`: `freeze.json`, `training.json`,
`profile.json`, `{tesseract,single,consensus}-fixed.json`, `consensus-adaptive.json`,
`diagnostics.json`, and `known-cases.png`. Original benchmark labels and trusted
EXP profiles retain their original hashes. No game imagery/profile is added to Git.

Validation: **36 targeted tests passed** (31 synthetic/public, five private
regressions), and **397 full-suite tests passed, zero skipped**. The synthetic
tests cover alignment, ambiguity, threshold conflict, unknown shapes/scales,
clipping, incomplete competing geometry, complete native profile banks,
calibration provenance and level-only scoring. Inspection and calibration CLIs
and all three benchmark modes were exercised.

## Decision and next step

Worth extending as a cheap conservative verifier, **not ready for production**:
the observed wrong accepts disappeared at a substantial coverage cost. Zero
errors here cannot establish a safe false-accept rate on unseen streams. Do not
use an unchecked Tesseract fallback to recover coverage. Character identity and
level-up confirmation remain separate problems.

Next, collect permitted, independently labeled *development* examples spanning
native digit raster/phase and compression variants, plus near-confusable and
non-digit negatives. Keep another recording entirely untouched for validation.
Do not add benchmark failures as templates and call the result held-out accuracy.
For EXP, first test per-character segmentation/alignment and a bounded native
variant bank under the existing grammar, ambiguity and trust guards; measure
incorrect accepts separately. This level experiment supports that inexpensive
direction, but does not demonstrate reliable EXP recognition or justify relaxing
its safeguards. Defer production integration and automatic level-ups.

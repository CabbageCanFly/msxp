# Isolated RapidOCR CPU benchmark

**Continue evaluating direct line recognition. Do not integrate it into trust yet.**
It recovers complete, punctuation-preserving EXP/percentage readings on both new
streams, where our custom recognizers especially struggle on Stream 3. Numerical
tokens often survive even when brackets do not. Raw numerical mistakes still exist.
New-stream labels remain provisional Codex transcriptions, **zero human-verified**;
all reported matches are label agreement rather than independently verified accuracy.

## Environment and bounded protocol

The maintained `rapidocr` package was checked against its
[official installation guide](https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/install/),
[PyPI metadata](https://pypi.org/project/rapidocr/3.10.0/) and
[ONNX Runtime wheels](https://pypi.org/project/onnxruntime/1.31.0/).
Python 3.14.7 / Windows AMD64 installed **RapidOCR 3.10.0 and ONNX Runtime 1.31.0**
from official PyPI wheels in `private/rapidocr/.venv`. Production `.venv` and
`pyproject.toml` were not changed. No source compilation or new Python installation.

Bundled models: `PP-OCRv6_rec_small.onnx` (21,234,383 bytes),
`PP-OCRv6_det_small.onnx` (9,929,594 bytes); the bundled orientation model was
not used. Explicit local model paths avoid runtime model downloads. All inference
stayed local; no crop URLs or cloud endpoints were used. No visualization-font
download was needed. Model hashes and package versions are in every result JSON;
they match the published [model provenance and license notice](https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/).
These are PaddleOCR-derived weights distributed by RapidOCR under Apache-2.0;
we did not copy or redistribute the models into tracked files.

Both ONNX thread counts were fixed at one, verified `CPUExecutionProvider` only.
Orientation classification was disabled for horizontal fields. Recognition,
detector thresholds and model defaults otherwise stayed unchanged. Direct mode
returns the unfiltered line result; detection mode retains RapidOCR's default
0.5 text-score filter. No confidence cutoff was fitted to our labels.

1. Freeze 12 manual EXP crops per new stream, covering timestamps, digit widths,
   existing successes/failures, and both Stream 3 geometries. Record indices in
   `pilot-plan.json` before inference; no expected-answer-driven preprocessing.
2. Native RGB input and fixed 2× Pillow bicubic enlargement, each scored separately.
3. Default detection was too expensive: the initial pilot was stopped, followed
   by a reproducible **one-crop-per-stream cost check** at native/2×. Direct
   recognition ran on all 12 crops per stream: pilot 2× pairs were 12/12 and 6/12.
4. That justified expanding direct recognition to all 45 saved crops per stream,
   with one additional fixed **4×** bicubic variant. Every variant runs on every
   frame; no per-frame winner selection, tuning, training or model search.
5. Replay the original 117 saved fields as a separate comparison. No new video
   frames were extracted. Existing frozen labels, profiles, banks and models remain
   unchanged. All 90 new manual crop images were checked pixel-identical to the
   regions used by the saved custom-recognizer evaluations.

RapidOCR itself resizes short input images to a minimum side of 30 and its
recognizer normalizes text height to 48. Thus “native” describes the input crop,
not an absence of internal rescaling. This is documented behavior of the installed
implementation, not a change to our segmentation code.

## What the scores mean

Raw returned strings, scores, boxes and model timings are written to JSONL
**before parsing**. JSON adds parsed diagnostics, errors, input hashes and timing.

- **Complete pair:** the whole line parses without extra unknown characters.
  Existing `parse_exp` supplies bracketed syntax; a separate diagnostic parser
  also identifies uniquely separated numbers with explicitly missing punctuation.
  No numbers/decimals are reconstructed or corrected from expected answers.
- **Numeric tokens only:** an explicit opening bracket and `%` uniquely delimit
  valid EXP and percentage tokens, but the rest may be wrong. `74,059[25.17%1`
  has matching numeric tokens and an explicitly retained extra suffix `1`.
  It is **not counted as a complete pair**. Missing opening brackets that merge
  numbers remain ambiguous, even when the expected answer suggests a split.
- **Canonical raw match:** literal comparison with `EXP-with-commas[NN.NN%]`;
  compact comparison additionally ignores whitespace. These canonical strings
  derive from numeric labels, not separately human-annotated text strings.
  Valid omitted/thousands separators may preserve semantic numbers without a
  canonical raw match. Missing or changed digits never become matches.
- **Production trust:** none of these neural outputs is ingestion evidence. Even
  correctly bracketed model text lacks our calibrated pixel evidence and validated
  transition. No production guard/database path was run or weakened.
- Multiple returned text lines are not joined. Unknown labels are unscored.
  Digit-edit alignment is diagnostic only; no model confidence is treated as
  calibrated correctness or used to repair text.

## New-stream comparisons: same manual crops

Each cell is **complete label matches / mismatches / unavailable**, out of 45.
All three custom modes have identical results on each new stream.

| Recognizer | Stream 2, small HUD | Stream 3, both geometries |
|---|---|---|
| Strict valleys | 34 / 0 / 11 | 0 / 0 / 45 |
| Grammar suffix | 34 / 0 / 11 | 0 / 0 / 45 |
| Grayscale hybrid | 34 / 0 / 11 | 0 / 0 / 45 |
| RapidOCR direct, native | 43 / 0 / 2 | 21 / 0 / 24 |
| RapidOCR direct, 2× | **45 / 0 / 0** | **19 / 0 / 26** |
| RapidOCR direct, 4× | 45 / 0 / 0 | 19 / 0 / 26 |

All complete neural pair matches here also match the literal canonical raw string.
There were no parsed-but-wrong plausible complete values against these labels;
that does not mean all raw output was correct. At 2× the separately scored numeric
tokens match 45/45 Stream 2 and **44/45 Stream 3**; 25 Stream 3 results have extra
suffix `1`, and one has an ambiguous missing opener. These **26 are still rejected
as complete readings**, not silently rescued by dropping digit-like characters.

At 2×, EXP alone is 45 / 0 / 0 on Stream 2 and 44 / 0 / 1 on Stream 3. Percentage
with the conservative full-field context is 45 / 0 / 0 and 19 / 0 / 26; the
separately delimited percentage-token diagnostics are 45 / 0 / 0 and 44 / 0 / 1.
No expected values select which interpretation is used.

Stream 3 breakdown, **complete pair matches / numeric-token pair matches**:

| Geometry | Samples | Native | 2× | 4× |
|---|---:|---|---|---|
| Reference/windowed | 40 | 18 / 31 | 16 / 39 | 16 / 39 |
| Larger/full-width | 5 | 3 / 5 | 3 / 5 | 3 / 5 |

The frozen custom bank has no complete pairs in either geometry. Neural recognition
therefore shows useful transfer across both, with delimiter confusion remaining.
The full samples include the pilot: on the **33 non-pilot crops per stream**, 2×
complete matches are 33 Stream 2 / 13 Stream 3; numeric-token matches are 33 / 33.
4× offers no aggregate gain, so there is no reason to pursue further scale sweeps.

This is not an end-to-end automatic-HUD benchmark: the existing automatic-region
baselines remain **5/45 Stream 2 and 0/45 Stream 3**. Neural inference on those
automatic crops was not tested, nor were level recognition or transitions changed.

## Original recording kept separate

There are 116 numerically labeled fields plus one black/missing HUD. The neural
model returns an empty string / score 0 on that black field at all three scales;
it is unscored numerically and produces no candidate.

| Mode | Complete matches | Parsed numeric mismatches | Unavailable readable fields |
|---|---:|---:|---:|
| Strict valleys | 50 | 0 | 66 |
| Grammar suffix | 54 | 0 | 62 |
| Grayscale hybrid | 64 | 0 | 52 |
| RapidOCR native | 82 | 0 | 34 |
| RapidOCR 2× | 95 | 0 | 21 |
| RapidOCR 4× | 97 | 0 | 19 |

At 2×, EXP alone matches 99 and percentage 96; delimited token pairs match 99.
Compared with grayscale's 64, neural 2× **recovers 40 but loses nine** existing
complete matches. This is not a safe drop-in replacement. Lost timestamps: 19.5,
143, 239, 281, 384.25, 600, 780, 1064 and 1065 s. The original custom bank overlaps
this recording's calibration; pretrained neural inference received no training or
fine-tuning here. No pooled cross-recording headline score is reported.

## Important raw successes and failures

- Stream 3 **81.796 s**, 2×: `53,054[18.03%]`, score .97038. Our segmentation
  rejects this field, whereas whole-line recognition preserves it exactly.
- Stream 3 **0 s**, larger geometry, 2×: `51,025[17.34%]`, score .99654.
- Stream 2 **2276.007 s**: native `5[1.34%1` is rejected; 2× `5[1.34%]` matches.
- Stream 3 **1145.146 s**: `74,059[25.17%1`, score .96974. Numbers agree;
  closing delimiter does not. No extra digit is dropped to accept it.
- Stream 3 **3271.845 s**: `113,367138.53%1`, score .97265. The opener is
  misread as a digit. Splitting it using the annotation would be answer leakage.
- Stream 3 **3353.642 s**: `115,142[39.14%1`, score **.98728**, still malformed.
- Original **384.25 s**: `$7[15.32%]` instead of `57[15.32%]`, score .88728.
  The unknown EXP character is rejected, not converted from `$` to `5`.
- Original **1769.75 s**: `1,241199.82%]`, score **.94437**; reference percentage
  is **99.92**, also visually reviewed in the saved crop. This is a real raw
  numerical substitution, alongside the misread opener. Parser rejection is
  incidental protection, not proof that numerical predictions are always right.

For explicitly delimited fields the scored digit-edit diagnostics find no missing/
added numerical digits in these new streams; delimiter-to-`1` substitutions create
the principal malformed strings. No decimal repositioning was observed in parsed
fields. Ambiguously delimited strings cannot all be numerically scored, and the
99.92 → 99.82 example is outside that automatic alignment. Do not mistake zero
parsed mismatches for an exhaustive character-level correctness audit.

## CPU, RAM and installation size

Direct-recognition timings exclude extraction, HUD localization, external resize,
loading crops, scoring and initialization. Warm OS file caches; Windows workstation,
one ONNX thread, not a VPS. No per-frame model initialization.

| Direct line, 2× | Mean | Median | p95 |
|---|---:|---:|---:|
| Stream 2 | 32.7 ms | 21.4 ms | 54.0 ms |
| Stream 3 | 35.1 ms | 23.1 ms | 58.2 ms |
| Original | 46.8 ms | 53.1 ms | 62.3 ms |

Original timing overlapped a detector process, so it is not a controlled speed
comparison between crop families. Fresh-process direct startup: imports ~.77 s,
constructor ~8–9 ms, first model-loading/inference call ~.10–.11 s. Peak process
RSS ~143–145 MiB, settled RSS ~123–125 MiB. Three-variant runs consumed ~4.33 / 4.52
CPU seconds for the new streams; those totals also include local image/scoring work.

The unchanged-default detector check found **no text** on its one preselected crop
per stream at either native or 2×. Individual calls took **24.6–27.4 s**, peak process
RSS ~671–812 MiB. It upsizes short lines to a 736-pixel minimum side. This limited
check justifies stopping that branch; it is not a full detector accuracy estimate.

The isolated environment is ~276 MiB on disk, including ~30.3 MiB of bundled ONNX
models (~20.3 MiB recognition only). Wheel downloads totaled roughly 110 MB;
OpenCV was ~43.8 MB, RapidOCR ~27.3 MB, ONNX Runtime ~15.3 MB. Exact transitive
versions are in ignored `private/rapidocr/requirements-lock.txt`.

A persistent direct-line CPU engine looks plausible on a 1 GB VPS. At workstation
speed, one selected 2× pass for five channels every ten seconds would consume roughly
1–3% of one core for recognition. This is only arithmetic from workstation costs:
VPS speed, capture, Tesseract localization/level OCR and total service memory remain
unmeasured. Default neural detection is unsuitable for this budget in the tested form.

## Reproduce and review

For a fresh **separate** experiment environment, using the existing development pip:

```powershell
.\.venv\Scripts\python -m venv --without-pip private/rapidocr/.venv
.\.venv\Scripts\python -m pip --python private/rapidocr/.venv install --only-binary=:all: --index-url https://pypi.org/simple rapidocr==3.10.0 onnxruntime==1.31.0 psutil==7.2.2 Pillow==12.3.0
```

The saved private plan fixes indices/scales/modes. Existing installs can run:

```powershell
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/cross-stream/stream2/manifest.json --plan private/rapidocr/expanded-plan.json --all --output private/rapidocr/repeat-stream2.json
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/cross-stream/stream3/manifest.json --plan private/rapidocr/expanded-plan.json --all --output private/rapidocr/repeat-stream3.json
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/levelup-evaluation/manifest.json --plan private/rapidocr/expanded-plan.json --all --output private/rapidocr/repeat-original.json
# Optional slow detector reproduction: omit --all, use detector-plan.json.
.\.venv\Scripts\python private/rapidocr/make_review.py
Start-Process .\private\rapidocr\review.png
.\.venv\Scripts\python -m pytest -q --basetemp private/rapidocr/pytest-full
```

Private review: `review.png` / `review.csv` show 11 illustrative outputs and their
source crops, confidence, reference values and rejection status. All raw cases are
in `full-{stream2,stream3,original}.json` and matching JSONL files. `comparison.json`
lists neural recoveries/losses against each saved custom mode. Original annotations
remain under their existing directories; no prediction relabeled a frame.

Added only the experimental benchmark, synthetic parser/scoring tests, this report
and a README link. **536 tests passed, zero skips**; the production test environment
does not need RapidOCR. No training, existing recognizer/profile/threshold changes,
production integration, commits, pushes or image uploads. Private artifacts and the
experiment environment remain ignored.

The next bounded task should **continue RapidOCR direct recognition**, testing
independent visual delimiter verification and the already saved automatic regions,
with negative/obscured fields and human-reviewed labels. Do not simply strip suffix
`1` or trust a high confidence. A framework switch to PaddleOCR is not the first
choice: these weights already come from PaddleOCR. No evidence here justifies
custom neural training before checking those smaller issues. Preserve the original
glyph path while assessing conflicts and additional coverage separately.

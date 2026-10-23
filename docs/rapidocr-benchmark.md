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

That first phase tested manual crops only. The automatic-region follow-up below
uses the same saved frames; level recognition and transitions remain unchanged.

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

## Follow-up: saved automatic regions and delimiter feasibility

The same 45 frames per new stream were evaluated with the **unchanged cached
automatic regions**, native and fixed 2x bicubic inputs, direct recognition only.
Every available cached crop was checked pixel-identical to its saved frame/region
using the existing normalized `Region.pixels` conversion. Missing regions remain
in the denominator and do not receive fabricated inference timings. No locator,
model, profile, annotation or recognition threshold was changed. The original
manual results were reused, with the same model hashes and package versions.

All counts below are **provisional label matches / mismatches / unavailable**,
not independently verified accuracy. Zero Stream 2/3 labels are human-verified.
All complete pairs here also preserve canonical bracketed raw syntax.

| Input and recognizer | Stream 2 | Stream 3 |
|---|---:|---:|
| Custom strict/grammar/grayscale, automatic | 5 / 0 / 40 | 0 / 0 / 45 |
| RapidOCR manual, native | 43 / 0 / 2 | 21 / 0 / 24 |
| RapidOCR automatic, native | 32 / 0 / 13 | 26 / 0 / 19 |
| RapidOCR manual, 2x | 45 / 0 / 0 | 19 / 0 / 26 |
| RapidOCR automatic, 2x | **31 / 0 / 14** | **28 / 0 / 17** |

- Stream 2: nine missing regions, one available crop with an ambiguous opener,
  and four matching numeric-token pairs with malformed suffix `1` at 2x. Thus
  31/36 available crops parse completely, and 35/36 retain matching tokens.
  Native has three malformed-token cases and the same ambiguous opener. Neural
  preprocessing tolerates much of the old alignment problem without fixing it.
  Eight automatic regions fail the older numeric-ink containment diagnostic;
  all eight nevertheless agree numerically at both scales. This is diagnostic
  tolerance, not evidence that clipped numerical pixels are safe to trust.
- Stream 3: four missing regions, one ambiguous opener, and 12 matching-token
  suffix errors at 2x. Of 41 available crops, 28 parse and 40 retain matching
  tokens. Native has 14 malformed-token cases. At 2x the windowed geometry has
  26/40 complete pairs, larger geometry 2/5; token matches are 36/40 and 4/5.
- Relative to manual 2x, Stream 2 loses 14 complete pairs (nine missing crops,
  four suffix errors, one opener). Stream 3 gains 12 and loses three complete
  pairs, all three losses caused by missing regions: net +9. This is evidence of
  crop/context sensitivity, not a rule that tighter crops are always better.
- Both scales produced zero parsed mismatches against these labels. The saved
  locator selected no secondary HUD in these samples; this does not establish
  safe target selection when multiple Classic HUDs are visible.
- Reusing unchanged cached level readings, automatic 2x complete triples agree
  on 22/45 Stream 2 and 28/45 Stream 3 with Tesseract, zero with pixel levels.
  **None is production-trusted:** neural candidates still lack calibrated numeric
  pixel verification and the existing guarded transition. No ingestion was run.

Examples: Stream 2 at 995.753 s has expected `8[14.04%]`, but automatic 2x gives
`8114.04%1` despite the cached containment check finding all numeric ink. At
3271.760 s it gives `475[84.82%1` instead of the correctly bracketed manual result.
Stream 3 at 1145.146 s changes from manual `74,059[25.17%1` to automatic
`74,059[25.17%]`. At 3271.845 s both inputs still merge the opener into
`113,367138.53%1`. Per-frame new/lost lists are in private `audit.json`.

### Closing-bracket feasibility: do not promote suffix errors

A bounded pixel probe reused the two **frozen, earlier calibrated profiles** and
`exp_digits.brackets` with its existing green-excess thresholds and distance bound.
It uses original-resolution pixels, separate from raw neural text, and checks
ordered bracket locations against the existing text band and suffix whitespace.
No new templates, inferred brackets, training or fitted thresholds were used.

Ordered-pair mask evidence exists on 40/45 manual Stream 3 crops, including 23 of
the 25 malformed-suffix cases at 2x. The other two are the unsupported larger
geometry. On automatic Stream 3 crops it covers 37/45, including ten of the 12
malformed-token cases. However, **every supported case has ambiguous bracket
direction**: at least one selected glyph also matches the opposite bracket role.
Requiring both positions to exclude the opposite role leaves zero supported
pairs, on both streams. Some frozen masks capture a blurred green stem/rectangle
rather than a directional bracket shape. Matching these masks alone is therefore
insufficient independent delimiter verification; this is not a defect claim about
the existing full-field guard, which also verifies numeric glyphs.

Thirteen predefined synthetic/contradictory probes were made from one readable
Stream 3 crop, without using them to fit a verifier. Missing/cropped brackets,
missing opener, strongly damaged top/bottom caps, and actual white/green numeral
1 substitutions lack ordered-pair evidence. But the probe still finds brackets
after deleting/fragmenting numeric pixels or clipping numerals. Two actual 2x
model outputs show why this matters:

- A fragmented last EXP digit changes `74,059` to **`74,050[25.17%1`**, confidence
  .94653, while ordered bracket masks still match.
- A crop cutting the first numeral gives **`4,059[25.17%1`**, confidence .96340,
  while ordered bracket masks still match.

Replacing either suffix blindly would create a plausible wrong complete pair.
A separately marked injected contradictory raw string on identical pixels also
demonstrates that punctuation cannot verify numbers. The real original
**99.92 -> 99.82** raw substitution remains relevant for the same reason.
One cropped-close negative parses as a missing-punctuation diagnostic pair; its
`bracketed_syntax` is false and it has no closing-mask evidence, so it is not a
delimiter-verified candidate. Unknown digits and decimals are never reconstructed.

**No rescue rule was implemented.** New promoted pairs: zero; existing complete
pairs lost: zero; new promoted mismatches: zero. Combined automatic results remain
31/45 and 28/45 at 2x. This is a feasibility stop, not a zero-error validation of a
new verifier. There is insufficient verified calibration/negative evidence for
these new geometries to justify stronger claims or a new acceptance threshold.

### Cost, reproduction and review

Automatic direct-line 2x mean / median / p95: Stream 2 **39.9 / 26.7 / 66.9 ms**;
Stream 3 **43.9 / 32.4 / 69.8 ms**, excluding missing crops, extraction,
localization, resize and initialization. The native means are 39.5 / 40.9 ms.
Process peak RSS is about 152 / 153 MiB, settled 132 / 134 MiB; whole benchmark
CPU cost 3.98 / 4.83 s for both scales, including scoring and image checks.
Workstation measurements, not a controlled VPS/manual speed comparison.

The isolated environment, models and private inputs already exist locally:

```powershell
# plan.json fixes scales [1,2], modes ["line_recognize"]; --all selects the same 45 frames.
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/cross-stream/stream2/manifest.json --plan private/rapidocr-auto/plan.json --all --automatic-results private/cross-stream/stream2/results.json --output private/rapidocr-auto/stream2.json
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/cross-stream/stream3/manifest.json --plan private/rapidocr-auto/plan.json --all --automatic-results private/cross-stream/stream3/results.json --output private/rapidocr-auto/stream3.json
.\.venv\Scripts\python private/rapidocr-auto/audit.py
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/rapidocr-auto/negative-manifest.json --plan private/rapidocr-auto/plan.json --all --output private/rapidocr-auto/negative-results.json
.\.venv\Scripts\python private/rapidocr-auto/make_review.py
Start-Process .\private\rapidocr-auto\review-01.png
Start-Process .\private\rapidocr-auto\review-02.png
.\.venv\Scripts\python -m pytest tests/test_rapidocr_benchmark.py -q --basetemp private/rapidocr-auto/pytest-targeted
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
.\.venv\Scripts\python -m pytest -q --tb=line -rs --basetemp private/rapidocr-auto/pytest-full-current-root
```

`review.csv` has 18 review cases and blank human-review fields. Please check values,
bracket direction, missing ink and the difference between real model output and
explicitly synthetic contradictions. Editing this sheet does not modify frozen
labels. PNGs, scripts, negative crops, raw JSONL, annotations and weights stay under
ignored `private/`; no models or imagery were added to tracked directories.

Public changes are limited to this report, optional cached-region input handling
in `tools/benchmark_rapidocr.py`, and two synthetic benchmark tests. No production
code, algorithms, thresholds, profiles, frozen labels, commits or pushes changed.
The final harness was rerun: both streams' raw texts and scoring were identical
at both scales. **23 benchmark tests pass. Full suite: 529 passed, 9 failed,
zero skips** with loopback access and the current `src` on `PYTHONPATH`. All nine
failures occur while loading unchanged private banks that still reference
`H:/Desktop/msclassic-twitch-exp-tracker/private/adaptive-ocr/native-profile.json`,
before the workspace moved under `H:/Desktop/codex/`. The frozen calibration
artifacts were preserved rather than rewritten. Without loopback permission one
HTTP test skips; without the current `PYTHONPATH` the moved editable installation
also fails its subprocess import test. The public synthetic benchmark tests need
neither private fixtures nor RapidOCR. Private-path relocation remains separate
housekeeping, not an OCR result or threshold change.

Next priority: **automatic crop/context handling**, with a deterministic bounded
context policy and missing-region diagnostics, retaining raw neural outputs as
untrusted. The geometry-dependent delimiter errors and nine/four absent regions
are actionable acquisition-to-recognition losses. Before any trust integration,
independent numeric verification and human-reviewed negative calibration are also
necessary. Do not add suffix rescue using these old masks or assume high neural
confidence proves digits. No new framework or training is justified by this audit.

## Repository relocation cleanup

The earlier 529-pass/9-failure result is historical. After cleanup, **543 tests
pass, zero failures and zero skips** (80.48 s), without `PYTHONPATH`. Loopback
permission was granted for the HTTP test; restricted runners may skip it.

All nine failures were reproduced in `exp_digits.load_bank`, opening the first
profile referenced by the unchanged `private/exp-digits/bank.json`:

| Test group | Cases |
|---|---|
| `test_exp_digits.py::test_private_success_and_rejection_regressions` | 19750 ms, 599000 ms, CharA crop 0016 |
| `test_grammar_suffix.py::test_private_percent_recoveries_do_not_rescue_bad_numbers` | 142500, 1770000, 599000 ms |
| `test_grayscale_digits.py::test_private_hybrid_recoveries_and_unreadable_rejection` | 384250, 780000, 599000 ms |

The bank has 16 distinct absolute references under the former repository root:
two profiles and fourteen character source images. Every file exists under the
current root and matches its historical cross-stream SHA-256. Rewriting the bank
would break the grayscale model's `bank_sha256`, so neither artifact was changed.

The separate, ignored `private/exp-digits/bank.paths.json` instead maps each old
reference to a **bank-directory-relative path and recorded SHA-256**. For example,
the old native-profile reference maps to `../adaptive-ocr/native-profile.json`.
The shared `bank_source` resolver verifies source bytes, with no fallback after
a mapped file is missing or mismatched. Unmapped references retain existing path
semantics. Keep this sidecar with the bank during future moves. New banks should
use relative paths directly. No directory search, symlink or environment override
is needed. Experimental readers/source hashing share the resolver, and new
evaluation outputs include the sidecar as an input dependency.

Separately, the editable installation's `.pth`/`direct_url.json` and development
Windows launchers pointed to the old location. Reinstalling the project editable
and the exact existing console-script package versions (`--no-deps`) repaired
them. No dependency versions changed; `pip check` passes. Imports, `ms-exp.exe`,
`pip.exe`, `pytest.exe` and `streamlink.exe` work at the current root.

The isolated RapidOCR interpreter, imports, models and benchmark `--help` also work.
Its unused `rapidocr.exe`/`onnxruntime_test.exe` wrappers still embed the old path;
use the documented explicit interpreter and benchmark script. Neural packages and
weights were not reinstalled merely to fix those wrappers. Recreate virtual
environments after future moves, or reinstall affected editable/console packages.
Historical paths in saved results and venv creation metadata remain provenance.

```powershell
# Reinstall editable after a move; no PYTHONPATH workaround.
.\.venv\Scripts\python -m pip install --no-deps -e .
.\.venv\Scripts\python -c "import exp_tracker; print(exp_tracker.__file__)"
.\.venv\Scripts\python -m pip check
.\.venv\Scripts\python -m pytest -q -k "private_success_and_rejection_regressions or private_percent_recoveries_do_not_rescue_bad_numbers or private_hybrid_recoveries_and_unreadable_rejection" --basetemp artifacts/pytest-nine
.\.venv\Scripts\python -m pytest tests/test_bank_paths.py -q --basetemp artifacts/pytest-paths
.\.venv\Scripts\python -m pytest -q -rs --basetemp artifacts/pytest-full
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py --help
git diff --check
```

The nine regressions pass (9/9), plus five new synthetic path tests. All **204
snapshotted evidence files remain byte-identical**, including RapidOCR outputs,
review sheets, models and calibration banks; twenty private source hashes also
match the historical evaluation. Private receipt: `private/relocation-audit/before.json`.
No templates, models, annotations, production behavior, commits or pushes changed.
The repository is ready for the next crop/context experiment using the explicit
RapidOCR interpreter.

## Fixed automatic crop-context experiment

**Two pixels is promising for recognition coverage, not sufficient for trust.**
Default padding remains zero; only the isolated benchmark gains an opt-in
`--padding 0|2|4` option. Production recognition and ingestion are unchanged.

Before inference, `private/rapidocr-context/plan.json` fixed symmetric 0/2/4 native
pixel padding on all four edges, followed by the same 2x bicubic enlargement and
unchanged direct-line CPU model. Coordinates first use existing `Region.pixels`
floor/ceil conversion, then expand and clamp to the saved frame. Expanded pixels
come from original full frames, never from enlarging an already clipped crop.
Only unique cached locator candidates are used; no region fallback, locator change,
per-frame winner selection, extra scale search or later padding adjustments.

Both 45-frame denominators are retained. Labels remain **Codex-provisional, zero
human-verified**. These recordings have already been inspected in previous work;
this predefined comparison is not fresh independent-stream validation. The
unpadded rerun reproduces the original raw strings and scores/categories exactly.

Each cell below is **complete numeric label matches / mismatches / unavailable**.
Here complete requires the existing parser's bracketed syntax, both values and no
extra unknown text. Its pre-existing loose missing-punctuation diagnostics do
not count as complete observations. None of these candidates is production-trusted.

| Native padding | Stream 2 | Stream 3 |
|---|---:|---:|
| 0 px | 31 / 0 / 14 | 28 / 0 / 17 |
| 2 px | **35 / 0 / 10** | **39 / 0 / 6** |
| 4 px | 29 / **1** / 15 | 41 / 0 / 4 |

At 2 px, all previous complete matches survive: four new Stream 2 and eleven new
Stream 3 matches. Stream 2's four original suffix-`1` cases recover; its remaining
available failure (995.753 s) changes from merged `8114.04%1` to `8[14.04%1`.
Stream 3 retains two matching-token suffix failures: 3271.845 s, where the opener
is now recovered, and 3353.642 s in the larger geometry. Thus malformed-punctuation
matching-token counts change from **4 to 1** and **12 to 2**. Missing regions remain
**nine and four**, respectively. Available-crop matches are 35/36 and 39/41;
these conditional counts must not replace the full 45-frame results.

Stream 3 geometry at 2 px: windowed 36/40 (all four unavailable have no region),
larger 3/5 (one missing region, one suffix error). At 4 px these become 37/40 and
4/5; all available fields then parse. However, 16 raw Stream 3 outputs change a
thousands comma to a dot: 41 semantic pair matches, only 25 literal canonical
matches. Raw strings are preserved, not normalized before logging.

Per-frame IDs (indices into each frozen manifest):

- **2 px recovered, Stream 2:** 16, 23, 39, 44. **Lost:** none.
- **2 px recovered, Stream 3:** 3, 13, 26, 28, 30, 31, 32, 35, 37, 38, 42.
  **Lost:** none.
- **4 px recovered, Stream 2:** 23, 39, 44. **Lost:** 12, 20, 21, 25, 42;
  index 21 becomes an incorrect complete candidate, the others lose their opener.
- **4 px recovered, Stream 3:** the eleven above plus 40 and 41. **Lost:** none.

Exact timestamps, before/after raw strings, confidence, categories and crop boxes
are in private `per-frame-changes.csv` and `comparison.json`. The four Stream 2
2-px recoveries occur at 2276.007, 3271.760, 5547.768 and 6259.020 s. The Stream 3
recoveries span 245.388 through 3435.438 s; sparse samples do not establish
continuous tracking or transition reliability.

### Context contamination and negative cases

At Stream 2 **2987.260 s**, 4 px yields **`2345[92.74%]`**, score .96809, instead
of `345[92.74%]` at 0/2 px. Visual inspection shows a partial neighboring EXP
label at the left and the progress bar below entering the expanded crop. The
label fragment appears to become the extra `2`; this is a plausible wrong number
with valid punctuation, not something the parser can safely correct. Four pixels
is therefore unsuitable as a global policy despite its Stream 3 coverage.

Seven predefined synthetic full-frame negatives reuse one existing Stream 3
source: deliberately clipped numerals, a fragmented digit, an erased digit,
missing decimal, absent close, damaged close and an actual green numeral `1`
in the closing position. Original files and frozen labels remain untouched.
These stress cases retain the source's intended numerical value; they are not
new independently verified video annotations or training examples.

- Baseline accepts the clipped-numeral image as wrong `4,059[25.17%]`; 2 px makes
  that string unavailable, but introduces a different wrong complete candidate.
- **Fragmented digit:** 0 px gives rejected `74,050[25.17%1`; 2 px gives
  **`74,050[25.17%]`**, score .96343, versus source intent 74,059. Padding fixes
  punctuation while preserving the wrong digit. Four pixels also produces it.
- The remaining five negatives stay unavailable under the strict complete-pair
  definition at every padding. In particular, missing close produces a loose
  numeric diagnostic, not a complete pair; the green numeral `1` is never replaced.

Consequently strict wrong complete negatives number **1 / 1 / 2** at 0/2/4 px;
the 2-px wrong case is newly introduced even though the aggregate count is equal.
No candidate is promoted to trusted state. This counterexample prevents claiming
that 2-px padding is a safe acceptance rule or that punctuation verifies digits.

### Cost and reproduction

Workstation inference-only mean / median / p95 in milliseconds, one measured pass:

| Padding | Stream 2 | Stream 3 |
|---|---|---|
| 0 | 32.2 / 26.8 / 64.9 | 37.0 / 27.1 / 65.2 |
| 2 | 22.5 / 20.9 / 48.3 | 29.5 / 21.9 / 55.8 |
| 4 | 21.1 / 20.1 / 25.4 | 27.9 / 20.8 / 49.3 |

Full-frame loading, cached-crop verification and cropping separately average
30-35 ms per available frame, with no meaningful padding-related increase.
Peak process RSS is about 160-162 MiB. At 2 px whole-loop CPU cost is 1.89 s for
Stream 2 / 2.50 s for Stream 3, versus 2.22 / 2.84 s unpadded. Initial input
hashing, model startup, stream capture and localization are excluded. Padding
changes the model's normalized input geometry; the observed faster inference is
not a controlled speed guarantee or a VPS measurement.

```powershell
# All old outputs preserved; reruns below go into a separate directory.
foreach ($stream in 'stream2','stream3') {
    foreach ($padding in 0,2,4) {
        .\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py "private/cross-stream/$stream/manifest.json" --plan private/rapidocr-context/plan.json --all --automatic-results "private/cross-stream/$stream/results.json" --padding $padding --output "private/rapidocr-context/repeat/$stream-pad$padding.json"
    }
}
# Inspect/analyze the saved initial run, including negative results:
.\.venv\Scripts\python private/rapidocr-context/analyze.py
Start-Process .\private\rapidocr-context\review-01.png
Start-Process .\private\rapidocr-context\review-02.png
Start-Process .\private\rapidocr-context\negative-review.png
.\.venv\Scripts\python -m pytest tests/test_rapidocr_benchmark.py -q --basetemp private/rapidocr-context/pytest-targeted
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/rapidocr-context/pytest-full
```

`prepare_negatives.py` reproduces the private synthetic frames/cached regions.
To rerun their inference, use `negatives/manifest.json` and `negatives/results.json`
instead of the real-stream paths, with the same plan and padding variants, and
a new output filename. Exact raw outputs/confidences precede parsing in JSONL.
The result JSON records crop boxes, padding and input/model hashes.

This task changes only the experimental benchmark, its synthetic tests and this
report; earlier uncommitted relocation work is preserved. **41 benchmark tests
pass; full suite 561 passed, zero skips** (82.19 s with loopback access).
All **205 prior snapshotted evidence files remain byte-identical**, including
old benchmark outputs, frozen annotations, profiles and model weights. New frames,
review sheets and result artifacts remain ignored. No commits, pushes, production
integration, model changes or threshold tuning.

Next priority is **numeric verification**, particularly clipped/degraded numerals
and adjacent label contamination. Localization recovery is the next coverage
step: thirteen of the sixteen remaining real-sample failures at 2 px have no ROI.
Keep 2 px available for bounded experimental comparison; retain baseline defaults
until it has independent validation and stronger numeric evidence. More suffix
tolerance or broader padding searches are not justified here.

The subsequent [EXP/percentage consistency diagnostic](exp-consistency.md) uses
external community requirements and explicit rounding hypotheses. It flags gross
inconsistencies, but unverified UI semantics and percentage precision prevent
using it as an authoritative validator or repairing neural outputs.

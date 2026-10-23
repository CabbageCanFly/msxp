# Per-character EXP experiment

**A modest accuracy improvement, still an isolated experiment.** Complete EXP +
percentage recognition rises from 41 to 50 on the 117 saved recording crops,
and from 14 to 15 on the original 17-frame CharA trial. No incorrect EXP,
percentage or complete readings were accepted in these evaluations.

## What changed

`tools/exp_digits.py` separates colored brackets from white text, splits white
characters using column projection, and matches native bitmaps with bounded
one-pixel alignment. The alternative/default `valleys` mode also splits at
low-ink columns to handle compression bridges. Every pixel belongs to a segment;
unknown characters are not removed. Both modes enforce observed punctuation,
field grammar, spacing checks for erased internal slots and ambiguity rejection.
Partial EXP/percentage outputs remain diagnostic; a complete pair must share
one segmentation. The result is an experimental `candidate`, not trust evidence
for ingestion. No Tesseract EXP fallback is used.

Existing v2 bracket profiles retain their original thresholds and four-pixel
distance bound. Empty masks cannot verify brackets. Digits permit three differing
pixels with a two-pixel class margin. Development leave-cell-out comparisons
supported keeping this conservative bound: 57/66 native digits were within three
pixels, but wrong classes were as close as two pixels; relaxing distance alone
would confuse some 8/9/3 shapes. Tiny comma/decimal masks require an exact match
and a one-pixel margin because those development classes differ by one pixel.
Scores are geometric distances, not calibrated probabilities.

No additional calibration images were introduced. The private bank contains
128 visually reviewed character boxes from the existing labeled development
material: 89 native recording characters and 39 CharA characters, including
punctuation. These reuse two native geometries, not a larger collection of whole
field profiles. Bracket templates are reused unchanged. The public loader accepts
relative image/profile paths and requires development labels and a complete
alphabet. It builds the small bitmap bank once at setup.

## Evidence and limitations of the comparison

Earlier fixed-cell diagnostics found digit-distance failures on 73 readable
frames, punctuation failures on 18 and bracket failures on seven (overlapping).
Development inspection found occasional joined digits and characters clipped
by fixed advances, particularly later characters in `1,093[88.00%]`. Separating
characters recovers their native shapes without stretching the entire string.
Connected components would also join pixels at compression bridges; column
projection with a bounded split was the smaller useful experiment here.

The first benchmark attempt rejected every saved crop because a separate bright
progress-bar row expanded the detected text height. Row selection was corrected
using a synthetic regression; no numeric labels or matching thresholds changed.
Both attempts and freeze hashes are retained privately. A later review added an
explicit empty-bracket-mask check. Actual templates have at least 19 foreground
pixels, so empty masks already exceeded the four-pixel bound; all 134 fixed-crop
results and detailed evidence were repeated identically after that safety fix.

**These are same-recording/same-stream development comparisons.** The eleven
recording development timestamps remain disjoint from the frozen 117 labels,
but share font, encoder and often nearly identical rasters. The CharA trial
was not used for calibration; it shares the streamer/rendering geometry of its
older development captures. Its 14 accepted values had been reviewed by the
user; all available crops were visually reviewed here before evaluation,
including rejected frames 3 and 16. Frame 6 has no saved EXP crop and stays
unavailable. No label was generated from this recognizer's predictions.

## Results

Each cell is **correct / incorrect / unavailable**. Recording totals include the
one missing HUD. Baseline fields are coupled by the old whole-line matcher;
the new partial field counts do not represent trusted complete observations.

| Saved recording crops, 117 | Baseline | Columns | Valleys |
| --- | --- | --- | --- |
| Numeric EXP | 41 / 0 / 76 | 89 / 0 / 28 | **90 / 0 / 27** |
| Percentage | 41 / 0 / 76 | 60 / 0 / 57 | **60 / 0 / 57** |
| Complete EXP + percentage | 41 / 0 / 76 | 49 / 0 / 68 | **50 / 0 / 67** |
| Complete with unchanged Tesseract level helper | 29 / 0 / 88 | 34 / 0 / 83 | **35 / 0 / 82** |
| Complete with unchanged pixel level recognizer | 27 / 0 / 90 | 31 / 0 / 86 | **31 / 0 / 86** |

With the **previous automatic HUD regions**, complete EXP pairs rise from
**37 to 46 / 117**, with zero wrong pairs. Numeric EXP is 79 / 0 / 38; percentage
is 55 / 0 / 62. Complete readings with Tesseract levels rise from 25 to 31;
with pixel levels, 23 to 27. Locator failures remain unavailable. The existing
locator was not changed or rerun on the recording. Cached level-only outputs
were joined for scoring; EXP rejection is never evidence that a level is correct.

On **CharA**, both new modes yield **15 / 0 / 2** for numeric EXP, percentage,
complete EXP and complete readings with the unchanged adaptive Tesseract level
helper, versus baseline **14 / 0 / 3**. All 14 old successes are retained. The
recording-only pixel level profile rejects every CharA level crop; combining it
would yield zero full readings. No new level calibration was performed.

Recording gains are not monotonic: 14 new complete successes and five losses.
By EXP digit count, default complete results are **21/36** (one digit), **10/29**
(two), **19/41** (three), and **0/10** (four); all other cases are unavailable.
CharA's six-digit values work in its supported smaller raster. Width alone is
therefore not the cause: rendering variation, punctuation and ambiguity interact.

Concrete examples, pictured in `private/exp-digits/results-examples.png`:

- 19.75 s and 30 s: newly correct **4 / 11.76%**.
- 280 s: **84 / 91.30%** was accepted before; now rejected because the first
  digit's class margin is only one pixel. Three `66 / 17.74%` frames at
  452–453.5 s similarly lose acceptance. No margin was relaxed to recover them.
- 599 s: EXP **0** is independently recognized, but the percentage has merged
  zeros and a degraded percent glyph. No complete candidate is produced, so
  the existing erroneous Tesseract level 3 does not become a complete accept.
- 1061.75 s: EXP **1** is readable; the percentage's 8 is ambiguous and its
  percent glyph differs too much. The known wrong Tesseract level remains unsafe.
- 1740 s: **1,169 / 94.12%** remains unavailable. Several glyphs exceed distance
  limits. Near 1769.5 s, a bracket cannot be verified either.
- CharA frame 16: newly correct **879,440 / 72.68%**, including both verified
  brackets. Frame 3 remains rejected; frame 6 has no EXP evidence.

`samples/maplestory-classic-stream4.png` exists and was tested without calibration.
Visual truth is **level 1 / EXP 9 / 60.00%**. The unchanged locator found no HUD;
manual crop diagnosis also rejected EXP with this bank. Both level recognizers
read 1 on that manual crop. Its layout/content resembles the recording and its
independent-stream provenance is unestablished. This is an unseen-image failure,
not evidence of independent-stream success.

## Cost and reproduction

Windows, Python 3.14.7, Pillow 12.3; separate sequential processes, 10 ms sampling.
Times exclude file/profile loading, capture, localization and level OCR. The
fixed saved recording crops are 135×18 and include padding/progress-bar context;
the earlier 3.18 ms baseline used tighter EXP crops and is not this comparison.

| EXP + percentage only | Baseline mean / p95 | Default mean / p95 | Default total Python CPU | Default peak RSS |
| --- | --- | --- | --- | --- |
| Recording, 117 | 18.62 / 24.46 ms | **20.09 / 26.23 ms** | 2.266 s | 32.24 MiB |
| CharA, 17 | 2.12 / 2.79 ms | **6.10 / 9.57 ms** | 0.094 s | 30.21 MiB |

Baseline peak RSS was 31.32 and 29.86 MiB respectively. The initial automatic-ROI
run averaged 14.44 ms, peak 35.14 MiB. RSS includes interpreter, prepared crops
and accumulated diagnostics. The 43,503-byte calibration JSON retains about
125 KB of Python allocations after loading; separate traced peak was 375 KB
during loading and 194 KB during repeated recognition, excluding native/Pillow
allocations. These are workstation measurements, not Linux VPS or live latency.

Existing dependencies suffice; the evaluator uses existing optional `psutil`.
The private bank and evaluation files are intentionally absent from public Git.

```powershell
.\.venv\Scripts\python tools/exp_digits.py artifacts/green-test-20261015-215403/0016/exp-crop.png --bank private/exp-digits/bank.json
.\.venv\Scripts\python tools/evaluate_exp_digits.py private/levelup-evaluation/manifest.json --engine valleys --bank private/exp-digits/bank.json --levels private/exp-digits/levels-fixed.json --output private/exp-digits/recording-repeat.json
.\.venv\Scripts\python tools/evaluate_exp_digits.py private/levelup-evaluation/manifest.json --engine baseline --profile private/adaptive-ocr/native-profile.json --levels private/exp-digits/levels-fixed.json --output private/exp-digits/baseline-repeat.json
.\.venv\Scripts\python tools/evaluate_exp_digits.py private/exp-digits/streamer_a-manifest.json --engine valleys --bank private/exp-digits/bank.json --levels private/exp-digits/levels-streamer_a.json --output private/exp-digits/streamer_a-repeat.json
# Use --engine columns for the first segmentation method.
# For automatic recording regions, replace --levels with levels-adaptive.json
# and add --adaptive-results private/adaptive-ocr/benchmark-final.json (requires FFmpeg).
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-exp-digits-full -rs
```

Evaluator exit 1 flags any incorrect metric, including an incorrect level paired
with correct EXP. Detailed outputs, calibration boxes, failures and hashes are
under `private/exp-digits/`. The bank JSON has `version: 1` and `families`, each
containing an existing v2 bracket `profile` path and `characters` with `image`,
`char`, native pixel `box` and `split: "development"`. Inspect these boxes manually;
do not train from OCR predictions. Public tests generate their own invented font.

Validation: **30 targeted tests passed** (27 public, three private regressions).
The full suite passed **426 with one sandbox loopback skip**; that HTTP test then
passed separately with local socket access. No sample skips or test failures
remain. Original profiles/labels and production source were preserved. No new
footage, dependencies, commits or pushes.

## Recommendation

Keep this as an experimental verifier, not a replacement: 50/117 complete pairs
is still low coverage, and the extra segmentation alternative gains only one
recording frame. Further threshold tuning or template accumulation is unlikely
to establish general reliability from these correlated samples.

Next test a small grayscale digit/punctuation classifier on padded individual
glyph crops, retaining explicit unknown rejection, bracket verification and
grammar. Require verified development examples with compression/raster variation,
confusable negatives and a different untouched recording for validation. Measure
wrong accepts and CPU/RSS before choosing a runtime or integrating it. A wholly
missing leading digit remains indistinguishable from a shorter value without
reliable field-start evidence; recognition cannot establish character identity
or source freshness. Production integration and automatic level-ups remain deferred.

## Grammar-assisted suffix follow-up

An optional `--grammar-suffix --localized` mode tests whether predictable `%]`
punctuation explains the remaining failures. Strict mode remains the default.
`--localized` asserts a separately verified field ROI; this is not a new HUD
detector. Evaluation uses the existing saved field crops or previously verified
automatic regions. Do not assert it for an arbitrary stream crop.

Percentage digits and the decimal still pass the unchanged native matcher and
exact `D.DD`/`DD.DD` grammar. An inferred percent must be a separate last component,
closer to `%` than every numeric alternative by at least four pixels, with a
native bounding box within one pixel of a template and at most one quarter of
its ink count in differing pixels, rounded up and capped at eight. An inferred close must have green stroke
evidence with comparable native geometry/agreement, be distinctly unlike numeric
glyphs, and hide at most two white pixels. The opening bracket is always verified
strictly. Empty/missing symbols, arbitrary blobs, unknown numbers and extra
digit-like components are rejected. Attempt diagnostics explicitly mark inferred
symbols; these candidates do not enter production trust or persistence.

One rule was fixed using synthetic positive/negative tests before the frozen
recording/CharA runs; no threshold sweep or new templates were used. All figures
below have **zero incorrect numeric, percentage or complete outputs**.

| Correct readings | Strict per-character mode | Grammar-assisted mode |
| --- | ---: | ---: |
| Percentage, 117 fixed recording crops | 60 | **64** |
| Complete EXP + percentage, same crops | 50 | **54** |
| Complete with unchanged Tesseract level helper | 35 | **39** |
| Complete with unchanged pixel level recognizer | 31 | **32** |
| Percentage, previous automatic regions | 55 | **59** |
| Complete EXP + percentage, automatic regions | 46 | **50** |
| CharA percentage and complete EXP, 17 frames | 15 | **15** |

No old successes were lost. The four fixed-crop recoveries are 142.5/142.75 s
(`0 / 0.00%`), 145 s (`4 / 7.02%`) and 1770 s (`1 / 0.06%`). Their percent
symbols differ by four or five pixels. **All four recoveries infer `%`; none
requires inferred `]`.** CharA gains none and retains its prior 15 readings.

Of 53 still-unavailable recording percentages, **47 cannot verify the numeric
prefix/decimal/segmentation**, five lack usable bracket/field boundaries, and
one has no HUD. The first category is a post-scoring diagnostic: at existing
attempt boundaries, remove only the last white run and test the remaining numeric
prefix with the unchanged matcher. No expected values choose the split, and no
diagnostic output becomes a recognition. Causes may overlap; these counts do not
claim that every other suffix is readable. In particular, 599 s and 1061.75 s
remain unavailable rather than exposing the known incorrect Tesseract levels.

Mean EXP processing increases from 20.28 to **51.48 ms** on the recording, p95
70.90 ms, sampled CPU 5.578 s across 117 attempts. Peak RSS is **32.12 MiB**.
CharA averages 25.16 ms, peak 30.40 MiB. Acquisition, localization, level OCR,
image loading and bank setup are excluded. No Linux/live performance was tested.

```powershell
.\.venv\Scripts\python tools/exp_digits.py private/levelup-evaluation/evaluation-crops/recording-crops/142500/exp-crop.png --bank private/exp-digits/bank.json --grammar-suffix --localized
.\.venv\Scripts\python tools/evaluate_exp_digits.py private/levelup-evaluation/manifest.json --engine grammar --bank private/exp-digits/bank.json --levels private/exp-digits/levels-fixed.json --output private/grammar-suffix/repeat-recording.json
.\.venv\Scripts\python tools/evaluate_exp_digits.py private/exp-digits/streamer_a-manifest.json --engine grammar --bank private/exp-digits/bank.json --levels private/exp-digits/levels-streamer_a.json --output private/grammar-suffix/repeat-streamer_a.json
# Compare using --engine valleys; use the same inputs and a separate output file.
```

Private evidence under `private/grammar-suffix/` includes `freeze.json`,
`recording.json`, `recording-adaptive.json`, `streamer_a.json` and
`remaining-failures.json`. Frozen labels, development bank and original profiles
are unchanged. This remains a correlated same-recording comparison.

Validation: **470 full-suite tests passed, zero skipped**, including 43 new
suffix tests (40 synthetic and three private regressions). These cover degraded
but plausible punctuation, missing symbols, arbitrary blobs, malformed decimals,
unknown digits, and all ten digits substituted for `%` or for a white/green `]`.
Default strict recognition and production source remain unchanged.

The improvement is small: four extra complete pairs and no transfer gain on
CharA. Keep the optional experiment; proceed with the proposed small grayscale
classifier experiment to address numerical glyph variation, retaining suffix
evidence and strict unknown rejection. Do not keep relaxing punctuation bounds.

# Temporal RapidOCR feasibility experiment

Later [label reconciliation](ocr-label-audit.md) preserves these frozen counts but
separates the 1146s annotation correction and new user review at 1141s. The claimed
8→9 errors at 1141/1142/3359s are not independently established; see that audit.

Temporal agreement helps identify stable model outputs and retry opportunities;
it does **not** establish numerical correctness. The most consequential result is
a repeated, high-confidence apparent digit error that survives both crop variants.
Independent image-based numeric verification should take priority over a voting rule.
This is offline diagnosis only: no production code or acceptance policy changed.

Four windows were fixed before inference, using existing context: original
137–147 s (known level 2→3 boundary); Stream 2 2983–2993 s (small main HUD near
the earlier contamination case); Stream 3 1140–1150 s (windowed HUD) and
3349–3359 s (large HUD with known suffix difficulty). Eleven timestamp-seeked
frames per window give **44 frames at 1 Hz**, spanning ten seconds each.
No windows were replaced after seeing outputs. The unchanged locator ran afresh
on every frame, followed by the unchanged experimental Tesseract level reader.
RapidOCR 3.10.0 / ONNX Runtime 1.31.0 used the existing PP-OCRv6 small recognition
model, one CPU thread, direct line mode and fixed 2× bicubic input, separately at
zero and two native pixels of padding. Neither variant selects the other's result.

Each original-image visual row was inspected and transcribed before inference.
**All 44 new labels are Codex-provisional; zero are human-verified.** Existing
labels were neither changed nor propagated to adjacent frames. Counts below are
agreement with those transcriptions, not independently established accuracy.
Manual review boxes never enter localization or become fallback crops.

| Window (11 frames each) | Unique automatic regions | 0 px: matching / mismatching / unavailable pairs | 2 px: matching / mismatching / unavailable pairs |
|---|---:|---:|---:|
| Original transition | 11 | 11 / 0 / 0 | 10 / 0 / 1 |
| Stream 2 small | 8 | 8 / 0 / 3 | 8 / 0 / 3 |
| Stream 3 windowed | 9 | 3 / 2 / 6 | 6 / 3 / 2 |
| Stream 3 large | 11 | 0 / 0 / 11 | 7 / 1 / 3 |
| Total descriptive counts | **39** | **22 / 2 / 20** | **31 / 4 / 9** |

“Complete” requires the existing parser's bracketed syntax and both numbers;
none of these neural candidates is production-trusted. At 2 px, 35 candidates
are complete, four raw lines are malformed and five frames lack a region.
At 0 px, 24 are complete, 15 malformed and five lack a region. All 39 unique
regions point at the intended main HUD by the existing target check and visual
review; no secondary selection occurred in these eleven Stream 2 frames.
That does not establish multi-HUD disambiguation generally.
The level reader returns 37 values agreeing with provisional levels and seven
unavailable (including the five missing regions). Complete triples number
33 at 2 px (29 provisional matches / four mismatches), versus 22 at 0 px
(20 / two). Level availability is not evidence that EXP digits are correct.

Across 40 within-window adjacent edges, 2 px produces ten equal numerical pairs,
14 different pairs and 16 edges with an unavailable endpoint. Their breakdown:

| Window | Equal pairs | Different pairs | Unavailable edge |
|---|---:|---:|---:|
| Original | 6 | 2 | 2 |
| Stream 2 | 2 | 2 | 6 |
| Stream 3 windowed | 2 | 5 | 3 |
| Stream 3 large | 0 | 5 | 5 |

Differences agree with the direction of visually observed progression, but some
numbers are suspect. Monotonicity alone would miss them. No rate limit, gain
calculation, interpolation or transition bridge was applied.

- **1141 and 1142 s, Stream 3:** both variants say `73,991[25.15%]`;
  visual transcription is `73,981[25.15%]`. Two-pixel confidence is .99085
  and .99169. Crop bytes differ, yet the same apparent 8→9 substitution persists.
  This is one correlated error episode, not two independent error events.
- **1146 s:** both variants' numeric tokens say 74,059, versus visually
  transcribed 74,069. Padding repairs the suffix, producing a wrong complete
  candidate at confidence .98526. The preceding 1145 s has no automatic region.
- **3359 s:** both variants' tokens say 115,295, versus visually transcribed
  115,285. Only 2 px has complete punctuation, confidence .94654. Its increasing
  value looks plausible after 115,252; temporal ordering cannot reject it.
- **143→144 s:** level increases to 3, but 2 px first reads malformed
  `010.00%]`, then complete `0[0.00%]`. Zero padding reads both correctly.
  Later EXP becomes 4. This is evidence of reacquisition, not cross-level gain
  accounting or sufficient validation of automatic level-up handling.
- **3352–3353 s:** unchanged visual `115,142[39.14%]` remains malformed
  `115,142[39.14%1` in both variants. At 3354 s a different value is readable;
  the missing value cannot be reconstructed from it.

At 2 px, all nine unavailable frames have a complete immediate neighbor in this
selected sample. Eight have a later complete candidate within two seconds;
the ninth is at a window endpoint. Two of those later candidates are suspected
numeric errors. Only the 143→144 s case and Stream 2's 2987→2988 and 2989→2990 s
cases visibly reacquire the *same* numerical state. At 2991→2992 s and elsewhere
the value changes. No unavailable frame is filled from either neighbor.

Zero-versus-two-pixel comparisons yield **23 complete agreements, zero complete
contradictions, 12 padded-only, one zero-only and eight jointly unavailable**.
Two of the complete agreements are the suspected 73,991 error episode.
Thus this comparison found no numerical contradiction to reject in these windows,
despite apparent errors. Raw malformed tokens remain visible; they are not suffix
rescues. Twelve gains include ten provisional matches and two mismatches; the
one loss is the original transition frame at 143 s.

The 44 frames represent only 27 provisionally distinct visual numerical states;
35 distinct crop byte arrays occur among the 39 available crops per variant.
Long stable stretches are episodes, not independent validation samples. Equal
digits can persist because of identical rasterization, compression, a cached or
frozen video, repeated clipping, or sustained selection of the wrong HUD.
Different preprocessing of the same pixels is also correlated evidence.
Existing saved synthetic negatives reinforce this: a fragmented digit repeatedly
becomes complete wrong `74,050[25.17%]` at 2/4 px, while a clipped leading numeral
becomes `4,059[25.17%]` at 0/4 px. The real Stream 2 4-px contamination case
`345`→`2345` could likewise persist while adjacent text remains unchanged.
Those examples were reused from the context experiment, not regenerated here.
Percentage quantization and unverified rounding semantics also prevent arithmetic
consistency from independently verifying every small substitution.

Workstation measurements, one pass, excluding extraction/localization from neural
inference: 2-px inference mean/median/p95 **28.72 / 22.38 / 56.71 ms** over 39 crops;
0 px **39.26 / 26.42 / 68.25 ms**. Whole neural loops, including crop loading,
use 2.31 / 2.91 CPU seconds respectively; peak process RSS 160.7 / 158.7 MiB.
Two-pixel import, constructor and cold first inference cost .770 / .008 / .103 s.
Timestamp frame extraction takes 23.21 s separately. Fresh localization plus
level OCR takes 90.68 s wall, 85.75 sampled process-tree CPU seconds and peaks
at 187.45 MiB RSS. Locator mean/median/p95 is 1.639 / 1.000 / 3.127 s per
frame; level OCR mean .410 s per available region. Process-tree CPU sampling can
miss short subprocesses. This unoptimized fresh-localization pipeline does not
keep pace with 1 Hz on this workstation; these are not Linux VPS measurements.

Private review: `private/temporal-ocr/review-01.png`, `review-02.png` contain 16
selected examples, raw outputs/confidences and provisional labels; `review.csv`
contains every frame and crop hashes. `visual-*.png` are the original pre-inference
label sheets; `contexts.png` shows all four layouts. Human review should prioritize
1141/1142/1146/3359 s disagreements, 143/144 s transition and 3352/3353 s suffix
failures. Review all 44 rows before calling the aggregate counts verified accuracy.

Reproduce against the frozen private frames and fresh-locator results (use new
filenames; the analyzer refuses to replace evidence):

```powershell
foreach ($padding in 0,2) {
    .\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/temporal-ocr/manifest.json --plan private/temporal-ocr/plan.json --all --automatic-results private/temporal-ocr/localization.json --padding $padding --output "private/temporal-ocr/repeat-pad$padding.json"
}
.\.venv\Scripts\python tools/analyze_temporal_ocr.py --manifest private/temporal-ocr/manifest.json --localization private/temporal-ocr/localization.json --zero private/temporal-ocr/repeat-pad0.json --padded private/temporal-ocr/repeat-pad2.json --output private/temporal-ocr/repeat-timeline.json
Start-Process .\private\temporal-ocr\review-01.png
Start-Process .\private\temporal-ocr\review-02.png
.\.venv\Scripts\python -m pytest tests/test_temporal_ocr.py tests/test_rapidocr_benchmark.py -q --basetemp private/temporal-ocr/pytest-targeted-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/temporal-ocr/pytest-full-repeat
```

Private `prepare.py`, `label_visuals.py`, `localize.py` and `review.py` preserve
the extraction/annotation/localization/review procedure; the first three refuse
to overwrite frozen sampling or results. No new dependencies, training, threshold
changes, production integration, commits or pushes. Prior 106 snapshotted evidence
files, model hashes and new pre-inference labels remain unchanged. Public additions
are just the analyzer, its synthetic tests and this report.

Validation: **54 targeted tests passed; full suite 596 passed, zero skipped**
(80.69 s with local loopback access). The 13 new synthetic tests cover missing
frames, malformed punctuation, timestamp/window boundaries, level changes and
unknown levels, evidence mismatches, correlated wrong-number agreement and crop
contradictions without a winner. No recognition algorithm was modified.

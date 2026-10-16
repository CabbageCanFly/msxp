# Adaptive HUD experiment

An isolated offline prototype, not a production capture/Store integration.
No production OCR, trust guard, accounting, schema, statistics or overlay changed.
No dependencies were installed, footage collected, commits made or pushes run.

## What was implemented

`tools/adaptive_hud.py` takes a full screenshot and a private profile bank;
**it takes no screen regions or character/EXP answers**.

1. Sparse Tesseract searches the entire frame at 2×, retrying at 3× when no
   complete HUD is found. Working image area is bounded at each magnification;
   inputs larger than 4096×2160 are rejected. Whole-frame search accommodates a
   game window above the bottom of the stream rather than assuming full-screen play.
2. Bind HP, MP, EXP and LV labels using their order, row alignment and relative
   distances. Prefix parsing handles labels merged with numbers. All plausible
   layouts remain candidates; multiple layouts are rejected, including alternatives
   sharing an HP anchor. This covers one classic HUD layout family, not arbitrary UI.
3. Infer field positions and a scale proxy from HP→MP spacing. EXP position is
   derived from the stable pair rather than the changing width of its OCR token.
   Profile metadata records reference anchor spacing. This is relative layout
   calibration by the developer, not per-streamer coordinate configuration.
4. Try a bounded bank of up to four native glyph geometries with the existing
   `match_exp(scales=...)`. Scale estimates within 2.5% of a native profile snap
   to native size; others use its existing nearest-neighbour normalization.
   Keep all digit/punctuation tolerances, ambiguity margins, grammar and green
   bracket thresholds unchanged. Conflicting profiles veto acceptance. There is
   **no Tesseract EXP fallback** in this prototype.
5. For levels, locate orange tile bounds, suppress colored background using the
   minimum RGB channel, and try the existing threshold values. If corroboration
   is insufficient, also try existing luma preprocessing. Require at least two
   confident agreeing variants and reject conflicting confident variants.
6. Complete candidates pass `reading_errors` and the existing
   `guard_unverified_exp` using the matching profile. No transition validator or
   database is bypassed: neither is called by this read-only experiment.

Here, **guard-passing acceptance is experimental recognition**, not a persisted
trusted observation. The EXP guard does not independently verify the level.
Top-level confidence reports EXP glyph agreement, not a calibrated joint probability;
the separate level attempts remain in diagnostics.
Production still needs explicit character/session assignment and its existing
validated transitions. Automatic level-up handling remains unimplemented.

## Data separation and limitations of this benchmark

Original frozen labels/manifest, existing profiles and screenshots remain unchanged
and ignored. The 117 numeric labels are only used for scoring after recognition.
The prototype/profile bank was frozen before scoring; hashes are saved privately.
The sole later algorithm change preserves ambiguous anchor alternatives, motivated
by a synthetic regression. Its original code/results and final rerun are retained.

**This is now a same-recording calibration experiment, not independent held-out
accuracy.** Eleven development timestamps outside the 117 were visually labeled
and used with the existing trainer to build a private native-size v2 EXP profile:
8-pixel digit cells, height 11. Disjoint timestamps do not prevent repeated HUD
values or nearly identical glyph rasters. No benchmark frames or numeric labels
trained the profile, but scene/encoder/font dependence is strong. Initial legacy
detector diagnosis also inspected the previously evaluated frame at time zero.

The smaller 6×9 profile was regenerated from existing development annotations
plus manually inspected cells from original screenshot 1. Both original screenshots
were used as development examples; screenshot 1's successful reading is consequently
resubstitution, not held-out evidence. No game-derived profile ships in Git.

## Recording results

The 117-frame set has 116 visually readable HUDs and one black/missing HUD.
Field-extraction scoring checks containment of visible numeric/bracket ink inside
independently specified numeric-only boxes. Localization also checks both field
centers, separating correct HUD selection from complete extraction.

| Stage, on 116 readable frames | Exact/correct | Incorrect | Unavailable |
| --- | ---: | ---: | ---: |
| HUD location | 109 | 0 | 7 |
| Both fields completely extracted | 109 | 0 | 7 |
| Level consensus | 63 | **1** | 52 |
| Complete EXP digits | 37 | 0 | 79 |
| Complete percentage | 37 | 0 | 79 |
| Complete reading passing EXP guard | **25** | **0** | **91** |

The black HUD is correctly rejected. Across all 117: **25 exact guarded accepts,
zero incorrect full accepts, zero rejected complete candidates, 92 incomplete
readings**. The previous unchanged-profile/fixed-ROI baseline had zero guarded
accepts. These runs differ in profiles and level preprocessing as well as location;
do not attribute the improvement to normalization alone.

The important remaining failures:

- Level 8 at **599 seconds** is confidently read as 3 by two neutral variants.
  EXP rejection prevents a full accept in this frame; this is incidental protection,
  not proof that the new level method is safe. No automatic level-up inference
  should depend on this consensus rule.
- Native-profile EXP matching on fixed crops yields **41/116 exact matches**,
  zero incorrect. Automatic extraction loses four of those to locator failures.
  All 37 automatic matches use the new native profile; normalization to the smaller
  profile yields **zero** recording EXP matches.
- A post-freeze, fixed-cell comparison finds excessive digit distance on 73
  readable frames, other punctuation distance on 18 and bracket distance on 7
  (overlapping categories). These are diagnostic comparisons at manually established
  cell positions, not a threshold search or complete isolation of encoding effects.
  They indicate that native geometry alone does not solve raster variation.

## Other layouts and scales

Twelve synthetic/development cases were tested after freezing. Of nine positive
cases, seven HUDs are located with complete fields; three produce correct full
accepts. This is a challenge of layout/raster changes to development imagery,
not a new independent dataset.

- Original screenshot 1: 60 / 71,441 / 5.90%, accepted using its development profile.
- Original screenshot 2: HUD and both fields found; recognition rejected.
- Recording development frame and its HUD relocated into the upper half of the
  stream: both read correctly. The relocated original HUD is found but rejected.
- Half-size and 0.75× embedded game images: HUD/fields found, EXP rejected.
- 1.25× rendering and a native game inside a larger 2560×1600 stream: no HUD found.
  Global sparse OCR remains sensitive to context and resizing.
- Duplicate panels: two candidates, ambiguous. Blank image and game HUD hidden
  while screenshot 1's third-party tracker remains: no HUD, no acceptance.

No challenge produced an incorrect full accept. This small result does not establish
a production false-accept bound or cover cropped labels, other languages, different
HUD layout families, anisotropic scaling, three-digit levels or very long EXP values.
Localization establishes neither character identity nor source freshness. A missed
second HUD could also escape the multiple-candidate check.

## Measured resource costs

Windows 11, Python 3.14.7, Pillow 12.3.0, Tesseract 5.4.0. CPU/RSS are sampled
across Python and its OCR children every 10 ms, with one OCR thread requested.
FFmpeg extraction is excluded from processing/resource measurements.

Final full run after the ambiguity safety regression; all recognition decisions,
raw evidence and regions match the initial run:

| Measurement | Result |
| --- | ---: |
| Mean localization | 1.348 s/frame |
| Mean field recognition, including locator failures | 0.393 s/frame |
| Combined mean / p95 | 1.742 / 3.067 s/frame |
| Sampled CPU time | 246.969 s / 117 attempts |
| Peak sampled process-tree RSS | 179.40 MiB |
| Fixed-crop native EXP-only mean / p95 | 3.18 / 4.58 ms |
| Two private profile files | 5,852 bytes total |

Global label OCR dominates cost; a numeric neural model would not remove it.
For five channels, the measured OCR CPU alone projects roughly 0.35 core at 30 s,
0.70 at 15 s and 1.06 at 10 s, before acquisition/other work. These are arithmetic
estimates from Windows, not Linux VPS measurements. Serial recognition avoids
multiplying OCR peak memory; independent concurrent workers could crowd 1 GB.
No end-to-end live interval or capture performance is claimed here.

## Alternatives investigated

OpenCV's [`matchTemplate`](https://docs.opencv.org/4.13.0/df/dfb/group__imgproc__object.html)
compares fixed-size patches. A multi-scale pyramid of label anchors could supply
cheaper proposals and more stable scale registration, followed by all-label/layout
verification. It would require permitted anchor templates and negative tests;
template similarity must never authorize numeric EXP. OpenCV/NumPy are absent
and were not installed, so their speed and memory are **unmeasured** in this task.

The simpler measured alternative reuses Pillow/Tesseract. Tesseract's own
[input-quality guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)
describes rescaling, segmentation and border sensitivity. Results here show why
native geometry profiles currently outperform blind whole-line normalization,
while still failing much compressed text. Per-character normalization, registration
over subpixel phase and a calibrated pixel verifier for level digits remain untested.

A small numeric CNN/CTC model may eventually help font/compression variation,
but needs independently labeled data, unknown-glyph rejection and confidence
calibration. [ONNX quantization](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)
is a possible inference optimization, not a guaranteed memory/accuracy result.
No additional neural runtime/model was installed or benchmarked. Test cheaper segmentation
and profile coverage first; do not substitute an unchecked neural/Tesseract fallback.

## Run locally and next step

Normal README dependencies suffice for inspection; the benchmark additionally uses
existing optional capture dependencies (`psutil`) and FFmpeg. No streamer setup,
Twitch connection or OBS configuration is involved.

```powershell
.\.venv\Scripts\python tools/adaptive_hud.py samples/maplestory-classic-stream1.png --bank private/adaptive-ocr/bank.json
.\.venv\Scripts\python tools/evaluate_adaptive_hud.py private/adaptive-ocr/benchmark-manifest.json --bank private/adaptive-ocr/bank.json --output private/adaptive-ocr/benchmark-repeat.json
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-adaptive-full -rs
```

Profiles were generated with existing `tools/train_glyph_profile.py`; private
`native-training.json` and `source1-training.json` record manual development cells.
The bank stores paths relative to its JSON and reference HP→MP spacing. A future
operator-maintained bank could serve supported geometries without streamer
calibration. A public checkout currently has no cleared real bank; unknown fonts
must remain unreadable. Do not train trusted glyphs automatically from OCR guesses.

Private evidence under `private/adaptive-ocr/`: `freeze*.json`, `benchmark*.json`,
`oracle-exp-diagnostic.json`, `glyph-failure-diagnostic.json`, `robustness.json`,
`benchmark-automatic-fields.png`, development annotation sheets and synthetic
`challenge-*.png`. Everything game-derived stays ignored.

Validation: **28 public, synthetic prototype/evaluator tests passed**. The final
full suite passed **361 tests, zero skipped**, including the existing private OCR
fixtures and localhost transport checks. Both prototype and evaluator CLI commands
were exercised. Original frozen-label/profile hashes and the final prototype/bank
hashes were verified; no production source or existing test was changed.

**Recommendation:** keep this offline. Next test anchor-template localization on
the declared development layout challenges, separately develop an independently
verified level-digit matcher and broader numeric glyph coverage, then evaluate
on another recording/stream untouched by calibration. Cached anchor verification
could reduce full-frame OCR cost, but must reacquire on layout changes and never
turn uncertain locations or candidates into trusted state. Defer production
integration and automatic level-ups until recognition is independently dependable.

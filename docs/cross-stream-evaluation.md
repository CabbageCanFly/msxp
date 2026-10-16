# Untuned cross-stream evaluation: recordings 2 and 3

**All new numeric labels are provisional Codex visual transcriptions, not
human-verified ground truth.** Counts below describe agreement with those labels,
not independently verified accuracy. No new imagery calibrated a recognizer.
Neither recording produced an additional complete pair from grammar assistance or
the grayscale hybrid beyond strict valleys.

## Inputs and sampling

FFmpeg input metadata (FFprobe is not on PATH):

| Recording | Duration | Video | Video bitrate | Sampling |
|---|---|---|---|---|
| Stream 2 | 1:44:20.02 | 1920 × 1080, H.264 High, progressive yuv420p, 60 fps | ~5,003 kb/s | 45 frames, 0–6259.020 s, ~142.250 s apart |
| Stream 3 | 1:00:00.03 | Same resolution/codec/pixel format/fps | ~8,003 kb/s | 45 frames, 0–3599.030 s, ~81.796 s apart |

Only these timestamps were sought with existing `frame_at` (`ffmpeg -ss` before
input); no exhaustive decode or new Twitch capture. Screenshots 5/6 established
layout context only. Actual video labels differ: Stream 2 starts at level 1,
13 EXP / 86.67%; Stream 3 starts at level 40, 51,025 / 17.34%.

All 90 sampled main HUDs were visually readable enough for a provisional
transcription. Unknown fields can be marked `null`; none was filled from another
timestamp or an OCR prediction. Labels were saved in `annotations-before-ocr.json`
before evaluating any mode. Input hashes, labels, source profiles, development
images and classifiers were checked unchanged after evaluation.

Stream 3 has two raster geometries: frames **0 and 41–44** use a larger full-width
HUD; frames **1–40** use the reference windowed geometry. Diagnostic manual boxes
record this difference per frame. Automatic localization receives only the whole
frame, never those boxes or expected numbers.

## Results kept separate by recording

Each triple is **matches provisional label / mismatches / unavailable**, out of
45. Strict, grammar and hybrid produce identical counts on each new recording;
they were all run independently using their unchanged implementations.
No wrong-target localization, ambiguous multi-HUD result or numeric/level mismatch
was observed against the provisional annotations. This is not a guaranteed error rate.

| Stream / crop source | Main HUD found | EXP | Percentage | Complete pair | + Tesseract level | + pixel level |
|---|---|---|---|---|---|---|
| 3 / automatic | 41; 4 missing | 0 / 0 / 45 | 0 / 0 / 45 | 0 / 0 / 45 | 0 / 0 / 45 | 0 / 0 / 45 |
| 3 / manual diagnostic | Supplied by evaluator | 0 / 0 / 45 | 0 / 0 / 45 | 0 / 0 / 45 | 0 / 0 / 45 | 0 / 0 / 45 |
| 2 / automatic | 36; 9 missing | 5 / 0 / 40 | 5 / 0 / 40 | 5 / 0 / 40 | 4 / 0 / 41 | 0 / 0 / 45 |
| 2 / manual diagnostic | Supplied by evaluator | 34 / 0 / 11 | 34 / 0 / 11 | 34 / 0 / 11 | 23 / 0 / 22 | 0 / 0 / 45 |

Level recognition alone:

| Stream | Tesseract manual | Tesseract automatic | Pixel manual | Pixel automatic |
|---|---|---|---|---|
| 3 | 45 / 0 / 0 | 41 / 0 / 4 | 0 / 0 / 45 | 0 / 0 / 45 |
| 2 | 32 / 0 / 13 | 25 / 0 / 20 | 0 / 0 / 45 | 0 / 0 / 45 |

These are experimental recognition candidates, not trusted/persisted observations.
No production guard, transition, database or session state was called or changed.
Partial fields were scored separately and never counted as complete observations.

## Stream 3: numerical segmentation and raster transfer

The intended main HUD is located in 37/40 reference-geometry samples and 4/5 larger
samples. All 41 located fields contain the visible-ink bounds from the evaluator's
numeric-only boxes. Missing detections occur at **654.369, 899.758, 1717.719 and
3517.234 s**. Tesseract's level agrees on every manual sample; level OCR does not
explain this recording's zero complete pairs.

- All **40 reference-geometry manual crops** reach bracket-verified attempts but
  reject numerical characters. Strict percentage segmentation has more column
  components than the six visible characters in `NN.NN%` in all forty. EXP has
  excess components in every candidate window on 31/40; nine have at least one
  window with the expected component count. Component counts diagnose fragmentation,
  not a complete character-by-character ground-truth assignment.
- At **81.796 s**, provisional `53,054 / 18.03%`, the binary crop breaks the 3
  into separate components, loses faint punctuation and fragments the percent
  symbol. The grayscale fallback rejects several candidates; the first true 5
  has supporting-source error ~0.173, exceeding the frozen native bound ~0.128.
  A true 4 is individually recovered, without producing a complete field.
- At **2453.884 s**, `101,170 / 34.39%`, numerical components fragment again.
  Individually digit-like pieces do not establish intact digits. Grammar rejects
  the full field; accepted fragments must not be described as safe numerical readings.
- All **five larger-geometry crops** fail before a bracket-verified text window
  exists. `no_verified_bracket_pair` also covers text-band incompatibility; it is
  not proof that only bracket shape is wrong. The classifier receives no numerical
  candidates in these cases.
- Pixel-level tiles measure **16×19 or 17×19** in the smaller geometry, versus
  profile examples 16×18 / 15×18. Some fall within the recognizer's geometry allowance
  but fail shape distances. Larger **21×24** tiles have no compatible family.

The hybrid provides **no demonstrated complete-field cross-stream improvement**.
This is both preprocessing/segmentation failure and appearance mismatch; adding
verified examples alone cannot restore decimal points or reassemble fragmented
characters that binary segmentation did not retain.

Private evidence: `stream3/segmentation-examples.png`, `hud-01.png` through
`hud-05.png`, and `results.json` under `private/cross-stream/`.

## Stream 2: correct target, fragile field alignment

The locator selects the intended main HUD whenever it returns one candidate:
36 main, nine missing, **zero secondary-feed selections**. Both numeric ink boxes
are contained on 28; EXP ink is partly excluded on eight. Containment is a useful
geometric check, but does not guarantee the surrounding context required for matching.

Of the 34 manually readable pairs, eight have no automatic localization. Another
**21 are lost solely when changing to the automatic crop despite selecting the
correct main HUD**. Only five remain. The saved crops demonstrate the alignment issue:

- **142.250 s:** level 2, `15 / 44.12%`, complete automatic Tesseract triple.
- **284.501 s:** level 2, `17 / 50.00%`, manual pair succeeds; automatic fails.
  The successful manual native window starts at global **y=797**; the automatic
  ROI starts at **y=798**. Its matching search cannot try the successful window,
  even though the evaluator's visible-ink bounds are contained. This is context/
  alignment sensitivity, not necessarily a missing white digit pixel.
- **3698.512 s:** level 8, `325 / 38.69%`, manual pair succeeds; automatic fails
  bracket-window verification and Tesseract level is also unavailable.
- The eleven manual pair failures all stop before any bracket-verified attempt;
  grammar and grayscale therefore have no numerical input to improve. Values
  include `8 / 14.04%`, `24 / 26.09%`, and `475 / 84.82%`. Do not attribute these
  unavailable outputs to a particular numerical digit without successful segmentation.
- Eleven of the 34 manual pairs lack a Tesseract level. Pixel-level tiles are
  **12×14 or 12×15**, unsupported by the existing larger profile. The original
  frame-44 manual level crop also lacks sufficient tile context: an evaluator-only
  expanded crop still reads 10 with Tesseract and is rejected by pixel geometry.
  This follow-up changes no aggregate count and is saved separately, preserving
  the untouched baseline and labels.

Evidence: `stream2/manual-vs-automatic.png`, `level10-corrected-padding.json/png`,
`context.png`, contact sheets and `results.json` under `private/cross-stream/`.

The secondary feed changes content, sometimes showing another MapleStory HUD and
sometimes other windows. These are not 45 tests containing two identical Classic
HUDs. Existing localization rejects multiple candidates, but returns at the first
search magnification that finds candidates; zero secondary selections here does
not prove all competing scales/layouts are detected or identity established.

## Sampled timeline and earlier benchmark

Stream 2's five automatic pairs occur at **142.250, 1280.254, 1707.005, 2845.009,
5263.267 s**. The last lacks level recognition, so only the first four are full
Tesseract observations. Stream 3 has none in any period. For Stream 2, quarter-of-
duration bins contain 12 / 11 / 11 / 11 samples:

| Crop/result | First quarter | Second | Third | Fourth |
|---|---|---|---|---|
| Manual pairs | 9 | 9 | 7 | 9 |
| Manual Tesseract triples | 9 | 6 | 5 | 3 |
| Automatic pairs | 2 | 2 | 0 | 1 |
| Automatic Tesseract triples | 2 | 2 | 0 | 0 |

Many samples repeat unchanged values: Stream 2's `17 / 50.00%` and `325 / 38.69%`,
and Stream 3's `103,393 / 35.14%`. Uniform timestamps still do not make these
independent recognition conditions. Stream 2's sample spacing itself **exceeds the
120 s accounting limit**. Neither recording is a continuous tracking or transition
benchmark; no gains, outage lengths or level-up reliability can be inferred from
unsampled intervals. Sampled Stream 2 levels span 1–10; every sampled Stream 3
level is provisionally 40.

For comparison only, the earlier 117-frame recording had fixed-crop pairs
**50 / 54 / 64** for strict / grammar / hybrid, Tesseract triples **35 / 39 / 46**,
and pixel triples **31 / 32 / 37**, with no known incorrect complete results.
It overlaps calibration; the new recordings do not. Do not pool these denominators
or call the provisional new agreements independently verified accuracy.

## Reproduction, review and checks

From the project root, reuse the already prepared private frames/annotations:

```powershell
.\.venv\Scripts\python tools/evaluate_cross_stream.py evaluate private/cross-stream/stream3/manifest.json --output private/cross-stream/stream3/repeat.json
.\.venv\Scripts\python tools/evaluate_cross_stream.py evaluate private/cross-stream/stream2/manifest.json --output private/cross-stream/stream2/repeat.json
Start-Process .\private\cross-stream\stream3\hud-01.png
Start-Process .\private\cross-stream\stream2\hud-01.png
.\.venv\Scripts\python -m pytest -q --basetemp private/cross-stream/pytest-full
```

`prepare --help` documents timestamp extraction/contact sheets; it refuses to
overwrite an existing manifest. Initial commands used `--count 45`, Stream 2 HUD
`838,788,1638,830` and Stream 3 HUD `640,1028,1767,1080`, followed by visual-only
per-frame geometry annotation before OCR. Canonical labels and evaluator boxes
are in each `manifest.json`; `annotations.csv` is an easy-to-review companion.
**CSV edits are not automatically imported.** Send corrections or update the JSON,
mark reviewed rows `human_verified: true`, and save a separately named rerun.
Keep `annotations-before-ocr.json` as the original provisional snapshot.

Evaluation reused existing frame seeking, locator, field-bound checks, both level
readers, all three EXP readers, scoring and resource monitor. No new model,
training, profile, threshold, dependency or production change. The evaluator and
13 synthetic tests are new; **515 full-suite tests passed, zero skips**. Videos,
screenshots, annotations and crops remain ignored; `git ls-files samples` lists
only `samples/README.md`. Nothing was committed or pushed.

Multi-mode evaluation took ~134 s / 153 s for Stream 3 / 2, sampled process-tree CPU
~125 / 147 s, peak RSS ~197 / 194 MiB. These concurrent workstation runs include
both manual/automatic branches and all modes, exclude extraction, and are not
single-worker/VPS throughput measurements.

**Next priority:** scale-aware field extraction and segmentation. First address
the demonstrated automatic-crop context loss on Stream 2, then investigate preserving
faint punctuation and intact characters on Stream 3. These are stronger immediate
targets than a bigger glyph bank or classifier search. Native pixel-level geometry
support is also needed, but level OCR is not the primary blocker on Stream 3.
Require human review of these annotations before claiming cross-stream correctness,
and retain a future untouched stream after any changes informed by this evaluation.

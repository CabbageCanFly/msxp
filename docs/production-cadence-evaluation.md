# Offline recognition availability at 15-second cadence

**Availability is promising; numerical trust remains the blocker.** This is a
fixed-schedule offline diagnostic, not a production acceptance or remote-capture
trial. No candidate enters the tracking engine. No cached-ROI gate is used.

## Frozen procedure and review

Before extraction or new inference, `private/production-cadence/plan.json` fixed
three inclusive 300-second windows, each with 21 timestamp seeks at 15 seconds:

| Window | Recording seconds | Context |
|---|---|---|
| Stream 2 | 2837–3137 | Main game plus secondary game feed; visible level 6→7 change |
| Stream 3 windowed | 991–1291 | Windowed HUD, including the previously disputed 1141s glyph |
| Stream 3 late | 3299–3599 | Windowed initially; large HUD by 3359s |

The last window ends before the recording's 3600.03s endpoint. Frames are neither
replaced nor added following OCR. Source extraction uses existing FFmpeg
timestamp seeking, not a full-recording decode. The layout change is visibly
between sampled 3344s and 3359s frames; its exact time is not established.

Seven indices per window, **0, 3, 7, 10, 13, 17, 20**, were visually transcribed
from original RGB HUD context and nearest-neighbor enlargements before this run's
inference. The 21 transcriptions are **Codex-provisional, zero human-verified**.
The other 42 frames have null numerical reference fields. The known 1141s dispute
was already familiar from prior work: this is not blinded or independent-stream
validation. Agreement with provisional labels is not authenticated accuracy.

`manifest.json` and `labels-before-inference.sha256` freeze those transcriptions.
Manual HUD bounds score target selection only; manual field boxes produce review
images only. Neither supplies a locator fallback or recognition input.

Every frame receives unchanged `adaptive_hud.locate`; only a unique candidate
receives unchanged `level_reading`. RapidOCR **3.10.0 / ONNX Runtime 1.31.0**, CPU,
existing PP-OCRv6 small line model, one inference thread, reads the current original
frame's automatic EXP region with **+2 native pixels**, then fixed **2× bicubic**
enlargement. Missing/ambiguous regions abstain. Raw text/scores precede parsing in
JSONL. No suffix rescue, number reconstruction, adjacent-value reuse or voting.

## Per-window availability

“Complete” means both numbers and the existing parser's complete bracketed syntax;
it does **not** mean numerically correct, calibrated, or production-trusted.

| Window, 21 frames each | Main HUD found | Missing | Ambiguous / wrong target | Complete pairs | Malformed | Level available | Complete triples |
|---|---:|---:|---:|---:|---:|---:|---:|
| Stream 2 | 17 | 4 | 0 / 0 | 17 | 0 | 11 | 11 |
| Stream 3 windowed | 20 | 1 | 0 / 0 | 20 | 0 | 20 | 20 |
| Stream 3 late | 20 | 1 | 0 / 0 | 18 | 2 | 20 | 18 |

There are 55 complete pairs, 51 available levels and 49 complete triples among
63 scheduled attempts. Six missing regions and two malformed strings explain
the eight pair failures; there are no empty model outputs from available crops.
All 57 unique regions pass the existing evaluator's **both-field-center** main-HUD
check against visually identified bounds. No secondary selection was observed.
That geometric diagnostic is not a validated general competing-HUD or identity gate.

Only the seven pre-reviewed frames per window receive provisional comparisons:

| Window | Pair agreement / disagreement / unavailable | Level agreement / disagreement / unavailable | Triple agreement / disagreement / unavailable |
|---|---|---|---|
| Stream 2 | 6 / 0 / 1 | 5 / 0 / 2 | 5 / 0 / 2 |
| Stream 3 windowed | 5 / 1 / 1 | 6 / 0 / 1 | 5 / 1 / 1 |
| Stream 3 late | 6 / 0 / 1 | 7 / 0 / 0 | 6 / 0 / 1 |

The single disagreement is raw `73,991[25.15%]` versus provisional `73,981` at
1141s. The disputed 8/9 remains unresolved rather than newly authenticated as an
OCR error. No incorrect accepted level was found in this reference subset; most
frames are unscored. The remaining 42 frames must not be called correct because
they produce plausible text.

## Timeline and interruptions

Private `per-frame.csv` reports **all 63** timestamps, layout, target category,
raw text/score, parsed candidate, level, review status, individual stage timings
and image hashes. `summary.json` retains exact success/failure runs and gaps.
Runs below describe sampled availability, not continuous visibility or correctness.

| Window | Consecutive pair-available sample runs | Largest pair endpoint gap | Largest triple endpoint gap |
|---|---|---:|---:|
| Stream 2 | 2837–2852; 2882; 2912–2942; 2972; 3002–3137 | 30s | 90s |
| Stream 3 windowed | 991–1021; 1051–1291 | 30s | 30s |
| Stream 3 late | 3299; 3329–3374; 3419–3599 | 45s | 45s |

- **Stream 2:** locator misses at 2867, 2897, 2957 and 2987s. Each is bracketed
  by complete pairs 30s apart. Level additionally abstains at 2852 and
  **3017, 3032, 3047, 3062, 3077s**. The latter five failed sample instants span
  60s; complete triples at 3002 and 3092s are **90s apart**. Triple-success runs
  are 2837; 2882; 2912–2942; 2972; 3002; 3092–3137s. The last gap crosses a
  visible level change; the 135s pair-success run is not one same-level interval.
- **Stream 3 windowed:** locator misses only 1036s, between complete triples
  at 1021 and 1051s. Seventeen consecutive candidates span 240s after recovery,
  including the suspected 1141s numerical error. Thus a long run is not proof of
  trustworthy continuity.
- **Stream 3 late:** locator misses 3314s. At 3389 and 3404s raw strings end
  `%1`, leaving a 45s gap between complete endpoints at 3374 and 3419s. No repair
  is applied. The final thirteen consecutive triples span 180s. Both layout-change
  sample endpoints, 3344 and 3359s, are freshly located without cached recovery.

An isolated missing sample has zero span between failed sample instants, but a
30s gap between its surrounding successful endpoints. Two failed samples span
15s and leave a 45s endpoint gap. These definitions avoid presenting sample counts
as measured interruption duration. Unsampled instants remain unknown.

### Separate post-inference diagnostics

`post-inference-review.json` and `post-review-01/02.png` record additional source
inspection without changing the pre-run annotations or scoring denominator:

- All six missed frames still visibly contain their main HUD. Failure is return
  of no complete anchor layout, rather than evidence that EXP vanished. The
  exact failed anchor is unavailable from the existing locator's return value.
- At 2852 and 3017s the visible level is provisionally 6, but only one sufficiently
  confident OCR attempt agrees. At 3032s the level reader sees **7 (.90) versus
  2 (.53)** and abstains; at 3077s it lacks confident consensus. These are useful
  conservative rejections, not permission to relax its rule.
- At **3359s**, raw `115,295[39.19%]` repeats the prior suspected 8→9 substitution
  against visual-review `115,285`. It remains provisional and outside the scheduled
  pre-reviewed subset. It is not counted as a second established accuracy error.
- Adjacent complete, same-level candidates show **no numerical decreases or
  unchanged-EXP/changed-percentage contradictions**. This does not exonerate 1141
  or 3359s: both suspected mistakes remain plausible and monotonic.
- There are no identical full RGB frames within a window. Two EXP crops, 3032
  and 3062s, are byte-identical (`75[13.39%]`); full frames and gameplay context
  differ. Stable EXP is plausible, but repeated pixels cannot authenticate video
  freshness. Stream 2 also has repeated numerical episodes at 334 and 75 EXP;
  those are correlated evidence, not independent successful trials.

No selected tracking character or session is established by these video files.
Visible names, numerical agreement, a single locator result and level progression
cannot independently establish character identity. Confirmed stream offline state
and network/capture freshness are outside this offline experiment.

## Costs

Windows workstation, one sequential pass; these are **not 1-vCPU Linux VPS or
remote Streamlink measurements**. Latencies below are mean / median / p95 in ms;
level and neural timings include only frames that reach those stages.

| Window | Local extraction + PNG write | Fresh localization | Tesseract level | RapidOCR inference |
|---|---|---|---|---|
| Stream 2 | 478 / 478 / 571 | 2918 / 3070 / 4247 | 466 / 521 / 577 | 22 / 21 / 30 |
| Stream 3 windowed | 557 / 567 / 625 | 926 / 870 / 955 | 529 / 529 / 581 | 33 / 22 / 54 |
| Stream 3 late | 551 / 561 / 615 | 1017 / 909 / 2065 | 349 / 274 / 540 | 57 / 56 / 63 |

- Extraction stage: **33.32s** summed seeks/encoding/writes. Including contact
  sheet generation, monitored wall **38.23s**, sampled process-tree CPU **54.14s**,
  peak sampled tree RSS **235.30 MiB**. FFmpeg uses multiple cores by default.
- Localization: **102.07s** summed calls; level OCR separately **25.49s**. Their
  combined process including PNG loading/writing takes **130.72s wall**, sampled
  tree CPU **121.11s**, peak sampled tree RSS **187.98 MiB**. Memory/CPU monitoring
  aggregates these two stages; it does not isolate per-stage Tesseract memory.
  Largest individual localization call: **4.33s**.
- Neural inference: **2.181s** across 57 crops, mean/median/p95 **38.27 / 30.48 /
  61.98ms**. Original-frame loading, cached-pixel validation and context cropping
  separately total **2.170s**. Whole measured inference-loop CPU **4.203s**;
  process peak RSS **159.41 MiB**. Model import **.747s**, constructor **.010s**,
  cold first call **.100s** are separate. Confidence is not calibrated correctness.

Sequential per-attempt stage sums average approximately **3.82 / 2.05 / 2.00s**
for these three windows, excluding neural startup and remote acquisition. This
fits 15s for one channel on this workstation. Full-frame localization dominates
processing. Five serial copies of the harder layout would consume roughly 19s
per sampling round even here; no five-channel/1-GB deployment claim is justified.
Sampled CPU may miss very short subprocess lifetimes. Peak measurements describe
separate processes/runs, not concurrent aggregate capacity.

## Tracker implications and decision

The existing [Store contract](tracking.md) requires calibrated matching pixel
EXP evidence, explicit character/session assignment, increasing timestamps and
validated transitions. **None of these neural observations qualifies.** The
actual trusted-ingestion availability demonstrated by this experiment is zero;
the counts above measure experimental candidate availability only.

No internal candidate endpoint gap exceeds 120s. That is only a timing comparison:
bridging also requires trusted same-character/session, same-level nondecreasing
endpoints and no hard continuity break. The 3002→3092s level 6→7 span must not be
bridged. The current engine preserves the prior trusted baseline and requires
explicit confirmation/session handling after level changes; high candidate
availability after 3092s does not automatically resume that session's accounting.
No unknown EXP gains, cross-level totals or interpolated observations are computed.
The earlier two-second cache experiment would expire before a 15-second retry;
its manually reviewed scene gate is neither used nor presumed available here.

**Single next priority: evaluate independent image-based numeric verification on
a small human-reviewed reference/evaluation set.** Resolve the disputed 8/9 labels
as part of that bounded validation. Numerical errors are the safety blocker even
where availability and timing look good; temporal monotonicity and punctuation
do not reject them. Level coverage and multi-HUD localization also need improvement,
but their present abstentions are visible rather than silently wrong values.
Do not broaden cached recovery, promote RapidOCR, or implement level-up accounting
on these availability counts.

## Reproduce and inspect

Private source frames, labels, sheets and scripts remain under
`private/production-cadence/`, ignored by Git. `prepare.py` freezes the plan before
extraction and refuses to overwrite it. `review.py` renders context; `freeze_labels.py`
records this particular AI review and is **not** a general labeling tool or verified
ground truth. The neural environment is the existing private environment; no new
dependency or model download is needed. From the repository root, saved-input
reruns can use new output names:

```powershell
.\.venv\Scripts\python tools/evaluate_cadence.py localize --manifest private/production-cadence/manifest.json --output private/production-cadence/localization-repeat.json
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/production-cadence/manifest.json --plan private/production-cadence/plan.json --all --automatic-results private/production-cadence/localization-repeat.json --padding 2 --output private/production-cadence/rapidocr-repeat.json
.\.venv\Scripts\python tools/evaluate_cadence.py analyze --manifest private/production-cadence/manifest.json --localization private/production-cadence/localization-repeat.json --neural private/production-cadence/rapidocr-repeat.json --output private/production-cadence/summary-repeat.json
Start-Process .\private\production-cadence\pre-review-stream2.png
Start-Process .\private\production-cadence\pre-review-stream3-windowed.png
Start-Process .\private\production-cadence\pre-review-stream3-late.png
Start-Process .\private\production-cadence\post-review-02.png
.\.venv\Scripts\python -m pytest tests/test_cadence_evaluation.py -q --basetemp private/production-cadence/pytest-targeted-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/production-cadence/pytest-full-repeat
```

Per-frame CSV: `private/production-cadence/per-frame.csv`. Full saved analysis:
`summary.json` and `report-summary.json`; measured resource records and raw neural
JSON/JSONL are alongside them. Review all 21 pre-labeled rows, especially ambiguous
8/9 glyphs, before describing these comparisons as human-verified accuracy.

Public changes are only this report, `tools/evaluate_cadence.py` and its focused
synthetic tests. Prior evidence receipts cover **716 files**, including existing
annotations, images, RapidOCR outputs and model weights;
all remain byte-identical, as does this run's frozen pre-inference manifest.
Calibration profiles were neither edited nor regenerated; they are not included
in that receipt set. No production changes, new footage, training, thresholds,
commits or pushes.

Validation: **13 focused tests passed; full suite 634 passed, zero skipped**
(82.49s, including local loopback server tests). Synthetic cases cover elapsed
gap boundaries, censoring, malformed candidates, unknown labels, wrong-target
exclusion, missing levels, contradictory transitions and incompatible saved inputs.
`git diff --check` passes. No environmental test limitation remains for this run.

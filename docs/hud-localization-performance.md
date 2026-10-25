# HUD localization performance

Follows [capture performance](capture-performance.md) and the VPS offline runs (4 vCPU,
15 channels, 30 s requested, cache off), where mean localization grew from 4.47 s at 4
workers to 5.84 s at 6 and 7.75 s at 8. The question: can `adaptive_hud.locate()` cost less
**without losing whole-frame visibility of every HUD**?

Outcome: an output-identical, opt-in prototype (`locate(..., batched=True)`) saves ≈5–6 %
CPU and ≈9–10 % wall per frame on the workstation. Every option that cuts Tesseract's
recognition work changes, or plausibly weakens, competing-HUD evidence. Nothing is enabled
by default, the HUD cache stays off, and no VPS measurement exists yet. The later CPU
pass below retains only a small, pixel-identical preprocessing improvement.

All figures are **workstation** measurements (i7-13700K, Windows 11, Tesseract 5.4.0 with
4 MB `eng.traineddata`, `OMP_THREAD_LIMIT=1`), single runs, not VPS numbers.

## Corpus

Read-only, decoded in memory; no frame or crop was written or copied.

- **56 recording frames**: `sample-stream.mp4` every 120 s, `sample-stream2.mp4` every
  300 s and `sample-stream3.mp4` every 180 s.
- **21 saved images**: 12 adaptive-OCR challenge frames (relocated, resized 0.5/0.75/1.25,
  two panels, hidden HUD, blank, embedded in a larger stream), 5 sample screenshots and the
  4 cached-HUD synthetic negatives (hidden, secondary HUD, shifted, stale).
- **12 adversarial composites** built in memory from recording frames: two game feeds side
  by side and stacked, a second game as picture-in-picture, a duplicated HUD strip, LV
  covered, EXP label covered, 1280×720 / 2560×1440 / 3840×2160, 2560×1080 pillarbox,
  4:3 letterbox and a cross-fade scene transition.

**Missing:** the CharC obscured-HUD frames (`private/obscured-hud/`) are no longer on
disk, and there are no live Twitch frames, no long 30–60 s sequences and no Linux run.

## Where the time goes

Instrumented copy of `locate()`, checked equal to `locate()` on all 77 frames:

| Per frame, mean (max) | 2× pass | 3× pass |
|---|---:|---:|
| Grayscale, bicubic resize, threshold | 0.058 s | 0.106 s |
| pytesseract temporary PNG write | 0.070 s | 0.140 s |
| Tesseract process wall | 0.820 s (1.51) | 1.199 s (2.63) |
| Tesseract process CPU | 0.800 s | 1.178 s |
| Words returned | 252 | 291 |
| `layouts()` | 0.002 s | 0.002 s |

- **Total:** `merge_layouts()` takes under 1 ms. The whole of `locate()` is 2.43 s mean
  (2.27 median, 4.62 max).
- **Tesseract dominates:** it is 83 % of wall time, and the 3× pass is 59 % of Tesseract's
  CPU. Tesseract waits on nothing, so its wall time is CPU time (0.98 s CPU per 1 s wall).
- **Python side:** preprocessing, PNG encode and TSV parse take ≈0.2–0.4 s CPU per frame
  (the two harnesses differ; Windows CPU timers have 16 ms resolution).
- **Fixed per-process cost:** 0.08 s wall and 0.06 s CPU on a 40×20 image.
- **Content drives the cost:** a blank 3840×2160 image takes 0.15 s and a blank 5760×3240
  image 0.26 s, against 0.8–1.2 s for a real frame. Cost tracks text-like content (game
  sprites, names, damage numbers), not pixel count alone.

**Contention** (6 processes pinned to 4 physical cores, 20 frames each, like 6 workers on
4 vCPU): baseline wall rises to 3.67 s mean (5.59 p95, 6.58 max). CPU per frame also rises,
from 2.17 to 2.59 s, so contention slows each frame as well as queuing them. The VPS's
4.5 → 7.8 s growth with workers is consistent with that.

## What each pass contributes

Replaying saved tokens through `layouts()`/`merge_layouts()` per scale:

- **2× alone** changes 17/77 results. It loses 15 single HUDs, loses both HUDs in
  `two_panels` (2 → 0), and turns the two-candidate `original1_hud_relocated` into a
  **false unique** (2 → 1).
- **3× alone** changes 31/77 results, 26 of them by box jitter of ≤4 px. The material
  changes:
  - loses 2 HUDs (`s1@1500`, `recording_development`);
  - loses the level crop on 2 frames (`s3@1305`, `s3@2925`);
  - also turns `original1_hud_relocated` into a **false unique**.

Neither scale covers the other. Dropping either pass is unsafe on measured evidence, not
just "not evaluated".

## Options considered

All variants ran on identical binary images. Each was compared with a control run of the
same harness, executed at the same time on its own pinned core. A second control run gave
byte-identical tokens on 77/77 frames, so Tesseract output is deterministic here.

| Option | Tokens identical (2× / 3×) | Located HUDs changed | CPU | Wall | Verdict |
|---|---|---|---:|---:|---|
| PNG `compress_level=1` | 77/77 / 77/77 | 0 | −0.8 % | −6.6 % | Safe, small |
| One Tesseract process, both images | 77/77 / 77/77 | 0 | −1.9 % | −8.0 % | Safe, small |
| **Both (prototype)** | 77/77 / 77/77, adversarial 12/12 | 0 | **−5.4 %** | **−10.4 %** | Safe, opt-in |
| `tessedit_do_invert=0` | 1/77 / 2/77 | 0 | −11.1 % | −15.3 % | **Rejected** |
| 1-bit PNG input | 68/77 / 68/77 | 4 (1 level crop lost) | −7.1 % | −12.3 % | Rejected |
| Drop 3× or 2× pass | n/a | 17 / 31 (see above) | ≈−55 % / −40 % | | Rejected |
| Region-first cache | prior work | blind to a new second HUD | | | Stays off |

**No-invert, re-examined at the evidence level.** `layouts()` reads only HP/MP/EXP/LV
label tokens, so the right equivalence test is label-token identity, not whole-token
identity. HUD decisions were unchanged on 89/89 frames. However:

- **Label tokens lost:** without inversion, label tokens differ in 25 of 154 scale passes,
  with 24 lost and 2 gained.
- **The lost labels sit off the main HUD:** they are HP/LV/EXP tokens outside the
  accepted game HUD, such as an `HP` at x≈406, y≈709 in seven Stream 2 frames and an `EXP`
  at x≈161, y≈1019 in three saved images. What those regions show was not visually
  confirmed.

Off-HUD labels are exactly the evidence a competing or partial second HUD depends on, so
the 11 % saving comes from reduced label recall. Rejected.

**Label-seeded 3×** (OCR the 3× pass only around 2× label tokens) is the one structural
idea the data does not rule out. Every 3× HUD (68/68) has at least one 2× label token
inside its `search_box`, and every 2× HUD (53/53) has a 3× one. It was **not prototyped**:

- **Crop OCR differs from full-frame OCR:** the earlier region search accepted only 53/61
  same-frame boxes, with ≤4 px jitter.
- **Seed-box size is unknown:** a single label token gives no anchor spacing, so its box
  size, and therefore the saving, is unknown.
- **One unseen label breaks it:** a HUD with no label recognized at 2× would become
  invisible at both scales.

## Prototype

- **`tools/adaptive_hud.py`:** `scan()` returns the per-scale tokens that `locate()` binds
  (a refactor; `locate()` output is unchanged). With `batched=True`, the 2× and 3× images
  are written with fast PNG compression (identical pixels) and read by **one** Tesseract
  process through a list file.
  - **Timeout:** one 20 s limit, the same per-frame bound as the two 10 s calls it replaces.
  - **Page check:** the result must contain every page. A missing page raises instead of
    silently hiding a HUD.
- **`src/exp_tracker/recognition.py`:** `_tokens(data, page)` is extracted from `_ocr`;
  `_ocr` itself is unchanged.
- **Default behaviour:** unchanged. `shadow_capture` and `CachedLocator` still call
  `locate()` with the default `batched=False`, and `multi_alpha.py` is untouched. The
  default path still builds, reads and releases one scale at a time. A test asserts that
  the 2× image is freed before the 3× image is built.
- **Memory:** peak Python-process memory above pre-call RSS, measured in fresh processes.
  Tesseract child memory was not measured.

  | | 1080p | 3840×2160 |
  |---|---:|---:|
  | Committed `locate()` | 36.8 MiB | 46.2 MiB |
  | New default | 36.0–36.4 MiB | 38.3 MiB |
  | Batched | 44.0 MiB | 46.0 MiB |

  The default is not higher, because the intermediate grayscale image is no longer held
  during OCR. Batching holds both binary images, ≈8 MiB more at 1080p. Nothing is retained
  after the call (≤0.8 MiB). Temporary directories are removed on success and on error.
- **`tools/benchmark_hud_locate.py`:** a standalone parity and timing tool. It runs
  baseline and batched OCR on the same frames, in alternating order, and exits 1 on any
  token difference. It reports wall time, own CPU and, on POSIX, Tesseract child CPU.
  `--output` never overwrites.

Results:

| | Baseline | Batched | Change |
|---|---:|---:|---:|
| Uncontended, 77 frames: mean wall | 2.347 s | 2.101 s | −10.4 % |
| Uncontended: CPU (own + Tesseract) | 2.165 s | 2.047 s | −5.4 % |
| 12 adversarial frames: CPU | 2.020 s | 1.895 s | −6.2 % |
| 6 processes on 4 cores, 120 frames: mean / p95 / max wall | 3.67 / 5.59 / 6.58 s | 3.34 / 4.59 / 5.04 s | −9 % / −18 % / −23 % |
| 6 processes on 4 cores: CPU | 2.587 s | 2.421 s | −6.4 % |
| Token identity | | 77/77, 12/12, 120/120 | |

Safety, against the requested report items:

- **Candidates and geometry:** no candidate-count, acceptance, rejection or geometry
  differences.
- **HUDs lost:** no previously accepted HUD became unavailable.
- **New acceptances:** no ambiguous scene became accepted, and no new unsafe acceptance
  occurred.
- **Why:** these follow from byte-identical tokens rather than from tolerance.

The two contention groups ran one after the other, so thermal or turbo drift could account
for part of the p95/max gain. Windows process start is slower than Linux `fork`/`exec`, so
the wall gain from batching is probably smaller on the VPS. The PNG-encode CPU saving
should carry over. **Untested on Linux.**

## Pre-existing limitation found (not caused or fixed here)

The baseline returns **one** HUD for three adversarial scenes that show two games:
side-by-side and stacked half-size feeds, and a picture-in-picture second game at 0.45
scale. A half-size HUD is not localized at either magnification (the existing
`recording_resized_0.5` challenge also finds none), so its presence never makes the scene
ambiguous. A small second game can therefore produce a false unique acceptance today.
This is a correctness gap in whole-frame detection, independent of performance. Any future
fast path should be validated against it rather than assumed to inherit safety from the
baseline.

## Recommendation

1. **Not ready to integrate by default.** The batched path is output-identical on every
   frame tested and fails closed on a missing page. Its gain is modest (≈6 % CPU), and it
   has not run on Linux.
2. **Next experiment, operator-run on the VPS from a separate checkout** (as in
   [capture performance](capture-performance.md)): `tools/benchmark_hud_locate.py` over
   the same offline recording, once alone and as 6 concurrent copies. Accept only zero
   mismatches. Wiring `batched=True` to a `multi_alpha` flag is a separate, reviewed
   change.
3. **Check the VPS Tesseract first.** `tesseract --version` should list AVX2/FMA, and
   `eng.traineddata` should match the workstation's 4 MB fast model (compare hashes).
   A missing SIMD path or the larger "best" model would explain the VPS being ≈1.9× slower
   per CPU-second more than anything here. It would also change tokens.
4. **The pytesseract `timeout=10` per pass** has 3.9× headroom over the workstation's
   uncontended 3× maximum (2.6 s). That headroom is unknown under VPS contention at 6–8
   workers, so record any localization timeouts in that benchmark.
5. **Larger savings need reduced recognition work.** Label-seeded 3× is the candidate.
   Evaluate it offline only, with seed-box sizing, adversarial multi-HUD frames and the
   small-second-game gap above, before any prototype.

```sh
# Private output; frames are decoded in memory. Exit 1 means a token mismatch.
PYTHONPATH=src:tools python tools/benchmark_hud_locate.py \
  $(for s in $(seq 60 120 1800); do printf 'samples/sample-stream.mp4@%s ' $s; done) \
  --output private/hud-bench/alone.json
```

## Validation

- **Focused:** `python -m pytest tests/test_adaptive_hud.py tests/test_capture_performance.py
  tests/test_hud_resilience.py tests/test_hud_dedup.py` gave **106 passed, 3 skipped**.
  The skips are private CharA fixtures. The new tests cover:
  - batched/separate plumbing parity (full frame and box);
  - missing, extra and malformed pages raising an error;
  - per-scale release on the default path;
  - real-Tesseract token identity on a generated two-HUD image;
  - the tool's mismatch exit and no-overwrite behaviour.
- **Full suite:** `python -m pytest` gave **2365 passed, 119 skipped**. 118 skips are
  private fixtures and 1 is a Windows symlink permission.
- **Parity with the committed code:** on all 89 frames (77 corpus + 12 adversarial), the
  committed `locate()` (`4ab2293`), the new default `scan()`/`locate()` and the batched
  path gave identical per-scale tokens and identical located HUDs. No `msxp-hud-*`
  temporary directories were left behind.
- **Harness:** the profiling and variant harness lives outside the repository. Its private
  token dumps were not committed.

## Second CPU pass: resident OCR and smaller search areas

This pass uses the existing saved images, without restoring the recordings: 43 frames
from the normal recorded-stream test selection and all 12 adaptive-HUD challenge images.
The Windows native Tesseract API matches the resident engine used in capture. Three
isolated workers compare baseline and candidate on each of the same 55 images; the
table sums process CPU seconds for both scales, including resize and threshold work.
These are offline workstation results, not VPS capture intervals.

| Second-pass experiment | Baseline CPU | Candidate CPU | Result |
| --- | ---: | ---: | --- |
| Full-width bands around first-pass labels | 166.75 s | 111.89 s (33% less) | Same HUD counts, but two crop positions changed and some labels disappeared |
| Four overlapping full-width strips covering the entire frame | 190.73 s | 203.47 s (7% more) | Three HUD results changed, including one lost HUD |

The label-seeded experiment keeps the complete 2x pass. Each HP/MP/EXP/LV token seeds a
band extending 12 token heights above it and 12 below its bottom; overlapping bands
merge. With no seeds, it falls back to the complete 3x pass. Crops come from the same
full-frame 3x binary image, so resizing pixels are identical. Cropping still changes
Tesseract's context: 41/55 frames had changed 3x label tokens; four had fewer labels.
One level crop moved by one pixel, and another frame's EXP crop moved by up to four.
No capture/accounting comparison was run for those altered crops. A second HUD whose
labels are entirely missed by 2x could also go unseen. This is promising research,
but it is not enabled in capture.

The full-coverage experiment divides the 3x image into four horizontal strips with
40 native pixels of overlap margin on each side of a boundary. It preserves image
coverage but still changes OCR context. It loses the embedded-game challenge HUD,
gains a HUD on another frame and changes level availability on a third. It is rejected.
Compare each candidate only with its own paired control; the two totals came from
separate runs. Raw outputs and disposable probes stay in ignored
`private/cpu-efficiency/`.

The production change is deliberately small: convert the frame/crop to grayscale
once, then reuse it for both enlargements. Both binary OCR input images remain
byte-for-byte identical, and each enlarged image is still released before the next.
On one 1080p image, 20 alternating pairs measured preprocessing at about 112 ms
before and 107 ms after. This saves about 5 ms per frame in that local measurement;
it is not a substantial reduction in total HUD OCR time. Tests compare exact input
pixels for RGB, RGBA and grayscale sources, including a cropped search.

Larger savings need a detector that can replace expensive full-frame recognition
while still finding competing HUDs. The measurements above do not justify making
label-seeded search the default.

## Visual HUD prototype

**Decision: retain as research only.** No production rollout is recommended yet.
Fallback adds work before the original detector, so a fallback-heavy workload can
cost more CPU and take longer. This prototype has no automatic backoff. The next
validation would be an isolated server comparison before any live enablement.

`msxp tracker --visual-hud` enables an experimental alternative on this branch.
It is off by default. Add `--check` to check the setup without starting capture.
The standalone `tools/shadow_capture.py` command accepts the same flag.

The first successful full-frame localization supplies a tiny image of the static
EXP label. A separate worker finds groups of three similarly spaced meter frames,
infers their scale, and checks the label with fuzzy image matching. It keeps at most
eight representative label images in memory, shared across streams; it stores no
readings or templates on disk. Different scales and minor compression changes can
use the same label shape. Unknown styles can be learned after a full-frame fallback.

The proposed regions form a mask over the current frame. The original two-scale
Tesseract detector still confirms the HUD, and EXP, level and character-name reads
use the original current pixels. No last-frame position or value is reused. The
existing freshness, identity, arithmetic and grammar policies remain in place.

Fallback uses the original full frame when the worker is unavailable, the label
style is unfamiliar, meter evidence is missing, the mask is too broad, the masked
OCR is incomplete/ambiguous, or EXP needs grammar recovery. A complete percentage-only
field does not require a numerical EXP pair. A separate whole-frame check looks
for matching EXP labels beside text rows outside the mask, including a second HUD
whose meters are covered. A detected competing label forces the full detector.

This reuses OpenCV and NumPy in the existing isolated OCR environment; it adds no
packages to the main environment. Startup checks those dependencies before database
changes. `--visual-hud` implies `--resident-neural` and cannot be combined with the
region cache or historical replay. Remove the flag to return to the current detector.

### Local results

The real resident worker was compared with the original detector on 225 saved
images. It kept all 171 correct strict EXP pairs from the labelled recordings,
introduced no new wrong pairs, and lost no previously available visual levels.
The one known tiny-font misread remains present in both paths. The fast path was
used on 101/225 images; the rest used full-frame fallback, including startup.
All 22 scaled, partly covered and JPEG-compressed competing-HUD trials kept an
existing multiple-HUD rejection. A generated partial-second-HUD regression is also
in the test suite; private images and learned templates are not committed.
The full suite passed: **3332 passed, 75 skipped, 1 known xfail**. Skips are 68
absent private crop cases, six Linux-only cases and one Windows symlink permission.

A paired CPU measurement used the standard 61-image selection, alternating
baseline/candidate order on three isolated workers during the 225-image replay.
It includes mask construction and full-frame retries, with the limited scope below.

| Replay and CPU scope | Original | Visual prototype | Reduction |
| --- | ---: | ---: | ---: |
| Calibration during the 225-image replay; parent/Tesseract + visual worker, neural child excluded | 144.06 s | 126.56 s | 12.1% |

**Withdrawn measurement:** an earlier warmed run reported 124.48 s to 93.41 s
(25%) as all recognition-process CPU. Its Windows accounting sampled the venv
launcher PIDs and omitted their actual OCR children, including the visual worker.
A direct process-tree check confirmed the omission. Do not use that percentage
as a capacity estimate. The 12.1% row above includes the visual worker's own
reported CPU but intentionally excludes neural inference. Neither is a VPS or
whole-service measurement. Accuracy comparisons above are unaffected.
The confirmation field read currently falls inside `localization_seconds`; use
total recognition time and process CPU rather than individual stage timings here.

This is a proposal heuristic, not proof that every HUD is visible. A second HUD with
an unfamiliar font or heavily damaged labels may escape its checks, and the full
detector already misses some small second HUDs. The saved fixtures do not establish
90–95% coverage of Twitch streams. Keep this opt-in until Linux and live behaviour
have been reviewed; local CPU measurements cannot predict the VPS capture interval.

## Further upstream leads

A broader GitHub/Reddit/upstream search found untried options inside Tesseract,
rather than another compression tweak. An offline feasibility probe used the six
varied screenshots, identical prepared 2x/3x inputs and the resident native API.
These are small, single-pass workstation comparisons, not a validated speedup.

| Route | Sum of process CPU | Observation |
| --- | ---: | --- |
| Current full recognition | 17.59 s | Control |
| Disable system/frequent dictionaries at initialization | 19.25 s | No clear saving; label evidence and HUD geometry matched these six images |
| Disable the LSTM ratings matrix / use greedy decoding | 18.75 s | Changed label evidence on all six; changed HUD geometry on two; reject |
| Layout analysis only, without recognizing text | 7.38 s | Layout boxes covered every baseline HUD-label centre in this small set |

The [upstream API](https://github.com/tesseract-ocr/tesseract/blob/main/src/api/baseapi.cpp)
explicitly separates `AnalyseLayout()` from `Recognize()`. Layout-only cost about
42% of full recognition here. It returns positions, not HP/MP/EXP/LV text or a
verified HUD. The completed prototype below follows this lead; the initial centre
coverage check alone did not establish accuracy or a pipeline speed gain.
The [dictionary/decoder parameters](https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc)
are real supported options; availability does not establish a useful speed gain.

A larger alternative is a small detector trained specifically to locate this game's
HUD, followed by the existing field OCR. [YOLO11's CPU/ONNX benchmarks](https://docs.ultralytics.com/models/yolo11/)
show that small object detectors can be practical without a server GPU; those
benchmark times are not predictions for this VPS. A HUD model would need labelled
examples, partial/secondary-HUD negatives, splits by source recording, and a
held-out recall/cost check. No model was trained or installed in this pass.

Two eye-catching alternatives do not justify a library switch from current evidence:
[RapidOCRLite's own AVX2 table](https://github.com/RapidAI/RapidOCRLite) reports faster
detection but slower recognition-only, which is our existing neural worker's mode.
[TurboOCR](https://github.com/aiptimizer/TurboOCR) currently ships its NVIDIA backend;
its advertised GPU document throughput does not apply to the CPU-only VPS.
No capture integration or deployment changes were made for this research.

## Layout-first prototype: offline only

The research implementation is [layout_first_hud.py](../tools/layout_first_hud.py),
with a reproducible [saved-image comparison tool](../tools/evaluate_layout_hud.py).
It is not enabled by `msxp tracker`, and adds no dependency, model or live flag.
The default HUD detector keeps the same scans; its existing token-to-HUD binding
was extracted into `locate_from_tokens()` so both paths share the same rules.

Both original 2x/3x binary pages get whole-frame native layout analysis. A loose
text-row geometry search proposes EXP word positions, including rows without LV.
Short original-pixel prefixes are read for EXP first; matching rows then supply
HP, MP and optional LV candidates. The existing binder confirms the HUD and supplies
the original-frame EXP/level crops. No prior frame, HUD position or numerical value
is reused. A field response is reused once only for the exact same current crops.

Incomplete/ambiguous candidates, a missing level region or EXP requiring grammar
recovery finish the original whole-frame read. Complete percentage-only text remains
eligible for the selective path. Two analyzed native pages are retained until that
decision, so fallback reuses segmentation instead of repeating it. Prefix reads and
field retries still add work. Word-crop or field-confirmation errors fall back too,
preserving the original path's ability to retain visual-level evidence. Native
recognition is explicitly called before TSV
after `AnalyseLayout()`; requesting TSV directly can assert in Tesseract 5.4.

### Complete replay results

Two paired 225-image runs alternated baseline/candidate order on three isolated
Windows workers. They include preprocessing, localization, actual field confirmation,
fallback/retries, visual and neural levels, and recursive OCR-child CPU. Windows
venv launcher children are included. Model initialization and the neural warmup
are outside the timers. Stream capture/FFmpeg, character identity/jobs, SQLite and
API publication are not measured. Each comparison uses its own paired control.

| Complete HUD + EXP/level OCR replay | Original CPU | Candidate CPU | Reduction |
| --- | ---: | ---: | ---: |
| Development prototype | 751.02 s | 544.31 s | 27.5% |
| Clean tracked implementation | 797.70 s | 578.00 s | 27.5% |

The clean implementation matched the development prototype's readings on all 225
images. It used selective recognition on **172/225**, with **53** full-frame fallbacks
(34 imperfect EXP fields, 17 incomplete/ambiguous HUDs, two page-budget/no-proposal
fallbacks). It kept all **171** previously correct strict EXP pairs and read **five
additional labelled frames** correctly. It introduced no new wrong full EXP pairs,
visual/neural levels or grammar-recovered percentages, and lost no previously
correct level or percentage reading. Existing baseline OCR errors remain.

All **22** scaled, partly covered and compressed competing-HUD cases kept the
baseline's multiple-HUD rejection. These are development/regression fixtures, not
a claim about population coverage. The original detector already misses some small
second HUDs; this study does not prove general multi-HUD recall.

### Costs and next step

Fallback can be slower: the 22-case competing-HUD replay used **66.80 s to 74.17 s**
CPU (about 11% more). The largest observed extra cost on an individual ordinary
fixture was 1.11 CPU seconds. Those observations are not worst-case bounds, and
there is no automatic backoff. A different stream mix could reduce or erase the gain.

The prototype uses **three exclusive native handles per offline worker**. Service
memory/queue effects, Ubuntu/Tesseract 5.5 output and live capture intervals are
unmeasured. Before production integration, run an isolated Linux replay, then keep
the native per-frame operation inside timeout-controlled worker processes. Routing
every word crop through a separate existing worker request would add unmeasured IPC
overhead. No native engine should be moved into the live coordinator process.

From an installed tracker Python environment, for one restored private sample:

```sh
python tools/evaluate_layout_hud.py samples/maplestory-classic-stream2.png --output private/layout-first/check-1.json --workers 1
```

The tool accepts saved images only, never opens a stream/database, writes a new
private result file and refuses overwrites. `--ocr-python` can reuse the existing
isolated environment. Native crashes are isolated to benchmark worker processes;
this offline tool is not the service's bounded worker protocol.

Validation: **3348 passed, 75 skipped, 1 known xfail**. The skips remain 68 absent
private-crop cases, six Linux-only cases and one Windows symlink permission. The
16 new tests cover native layout/full-read parity and reset, exact crop-response
reuse, stale-frame rejection, partial second-HUD proposals, retained-page fallback,
crop/field failures and private-output/no-overwrite checks.

### Fresh live-stream check, 2026-10-25

The 225-image results above used existing fixtures. A separate held-out batch now
adds **42 new frames from 14 live, authorized production-roster streamers**, three
rounds per streamer, captured at 09:14:41–09:15:56 UTC. All 42 captures succeeded
and have different file hashes: 33 at 1920×1080 and nine at 1280×720. These are
native stream frames, not Twitch thumbnails or recordings. The VPS roster was
read with SQLite read-only mode; all video capture and OCR ran locally. Production
was unchanged, and the prototype was not tuned against this batch.

Every frame's visible EXP/percentage and level was visually transcribed from the
original pixels, with enlarged context checked for difficult digits. Both methods
then used the same saved frames and original field crops:

| Result | Normal detector | Layout-first prototype |
| --- | ---: | ---: |
| Correct strict full EXP pairs | 25 | 26 |
| Correct strict percentage-only readings | 11 | 11 |
| Additional correct grammar proposals | 3 | 3 |
| Wrong raw full EXP pairs | 1 | 1, same frame |
| Correct neural levels | 39 | 41 |
| Wrong visual or neural levels | 0 | 0 |
| Mean local elapsed OCR time/frame | 1.465 s | 1.074 s |
| Total measured process-tree CPU | 60.766 s | 44.672 s |

No correct baseline EXP, percentage or level reading was lost. Grammar proposals
are diagnostic interpretations, not proof of accepted ingestion. The shared
wrong raw pair read `99,653 [9.16%]` as `99,653 [19.16%]`; the existing EXP-table
check marks it incompatible. Neither detector is error-free.

The faster path handled **36/42 frames (85.7%)**. Six fell back: four imperfect
EXP fields and two incomplete/ambiguous layouts. On those six frames, mean local
elapsed time increased from 1.095 s to 1.281 s; the largest observed extra time
over the whole batch was 0.273 s. Across the batch, CPU fell 26.5% and elapsed OCR
time fell 26.7%. Capture/network/startup time is excluded, as in the fixture replay.

Private frames, capture timestamps/hashes, human labels, review sheets and paired
results remain under `private/cpu-efficiency/fresh-live-20261025/`, excluded from
Git. The private evaluation runner only retained extra localization/crop metadata;
the recognition algorithm remains the committed prototype.

This adds independent frames, not 42 independent HUD designs: each streamer
contributes three nearby frames. All happened to show gameplay HUDs. This batch
does not establish behavior during ads, absent HUDs or unusual competing HUDs, nor
Linux/VPS performance or end-to-end website acceptance. The earlier competing-HUD
stress tests and the production-integration limitations above still apply.

### Second fresh batch: four frames per streamer

Repeated with **56 additional images from the same 14 currently live streamers**,
four rounds each at 09:23:48–09:25:42 UTC on 2026-10-25. All captures succeeded;
all hashes differ within this batch and from the earlier 42 images. Resolution:
44 at 1080p and 12 at 720p. Recognition code was unchanged. Human labels came from
the original frame context before examining the paired OCR outputs; level crops
and differing detector crops were then also reviewed.

Both methods produced **35 correct strict full pairs, 14 correct strict
percentage-only readings, four additional correct grammar proposals, and no
observed wrong readings**. They both rejected a black transition with no game HUD,
and returned no reading for a tooltip-obscured HUD. One other percentage-only
field remained unreadable. The prototype lost no correct reading and recovered
one additional correct visual/neural level (75) from a 720p frame.

The faster path handled **49/56 (87.5%)**; seven fell back. Local mean elapsed OCR
time fell **1.639 → 1.189 s** (27.4%); process-tree CPU fell **90.516 → 65.391 s**
(27.8%). The seven fallback frames averaged **1.403 → 1.683 s**, with a largest
observed extra time of **0.427 s** across the batch. These timings exclude live
capture and network time. Data and verification remain ignored under
`private/cpu-efficiency/fresh-live-20261025-batch2/`; neither main nor production
was changed. There is now one fresh absent-HUD example, but unusual competing
HUDs, live Linux performance and end-to-end website acceptance remain untested.

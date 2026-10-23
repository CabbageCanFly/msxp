# HUD localization performance

Follows [capture performance](capture-performance.md) and the VPS offline runs (4 vCPU,
15 channels, 30 s requested, cache off), where mean localization grew from 4.47 s at 4
workers to 5.84 s at 6 and 7.75 s at 8. The question: can `adaptive_hud.locate()` cost less
**without losing whole-frame visibility of every HUD**?

Outcome: an output-identical, opt-in prototype (`locate(..., batched=True)`) saves ≈5–6 %
CPU and ≈9–10 % wall per frame on the workstation. Every option that cuts Tesseract's
recognition work changes, or plausibly weakens, competing-HUD evidence. Nothing is enabled
by default, the HUD cache stays off, and no VPS measurement exists yet.

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

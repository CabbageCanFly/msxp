# Short-lived cached HUD-region feasibility

**Two extra provisional matches, conditional on offline scene review. This is not
a standalone automatic recovery method.** An unchanged region can survive a brief
locator miss, but local anchor checks cannot establish that no competing HUD exists.
No recognition trust, character assignment or production behavior changed.

First, N08's full-field observation was recorded separately in
`private/stream3-reference-review/n08-review-sidecar.json`: original provisional
`119,956[40.74%]` → reviewed provisional `119,856[40.74%]`, while the highlighted
digit remains 9. It is explicitly **AI-assisted provisional review**,
`human_verified=false`, with no asserted human confirmation. The frozen candidate
manifest, sheets and source frames remain unchanged. N08 is outside this temporal
benchmark and has no effect on its counts.

All five missing-region frames in the frozen 44-frame, 1-Hz temporal sample were
visually inspected before the experiment. In every case, the preceding automatic
main-HUD region still contains the visible EXP field. The Stream 2 frames also
contain a separate game feed; this ambiguity is grounds for a cache veto, not a
reason to choose whichever crop produces plausible text.

| Missed frame | Previous unique location | Scene review | Outcome |
|---|---|---|---|
| Stream 2, 2987 s | 2986 s | Multiple HUDs | Reject cache; no neural inference |
| Stream 2, 2989 s | 2988 s | Multiple HUDs | Reject cache; no neural inference |
| Stream 2, 2991 s | 2990 s | Multiple HUDs | Reject cache; no neural inference |
| Stream 3, 1145 s | 1144 s | Single HUD | `74,059[25.17%]`, provisional match |
| Stream 3, 1150 s | 1149 s | Single HUD | `74,122[25.19%]`, provisional match |

`tools/cached_hud_probe.py` is an isolated diagnostic. The fixed policy is:

- Only a new unique locator result seeds a cache; only zero current candidates
  can use it. Fresh or ambiguous detections are never replaced by cached regions.
- Reuse age must be **0 < age ≤2 seconds** with the same frame dimensions. Reuse
  does not refresh that age. The replay clears state across windows or a veto.
- Current scene context must explicitly be `single_hud_reviewed`. Multiple or
  unreviewed HUDs abstain. This input comes from **offline full-frame review**;
  there is no new automated competing-HUD classifier.
- A 64×36 RGB scene thumbnail must remain within maximum-channel mean absolute
  difference 32; every HP/MP/EXP/LV anchor patch must remain within 4. Seed anchors
  need visible structure. No positional search, shifting or relocking is attempted.
- The cached field must be in bounds and retain visible bright/contrast evidence;
  an empty numeric field abstains even if the label anchors remain. This is only a
  content-presence check, not numeric or bracket verification.

The constants were fixed for this run, without a parameter sweep. They are geometry
heuristics, not calibrated false-accept guarantees. The two eligible real misses
have age one second. At 1145 s all four anchor patches are byte-identical to the
seed; at 1150 s their maximum-channel mean differences are 2.09–2.83. The scene
scores are 18.08 and 19.46. Movement/cut robustness beyond the synthetic checks
below remains unestablished.

Only the **two recovered current-frame crops** received new neural inference.
The existing RapidOCR 3.10.0 / ONNX Runtime 1.31.0 CPU model ran unchanged direct
line recognition with fixed 2× bicubic input and +2 native pixels on all sides.
Both final boxes are `[1292,1037,1428,1056]`, derived from previous automatic
regions and the **current** original frame. Cached pixels, EXP values, levels,
labels and nearby OCR strings never substitute for current numeric evidence.
For example the preceding visible values are 74,047 and 74,091, rather than the
two recovered numbers. No gains are computed from this difference.

Raw outputs/scores are preserved in `rapidocr-recovered.jsonl` before parsing;
scores .98319 and .97884 are not calibrated confidence in correctness. Both results
have complete unchanged parser syntax. New numerical mismatches: **0** against
provisional labels; malformed recovered outputs: **0**; wrong-HUD selections in
the two reviewed recoveries: **0**. Three cache attempts were vetoed. These tiny
counts are not independently verified accuracy or a production safety claim.

| All 44 frames | Before | After offline-gated cache |
|---|---:|---:|
| Available regions | 39 | **41** |
| Complete pair matches, reviewed 1146 sidecar applied | 32 | **34** |
| Complete pair mismatches against that provisional review | 3 | **3** |
| Unavailable pairs | 9 | **7** |
| Malformed raw lines | 4 | **4** |
| Missing/vetoed regions | 5 | **3** |

Against the *original frozen* annotations instead, counts change **31 / 4 / 9 →
33 / 4 / 7** (match/mismatch/unavailable). The earlier 1146 s correction is applied
only during report scoring; neither the frozen labels nor the baseline raw strings
change. The existing 39 unique-region outputs are reused byte-for-byte, with
**zero original successes lost**, by construction. Existing suspected numerical
errors at 1141, 1142 and 3359 s remain; cached localization does not verify them.
Level OCR was not rerun, so there is no new complete-triple or trusted-ingestion claim.

Four source-derived synthetic negatives were checked without neural inference:
shifted HUD, hidden HUD, added secondary HUD and age-three-second cache. All abstain
under the stated scene metadata. Invented public fixtures additionally cover a
hidden numeric field with intact anchors, frame resizing, scene cut with unchanged
HUD, ambiguous detection, unknown scene, out-of-order timestamps and non-extending
expiry at the two-second boundary.

**Important counterexample:** if the added-secondary-HUD image is deliberately
given a stale/incorrect `single_hud_reviewed` flag, the probe returns an untrusted
cached candidate: unchanged anchors and scene score 2.40 pass. The secondary-HUD
test therefore validates a **review veto**, not automatic competitor detection.
Unknown scene context always abstains. Thumbnail/anchor similarity cannot prove
absence of another feed, prevent every cut or character switch, establish video
freshness, or independently verify numbers. Automatic recovery without the reviewed
context gate was not demonstrated. A future worker cannot silently assume that gate.

Measured workstation costs, not Linux VPS performance:

- The 44-frame cache replay including PNG loading takes **1.569 s wall**, **1.531 s
  sampled process-tree CPU**, **52.44 MiB peak sampled RSS**. Fresh full-frame
  localization is reused from frozen results and excluded.
- The two recovery checks plus writing native crops take **6.08 / 4.91 ms**.
- Neural inference alone takes **25.48 / 21.87 ms** (mean/median 23.68 ms;
  p95 25.48 ms with only two samples). Full-frame loading/validation is separate.
  Neural process peak RSS is **159.78 MiB**; whole inference loop CPU .109 s.
  Import/constructor/cold first call are 2.051 / .014 / .220 s. These tiny samples
  do not establish stable percentiles or deployment throughput.

Private review: `private/cached-hud/review-real.png` contains all five real cases,
current EXP crops, raw recovered text and full-frame context. `review-synthetic.png`
contains the four negatives plus the deliberately stale-review counterexample.
`misses-before.png`, `miss-audit.json`, `plan.json`, `decisions.json`, `summary.json`
and the new inference JSON/JSONL preserve the details. The repeat reproduces decisions
and native crop pixels; original input/model hashes remain unchanged.

```powershell
# Use a NEW directory; source annotations and saved outputs are never replaced.
.\.venv\Scripts\python private/cached-hud/evaluate.py private/cached-hud/repeat2
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/cached-hud/repeat2/recovered-manifest.json --plan private/cached-hud/repeat2/plan.json --all --automatic-results private/cached-hud/repeat2/recovered-localization.json --padding 2 --output private/cached-hud/repeat2/rapidocr-recovered.json
Start-Process .\private\cached-hud\review-real.png
Start-Process .\private\cached-hud\review-synthetic.png
.\.venv\Scripts\python -m pytest tests/test_cached_hud_probe.py tests/test_rapidocr_benchmark.py -q -rs --basetemp private/cached-hud/pytest-targeted-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/cached-hud/pytest-full-repeat
```

Recommendation: cached localization merits a **larger offline test on independently
reviewed single-HUD sequences**, with real cuts, movement and consecutive misses.
Before automatic use, a separately validated global ambiguity/scene gate is needed;
local anchor stability is insufficient. Do not extend expiry or loosen numeric
trust to recover the vetoed Stream 2 frames. No automatic identity or level-up
behavior, production integration, new dependencies, commits or pushes.

Validation: **56 focused tests passed; full suite 621 passed, zero skipped**
(83.85 s with local loopback access). Fifteen new synthetic tests include the
deliberately stale-review limitation. All **263** snapshotted prior evidence files
remain byte-identical. Public additions are this report, the isolated probe and its
tests; N08's review and all diagnostic images/results remain private and ignored.

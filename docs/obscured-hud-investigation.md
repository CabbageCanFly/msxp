# Tricia obscured-HUD investigation

Investigation on 2026-10-19, feature worktree `msclassic-level-inference` at
`8f5e86b`. Localization is the observed failure stage. Webcam obstruction is a
plausible cause, not an established root cause. No recognition policy was changed.

The subsequent real-frame investigation below establishes the cause in the five
new images: a bottom-left EXP Tracker overlay covers the native level area. The
webcam is on the right. An EXP-only localization improvement is now implemented.

## Actual multi-stream path

1. `tools/multi_alpha.py` validates explicit channel/character assignments, binds
   sessions, and serially schedules `shadow.capture_attempt` with `ShadowSession`.
2. `tools/shadow_capture.py` uses `src/exp_tracker/video.py`: Streamlink supplies
   the named rendition to bounded FFmpeg keyframe decoding. It records local
   receipt time and frame SHA-256, closes acquisition, then calls `analyze`.
   Source PTS and broadcast age remain unknown.
3. `analyze` checks local age, invokes `tools/adaptive_hud.py:locate`, and records
   candidate count/geometry. The locator searches the whole frame at two scales
   with thresholded Tesseract sparse OCR. `layouts` requires HP, MP, EXP **and LV**
   with relative spacing/alignment and in-frame field boxes. Zero or multiple
   candidates return before field OCR. A single candidate is not proof of identity.
4. A unique layout supplies native EXP coordinates with bounded two-pixel padding
   (`benchmark_rapidocr.context_box`) and a level crop. The EXP crop goes through
   isolated, bounded RapidOCR at 2x scale, optionally with a separate neural level
   crop. Strict complete-pair and whole percentage-only parsers retain separate
   candidates. Visual Tesseract level evidence is read separately. Failed level
   OCR already permits EXP/percentage diagnostics; successful localization is the
   prerequisite that currently prevents this for Tricia.
5. Freshness is rechecked after stages. `multi_alpha.emit` flushes the private
   JSONL, then `Diagnostics.append` persists bound experimental attempts. This
   does not call trusted Store ingestion. `Diagnostics` decodes/project rows via
   `diagnostic_evidence.project` (`experimental_level_v6` / `exp_derived_level_v2`)
   for public cards/progress. Existing inference already supports missing readers.

The older `src/exp_tracker/capture.py` / `recognition.py` pipeline is separate;
changing only that recognizer would not fix multi-alpha. The adaptive module's
"not capture integration" docstring and older README experiment wording do not
describe its subsequent use by shadow capture.

## Saved evidence

Inspected existing private JSONL files read-only under the sibling main worktree:
`private/multi-alpha/runs/20261019T025444Z-0fbaad78/triciaisabirdy/`.
No SQLite database was opened or changed. This archive was still growing during
inspection: an initial read contained 359 attempts across six runs, a subsequent
read 361 across seven. These are observations at read time, not final run totals.

The earliest 237 attempts, sorted by receipt time, reproduce the reported pattern:

| Evidence | Result |
| --- | --- |
| Receipt range (UTC) | 2026-10-19 02:55:06 through 04:36:18 |
| Decoded dimensions | 1920 x 1080 throughout |
| Distinct frame hashes | 237 |
| Status / reason | `unavailable` / `["missing_hud"]` throughout |
| Returned HUD candidates | 0 throughout |
| EXP neural / visual level stages | `not_run` throughout |
| Local age after localization | 0.954 to 8.050 seconds, below the 15-second limit |

All 361 inspected attempts had the same missing-HUD outcome. The original frozen
four-run/237-attempt export was not located; the earliest-237 subset is a check of
the described symptom, not a claim that it is the exact original snapshot.

Only JSONL files exist in this channel's capture directory. There are no saved
frames/crops, and failed localization does not persist OCR tokens. Frame hashes
cannot reconstruct pixels. Other private reference files have no established
Tricia provenance. Changed hashes do not prove live gameplay or source freshness.

`--save-crops` alone cannot supply the missing evidence: `analyze` saves EXP/level
crops only **after** unique localization. Missing-HUD attempts return before that.

Consequently the evidence establishes localization failure, not which label was
missing or whether the game HUD was visible. It cannot distinguish obscured LV,
unrecognized HP/MP/EXP, different spacing/scale, a scene change, or another layout.

## Minimum evidence to collect

Keep all material under ignored `private/obscured-hud/` in this feature worktree;
use new filenames. Do not attach credentials, signed playback URLs, or databases.

- Save 3-5 native full-frame PNGs of Tricia's normal scene with the webcam in its
  usual position and visibly changing EXP. Preserve the delivered 1920x1080
  geometry, overlays and all possible secondary HUDs. A tight EXP crop alone
  cannot establish anchor geometry or uniqueness.
- Prefer exact decoder `Frame.png` bytes from a failing attempt, paired with its
  existing receipt timestamp, SHA-256, rendition and attempt index. Saving these
  must happen before localization, with an explicit small capture limit, outside
  the live database path. At investigation time the CLI had no full-frame save
  option; the standalone collector below now supplies this evidence.
- Alternatively, use an authorized local recording of the same composed stream
  and rendition. Extract native PNGs without resize/re-encoding the source video.
  Record source filename, requested offset and dimensions; an offline extraction
  is reproduction evidence, not a fresh live capture or verified frame PTS.
- Include one unobscured control if available (another established sample is
  useful), a no-HUD/hidden-EXP frame and any real competing-feed layout. Manually
  label which HP/MP/EXP/LV anchors and EXP/percentage characters are genuinely
  visible; mark uncertain digits unknown. Do not fill expected values from
  inferred levels.

For example, after placing an authorized recording locally, extract one frame at
a known relevant offset (repeat for other offsets with new output filenames):

```powershell
New-Item -ItemType Directory -Force private/obscured-hud | Out-Null
ffmpeg -hide_banner -loglevel error -nostdin -n -ss 00:01:00 -i private/obscured-hud/authorized-recording.mp4 -frames:v 1 private/obscured-hud/tricia-0060.png
```

This example was not run; no Tricia recording is available here. Do not start a
new remote trial without the existing capture authorization. No OBS credentials
or browser security changes are needed for local recording extraction.

With these images, replay the locator's exact two preprocessing scales and retain
all sparse-OCR tokens (text, coordinates, confidence), candidate counts and crop
coordinates in private diagnostics. Compare visible anchor annotations with those
tokens before adjusting localization. Run existing native EXP OCR only on reviewed
in-bounds crops; retain raw text/scores, strict parser results and missing level
evidence. This distinguishes token-recognition failure from geometric rejection.

## Conditional smallest fix

If images show a consistent visible HP/MP/EXP group with LV covered, add an
EXP-only layout for that validated geometry, with optional level region. Keep
existing four-anchor corrections for complete HUDs. Count complete and EXP-only
groups together before selecting a unique HUD: an early complete match must not
hide another obscured HUD. Never fabricate an LV location or OCR the webcam as a
level. Skip absent level crops in visual/neural readers and crop saving.

Keep bounds, stale checks, explicit assignment/session continuity, OCR/grammar
validation and the existing inference projection. Percentage-only observations
can retain existing supported level context; they cannot initialize a level from
nothing. Numeric EXP without usable percentage cannot supply arithmetic level
evidence under the existing policy.

A fixed stream ROI is not justified without measured coordinates and scene
evidence. It must not suppress competing-HUD detection or authorize a target by
level/EXP similarity. Choose it only if reviewed anchors cannot support a safe
locator; layout changes must cause abstention.

Before shipping a fix, cover complete/unobscured HUDs, covered LV, missing EXP,
ambiguous EXP anchors, competing complete/obscured HUDs, false label groups,
out-of-frame crops and stale frames. Exercise both strict pairs and whole
percentage-only fields through capture/persistence into the existing inference
system with level readers unavailable. Synthetic geometry tests establish these
contracts; independently labeled Tricia frames must establish actual recovery.

No locator change or new regression suite was added without the missing image
evidence.

## Verification

- Actual evidence: inspected the saved attempt metadata above; no Tricia image
  localization/EXP accuracy test was possible and no new remote capture was run.
- Existing synthetic focused tests: **108 passed**, zero skipped, covering
  adaptive HUD geometry, shadow capture, EXP-derived levels and their public
  projection. Missing LV is explicitly rejected by the current locator tests;
  missing level OCR is already tolerated after localization. These passing tests
  do not establish recovery on Tricia's layout.
- Full `python -m pytest -q -rs --basetemp=artifacts/pytest-obscured-hud`:
  **1,561 passed, 101 skipped** in 88.61 seconds. Separately: **100 private-fixture
  skips**, **1 loopback-policy skip**. This feature checkout has no private fixtures;
  the existing sibling virtual environment supplied dependencies only.
- The initial run had a missing parent `artifacts/` directory and failed fixture
  setup. Creating that directory and rerunning produced the results above.

At the original investigation milestone only this document changed. No production
code, tests, trusted accounting, live database, main-worktree files or performance
work was changed. No commit or push was made. Suggested commit at that point:
`docs: investigate Tricia HUD localization failures`.

## Opt-in full-frame collector

`tools/collect_hud_frames.py` now supplies the missing native images using the
existing `VideoSession` / `Frame.png` acquisition path. It runs before any HUD
localization and requires neither Tesseract nor RapidOCR. It does not load the
coordinator configuration, connect to SQLite or append to existing archives.

From this feature worktree, using the existing sibling capture environment:

```powershell
Set-Location H:\Desktop\codex\msclassic-level-inference
# Run only after confirming streamer permission for this specific Twitch trial.
# The timestamp makes a new directory; existing output is always refused.
$hudCollection = 'private/obscured-hud/tricia-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
& ..\msclassic-twitch-exp-tracker\.venv\Scripts\python.exe tools/collect_hud_frames.py --channel TriciaIsABirdy --authorized --quality best --count 3 --interval 5 --timeout 10 --output $hudCollection
```

`--authorized` is an explicit operator assertion of permission for **this** trial,
matching shadow capture's authorization gate. It is not platform authorization or
authentication of the on-screen character. The tool accepts one Twitch login,
never arbitrary remote/playback URLs, and retains Streamlink's existing browser,
configuration and sideloading restrictions. Do not pass tokens or credentials.
Access restrictions remain acquisition failures. No remote trial was run during
implementation or testing.

For an authorized existing local video, with another new output directory:

```powershell
$hudCollection = 'private/obscured-hud/local-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
& ..\msclassic-twitch-exp-tracker\.venv\Scripts\python.exe tools/collect_hud_frames.py --file private/obscured-hud/authorized-recording.mp4 --start 60 --count 3 --interval 5 --timeout 10 --output $hudCollection
```

The local video must already exist. `--start` is a seek request, not confirmed
frame PTS; local playback uses FFmpeg's existing real-time/keyframe behavior.
FFmpeg must be on PATH; Twitch additionally needs the existing Streamlink capture
extra in the selected Python environment. No dependencies or models are installed
or downloaded by this tool. A feature-local `.venv` with those dependencies can
be used instead of the sibling Python executable.

The new output must be a direct child of this worktree's ignored
`private/obscured-hud/`. Resolved paths outside that directory, nested output paths,
existing files/directories and output symlinks are refused before acquisition.
The collector exclusively creates the directory and each evidence file. It saves
`frame-01.png` etc. and `manifest.json`. PNG files are byte-for-byte copies of
the delivered `Frame.png`, with original decoded dimensions and no image scaling
or recompression. This is native decoder output, not the source video's original
compressed frame data.

The manifest records PNG size/dimensions/hash, local receipt time/sequence/age,
collection limits and outcomes. Twitch source identity includes the normalized
login and requested named rendition/selector. `best` is a selector: the actual
resolved rendition name is not available from `VideoSession`; dimensions are
recorded per PNG. If a known named rendition was used by the failing capture,
request that same name explicitly. Local source identity is a SHA-256 of kind
and resolved path, without exposing the filename/path or hashing the full video.
This identifies the assignment, not video contents or character identity. Neither
signed URLs, credentials nor subprocess stderr are persisted. Errors use fixed
codes. Source/broadcast age and verified PTS remain unknown.

Bounds and resource implications:

- `--count` is 1-5, default 3; no more than five PNGs and one small manifest.
  Each PNG has the existing 32 MiB / 4096x2160-pixel limit (the latter is a pixel
  count limit). Maximum PNG disk payload is 160 MiB. JSON has at most ten attempt
  entries and five frame entries.
- At most ten frame acquisition attempts and a 60-second monotonic collection
  deadline, checked before waits and after returned frames. Per-frame timeout is
  1-20 seconds (default 10), clipped to the remaining collection budget. Pauses
  are 1-10 seconds (default 5), also clipped. A local receipt age outside 0-5
  seconds is rejected. Source latency cannot be checked.
- One persistent session with the existing single latest-frame buffer, FFmpeg
  decoder/PNG encoder thread limits, Streamlink 4 MiB ring buffer and bounded
  subprocess cleanup. Keyframe-only decoding preserves the live pipeline's
  behavior. The session downloads the selected rendition between samples;
  keyframe skipping does not reduce network bandwidth. No new OCR/model cost.
- The 60-second budget covers normal collection, not a hard OS resource quota.
  Process launch, filesystem IO and existing bounded shutdown add overhead;
  shutdown terminates/reaps children and joins their threads. No CPU/RSS/network
  benchmark or platform-wide resource limit is claimed.

Only distinct PNG SHA-256 values are saved; duplicates still consume attempts and
time. Different PNG bytes do not prove different visible content. Completion can
therefore return fewer than requested frames (static video, sparse keyframes,
source end, deadline or errors). The manifest explicitly marks this shortfall and
the stop reason. Exit codes: 0 requested count collected; 2 incomplete; 130 operator
interruption; 1 validation/output failure. Ctrl+C preserves a partial manifest and
closes the session. Hard termination or disk failure can leave partial evidence;
preserve it and choose a new directory rather than overwriting it.

The collector itself does not localize or save localization OCR tokens. After
collection, review the PNGs and run the locator offline to establish which anchors
or geometry fail before implementing an LV-independent locator.

Collector validation on this Windows feature worktree:

- Targeted offline tests: **39 passed, 1 skipped** (Windows refused creation of
  the symlink used by one escape-path test). Other path-containment and exclusive
  output tests passed, as did byte/hash/dimension preservation, authorization,
  duplicates, count/deadline/timeout limits, stale frames and interrupted cleanup.
- Generated synthetic MP4 integration used the real FFmpeg decoder, verified
  saved PNG hashes and checked child/thread cleanup. A separate invocation of
  the actual CLI also saved and verified one frame from that synthetic video;
  its ignored output is `private/obscured-hud/offline-cli-check/`.
- Final full `python -m pytest`: **1,600 passed, 102 skipped** in 100.22 seconds.
  Separately: **100 private-fixture skips**, **1 loopback-policy skip** and
  **1 symlink-permission skip**. CLI help and whitespace checks passed.
- No real Tricia frame, remote Twitch trial or CPU/RSS/bandwidth benchmark was
  performed. These tests validate collection behavior, not Tricia localization.

Changed files: `tools/collect_hud_frames.py`, `tests/test_collect_hud_frames.py`
and this guide. Coordinator, locator, OCR, SQLite and tracking policies are
unchanged. No commit or push was made. Suggested commit:
`feat(diagnostics): add bounded native HUD frame collector`.

## Real-frame diagnosis and EXP-only recovery

Source: `private/obscured-hud/tricia-20261019-015257/`, five native 1920x1080
PNGs received on 2026-10-19 at 05:53:05.699 through 05:53:23.886 UTC. All five
manifest hashes/dimensions were verified. The five PNGs and manifest remain
byte-identical. No Twitch connection or existing database/archive was used.

All five full frames, enlarged native HUD strips and proposed EXP crops were
visually inspected. The game HUD has visible HP, MP, EXP, numeric EXP and
percentage. Its native LV label/value are covered by the **bottom-left EXP
Tracker overlay**, not the right-side webcam. The overlay has its own level and
EXP display, showing different EXP from the native HUD. It supplies no HP/MP
group and must not be treated as a game reading. There is one game feed, a webcam
and this overlay; no secondary game HUD is visible in these frames.

The unmodified original `adaptive_hud.locate` was instrumented by wrapping its
OCR/layout calls, preserving its grayscale, bicubic 2x/3x, threshold 160 and PSM 11
behavior. It returned zero candidates for every image. At **both** scales in
every frame Tesseract recognized the native HP, MP and EXP labels. No LV token
was recognized anywhere. The visible overlay level text also failed sparse OCR,
but it is outside the native anchor geometry and is not an acceptable substitute.

At the original 2x probe, native anchors were approximately:

| Anchor | Source x | Source y | Finding |
| --- | ---: | ---: | --- |
| HP | 706.5 | 1037.5 | Recognized in all five |
| MP | 859.5 | 1037.5 | Recognized, including `MP.` variant |
| EXP | 1015-1017 | 1035-1037.5 | Recognized in all five |
| Native LV | Expected label area x370-462, y1031-1061 | | Covered by overlay |

HP-to-MP spacing is 153 pixels; MP-to-EXP is 155.5-157.5 pixels. Alignment and
spacing pass the original row checks. This is the existing classic layout family
at a larger scale, not an unsupported stream position or rearranged EXP field.
The missing required LV anchor is the sole observed localization blocker. This
establishes the cause for this captured layout; no images exist to establish the
contents of every earlier failed attempt retrospectively.

### Narrow implementation

`adaptive_hud.layouts` keeps its complete four-anchor path and corrections. With
no matching LV it can now return a three-anchor candidate with explicit
`regions.level: null` and `anchors.lv: null`. This path requires bare HP/MP/EXP
labels (optional period/colon), confidence >=0.4, tighter spacing/alignment and
plausible relative label dimensions. It reuses the existing EXP field formula,
and rejects out-of-frame crops. There is no streamer name or fixed stream ROI.

Both existing preprocessing scales now contribute before uniqueness is decided.
Near-identical repeated candidates merge using stable MP/EXP anchor positions,
spacing and field bounds; a complete candidate can supply the level region for
the same group. Separate HUDs and disputed EXP/level geometries remain ambiguous.
No largest/first-HUD selection is introduced.

`shadow_capture.analyze` serializes null regions, saves only available crops,
skips visual level OCR when the level region is absent and passes no level PNG
to the existing neural protocol. Its worker already supports missing level crops.
Even an unexpected returned level is discarded for an absent crop. Existing
grammar, numerical safeguards, receipt-age checks, source/session binding and
frame hashes remain unchanged. No trusted accounting or inference policy changed.
Offline evaluators handle null regions; the four-anchor cache experiment continues
to reject incomplete groups rather than silently accepting a weaker cache seed.

### Real before/after results

Every proposed crop was manually checked. The native digits are 45,257 / 11.57%
in frames 1-4 and 45,390 / 11.60% in frame 5. These annotations come from the game
pixels; no known/guessed level, overlay level or EXP table supplied expected digits.

All after crops use bounded native coordinates `(1050, 1037, 1186, 1056)` including
the existing two-pixel context. The complete numeric field is inside each crop.

| Frame | HUD count before -> after | Exact RapidOCR text | Strict pair | Visual assessment |
| --- | --- | --- | --- | --- |
| 01 | 0 -> 1 | `45,257[11.57%]` | 45,257 / 11.57% | Correct |
| 02 | 0 -> 1 | `45,257[11.57%]` | 45,257 / 11.57% | Correct |
| 03 | 0 -> 1 | `45.257[11.57%]` | 45,257 / 11.57% | Correct digits; existing thousands separator grammar accepts the period |
| 04 | 0 -> 1 | `45,257[11.57%1` | Rejected | Correct visible digits, incorrect closing bracket OCR |
| 05 | 0 -> 1 | `45,390[11.60%]` | 45,390 / 11.60% | Correct |

Neural scores were respectively 0.95521, 0.97246, 0.96315, 0.94898 and 0.97676.
These are model scores, not accuracy probabilities: the high-scoring malformed
frame 4 is still rejected. There are **4/5 strict pairs, zero incorrect strict
pairs observed**, and no strict percentage-only outputs. Frame 4 retains raw
text/partial evidence; the existing grammar independently proposes a recovered
pair/percentage, which remains separately labeled and unverified. Its parser was
not relaxed. All five visual levels are unavailable, all five neural levels are
`missing_crop`, and neither level reader ran on the covered area.

No wrong-target crop was observed in these five images. The separate overlay EXP
text was not selected. This small positive set is not a general false-positive
rate measurement.

Five existing private reference screenshots were replayed through original and
new locators. Streams 1, 2, 5 and 6 each returned one complete HUD with **identical
before/after EXP and level pixel boxes**. Stream 4 remained missing in both.
The four localized controls produced strict EXP pairs with the real neural
worker; ordinary level-reader availability remains variable. These checks do not
establish that all other stream layouts or absent-HUD scenes are safe.

### Existing public inference, not another estimator

The real replay outputs were appended only to a **new private evaluation DB**,
with explicit channel/character/session assignment, original hashes and receipt
times, and an `offline_replay` marker. Freshness here measures local offline
processing, not new live receipt or broadcast age. The public projection was
evaluated at the historical receipt time, not served as current live progress.

The existing `experimental_level_v6` / `exp_derived_level_v2` policy establishes
**inferred level 43 on frame 5**, using eligible samples 2, 3 and 5. The first
three strict pairs are constant, and the last increases by 133 EXP / 0.03
percentage points. The existing policy needs multiple eligible samples and
forward progression, not a different EXP integer in every sample. Both reader
levels remain absent. The result is explicitly unverified, display-only and
ineligible for strict windows; the native level is obscured, so it is not
independently verified level ground truth. Trusted observations remain **zero**.
This demonstrates the actual public projection on these captured values rather
than relying solely on a synthetic progression demonstration.

Synthetic integration additionally establishes a level from three rising pairs,
retains it through whole percentage-only readings, rejects percentage-only level
initialization, and preserves trusted state. Other synthetic checks cover missing
EXP, covered LV, low-confidence/false labels, ambiguity, duplicate geometry,
competing complete/partial HUDs across scales, invalid bounds and stale work.

### Verification and remaining limits

- Initial focused suite: **187 passed**, zero skips. An added ambiguous-EXP case
  and evaluator coverage also ran in the final full suite.
- Final full Python suite: **1,623 passed, 102 skipped**, 104.72 seconds.
  Skips: **100 unavailable private fixtures**, **1 loopback policy** and
  **1 Windows symlink permission**. Available sibling reference screenshots and
  the new Tricia images were evaluated explicitly offline as described above.
- Relevant `product.test.mjs` / `shadow.test.mjs`: **59 passed**, zero skipped.
  Existing HTTP/public-provenance tests passed in Python; no frontend change was
  needed.
- The existing `test_real_neural_timeout_reaps_worker` immediate PID-existence
  check failed in two earlier runs, passed alone, and passed in the final full
  run. No timeout code or that test was changed; its intermittent Windows result
  is recorded rather than hidden. Whitespace checks passed.
- Real after-replay local processing age was 2.69-3.23 seconds on this workstation.
  Always checking both sparse-OCR scales adds work to ordinary HUDs that formerly
  stopped after the first match. Existing age gates remain; this is not a server
  CPU/RAM/capacity benchmark or a hard processing deadline.

Ready for a longer **authorized experimental validation run**, with real HUD
changes, stationary periods, scene changes, obstructions and eventual level-up
evidence. Five images do not establish false-positive rates, long-run numerical
accuracy or correctness of the provisional EXP table. Frame 4's punctuation
failure remains. No new remote capture was started here and no active coordinator
was restarted or modified.

Private evidence is in `private/obscured-hud/tricia-analysis-01/`: original locator
snapshot, input hashes, `before.json` / `after.json` (all sparse tokens, boxes,
scores and candidates), `geometry-audit.json`, `visual-review.json`, manual/after
EXP crops, `controls.json`, `control-ocr.json` and `public-projection.json` plus the
separate replay DB. All are ignored; source images and their manifest were not
rewritten. No images, crops, OCR logs or databases are added to Git.

Changed implementation: `tools/adaptive_hud.py`, `tools/shadow_capture.py`;
nullable-region callers in `tools/evaluate_adaptive_hud.py`,
`tools/evaluate_cadence.py`, `tools/evaluate_cross_stream.py` and
`tools/cached_hud_probe.py`; regression tests in `tests/test_adaptive_hud.py` and
`tests/test_obscured_hud.py`; this guide. No commit or push made.

Suggested commit: `fix(hud): localize visible EXP without a level anchor`.

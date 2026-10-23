# CharC obscured-HUD investigation

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
   prerequisite that currently prevents this for CharC.
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
`private/multi-alpha/runs/20261019T025444Z-0fbaad78/streamer_c/`.
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
CharC provenance. Changed hashes do not prove live gameplay or source freshness.

`--save-crops` alone cannot supply the missing evidence: `analyze` saves EXP/level
crops only **after** unique localization. Missing-HUD attempts return before that.

Consequently the evidence establishes localization failure, not which label was
missing or whether the game HUD was visible. It cannot distinguish obscured LV,
unrecognized HP/MP/EXP, different spacing/scale, a scene change, or another layout.

## Minimum evidence to collect

Keep all material under ignored `private/obscured-hud/` in this feature worktree;
use new filenames. Do not attach credentials, signed playback URLs, or databases.

- Save 3-5 native full-frame PNGs of CharC's normal scene with the webcam in its
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
ffmpeg -hide_banner -loglevel error -nostdin -n -ss 00:01:00 -i private/obscured-hud/authorized-recording.mp4 -frames:v 1 private/obscured-hud/streamer_c-0060.png
```

This example was not run; no CharC recording is available here. Do not start a
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
contracts; independently labeled CharC frames must establish actual recovery.

No locator change or new regression suite was added without the missing image
evidence.

## Verification

- Actual evidence: inspected the saved attempt metadata above; no CharC image
  localization/EXP accuracy test was possible and no new remote capture was run.
- Existing synthetic focused tests: **108 passed**, zero skipped, covering
  adaptive HUD geometry, shadow capture, EXP-derived levels and their public
  projection. Missing LV is explicitly rejected by the current locator tests;
  missing level OCR is already tolerated after localization. These passing tests
  do not establish recovery on CharC's layout.
- Full `python -m pytest -q -rs --basetemp=artifacts/pytest-obscured-hud`:
  **1,561 passed, 101 skipped** in 88.61 seconds. Separately: **100 private-fixture
  skips**, **1 loopback-policy skip**. This feature checkout has no private fixtures;
  the existing sibling virtual environment supplied dependencies only.
- The initial run had a missing parent `artifacts/` directory and failed fixture
  setup. Creating that directory and rerunning produced the results above.

At the original investigation milestone only this document changed. No production
code, tests, trusted accounting, live database, main-worktree files or performance
work was changed. No commit or push was made. Suggested commit at that point:
`docs: investigate CharC HUD localization failures`.

## Opt-in full-frame collector

`tools/collect_hud_frames.py` now supplies the missing native images using the
existing `VideoSession` / `Frame.png` acquisition path. It runs before any HUD
localization and requires neither Tesseract nor RapidOCR. It does not load the
coordinator configuration, connect to SQLite or append to existing archives.

From this feature worktree, using the existing sibling capture environment:

```powershell
Set-Location <branch checkout>
# Run only after confirming streamer permission for this specific Twitch trial.
# The timestamp makes a new directory; existing output is always refused.
$hudCollection = 'private/obscured-hud/streamer_c-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
& <your msxp folder>\.venv\Scripts\python.exe tools/collect_hud_frames.py --channel Streamer_C --authorized --quality best --count 3 --interval 5 --timeout 10 --output $hudCollection
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
& <your msxp folder>\.venv\Scripts\python.exe tools/collect_hud_frames.py --file private/obscured-hud/authorized-recording.mp4 --start 60 --count 3 --interval 5 --timeout 10 --output $hudCollection
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
- No real CharC frame, remote Twitch trial or CPU/RSS/bandwidth benchmark was
  performed. These tests validate collection behavior, not CharC localization.

Changed files: `tools/collect_hud_frames.py`, `tests/test_collect_hud_frames.py`
and this guide. Coordinator, locator, OCR, SQLite and tracking policies are
unchanged. No commit or push was made. Suggested commit:
`feat(diagnostics): add bounded native HUD frame collector`.

## Real-frame diagnosis and EXP-only recovery

Source: `private/obscured-hud/streamer_c-20261019-015257/`, five native 1920x1080
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
  the new CharC images were evaluated explicitly offline as described above.
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

Private evidence is in `private/obscured-hud/streamer_c-analysis-01/`: original locator
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

## Feature wrap-up: one short isolated trial

Wrap-up review of `e01b281` found no remaining serious correctness/safety issue
requiring another implementation change. Rechecked geometry merging/ambiguity,
crop bounds, null level crops and their callers, freshness, worker limits,
diagnostic persistence and public inference. This is still an experimental
single-layout-family recognizer, not character authentication.

Verified environments (read-only checks plus an actual offline EXP worker call):

- Capture Python: `<your msxp folder>\.venv\Scripts\python.exe`;
  Python 3.14.7, Streamlink 8.6.2, Pillow 12.3.0, pytesseract 0.3.13, psutil 7.2.2.
- OCR Python: `<your msxp folder>\private\rapidocr\.venv\Scripts\python.exe`;
  RapidOCR 3.10.0, ONNX Runtime 1.31.0. Existing models loaded successfully with
  worker downloads disabled. The saved first CharC EXP crop again returned
  `45,257[11.57%]`, with neural level `missing_crop`.
- Tesseract: `C:\Program Files\Tesseract-OCR\tesseract.exe`.
  FFmpeg: `C:\Shortcuts\exe\ffmpeg.EXE`.
- Offline `shadow_capture.prepare` passed for the command below: `args.db` is
  absent, no output was created and no remote connection was made. The script
  inserts this feature worktree's `src/`; borrowing the sibling interpreter
  does not select main's acquisition implementation.

Run **only after confirming permission for this specific Twitch trial**:

```powershell
Set-Location '<branch checkout>'
$capturePython = '<your msxp folder>\.venv\Scripts\python.exe'
$ocrPython = '<your msxp folder>\private\rapidocr\.venv\Scripts\python.exe'
$trial = Join-Path (Get-Location) ('private\obscured-hud\streamer_c-validation-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
Write-Host "Private trial: $trial"
& $capturePython tools/shadow_capture.py --channel streamer_c --authorized `
  --quality best --count 24 --interval 20 --timeout 15 --max-age 15 --ocr-timeout 10 `
  --experimental-neural-level --save-crops --ocr-python $ocrPython `
  --output (Join-Path $trial 'capture.jsonl')
```

Expected duration is about eight minutes at the measured cadence. This is an
attempt-count limit, not a hard wall-time deadline; overruns can extend it. Press
Ctrl+C at ten minutes if needed. The runner closes owned capture/worker processes
and writes an interrupted summary. Do not force-kill it to enforce a timer.
The runner normally writes JSONL silently; inspect the growing file in another
terminal if needed. Exit 0 alone does not establish successful OCR.

There is no `--db`, server, live configuration or coordinator access in this
command. New output paths are required. Crops are under
`$trial/capture/0001/exp.png` etc.; covered levels have no `level.png`. Missing or
ambiguous localization saves no crop. CPU/network are shared with other local
processes, even though files, state and owned subprocesses are isolated.

After the run, reuse the existing **offline replay** to inspect public inference
and Advanced coverage. This creates a separate review database, never opens the
active database, and never starts capture. Keep `$trial` from the command above:

```powershell
$reviewConfig = Join-Path $trial 'review-config.json'
$reviewDb = Join-Path $trial 'review.sqlite3'
if ((Test-Path $reviewConfig) -or (Test-Path $reviewDb)) { throw 'Use new review output names.' }
@{
  database = $reviewDb
  port = 8787
  streams = @(@{ channel = 'streamer_c'; character = 'Isolated validation'; source = 'twitch' })
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $reviewConfig
& $capturePython tools/multi_alpha.py --config $reviewConfig `
  --replay ('streamer_c=' + (Join-Path $trial 'capture.jsonl'))
```

`--replay` bypasses acquisition; no `--twitch-status` is enabled. This is a new
offline viewer process on port 8787, not the active coordinator. Use another free
port if necessary. Open `http://127.0.0.1:8787/stream/streamer_c` and
`http://127.0.0.1:8787/dashboard/streamer_c`. Ctrl+C closes the review viewer.
The original JSONL/timestamps remain unchanged. A normal or Ctrl+C summary is
needed for replay of this no-DB log; preserve/review incomplete logs after a hard
termination rather than inventing a completion.

Review all at most 24 attempts and available crops:

1. **Detection:** count acquired frames, unique/missing/ambiguous HUDs and failures.
   Advanced's coverage distinguishes strict pairs, percentages and grammar
   proposals; these categories overlap and are not an accuracy score.
2. **OCR:** manually compare every strict accepted number with its native crop.
   Separate correct, wrong and unreadable, then review rejected/recovered text.
   A high model score or arithmetic agreement is not digit verification.
3. **Target/false positives:** confirm crop coordinates and content belong to the
   native EXP row, not the separate overlay. Observe the stream during the trial
   for scene/identity changes. Crops alone cannot establish full-frame uniqueness
   or explain a missing-HUD frame; use the existing opt-in full-frame collector
   only if an anomaly needs context.
4. **Level continuity:** inspect the public level/context and Advanced decisions.
   Establishment needs several eligible, distinct frame hashes and forward EXP
   and percentage progress. Stationary play need not establish a level. Missing
   level OCR stays missing; percentage-only retention must remain inferred and
   gaps/conflicts/transitions must remain dated or explicitly uncertain.
5. **Freshness:** inspect increasing receipt times, repeated hashes,
   `local_age_seconds`, `current`, `status`, per-stage timings and resource
   snapshots. Stale results must remain ineligible. Receipt age is local only;
   hashes, Twitch availability and a low local age cannot prove broadcast age.

Merge recommendation: **ready after short live validation**. No implementation
blocker was found. Require no wrong-target or wrong strict accepted values in the
reviewed sample, reliable localization while the native row is visible, honest
stale/gap handling and coherent inferred continuity when sufficient progression
occurs. A short trial will not establish broad false-positive rates, table
accuracy or every real level-up scenario. Do not expand this into a new phase.
After integrating main's independent performance work, run the combined suite;
its projection changes were not reimplemented or audited here.

Wrap-up checks: **193 focused Python tests passed, zero skips**; previous final
full suite **1,623 passed / 102 skipped** (100 private fixtures, one loopback,
one symlink permission), plus **59 frontend tests passed**. No production code
changed during wrap-up, so that full run was not repeated. No remote trial,
active database write, coordinator restart, merge or push was performed.

## CharA duplicate level interpretations (2026-10-19)

This follow-up supersedes the earlier requirement that disputed level crops make
the entire EXP HUD ambiguous. Conflicting EXP geometry still rejects field OCR.

Only the three requested CharA JSONL files were frozen and replayed, under ignored
`private/streamer_a-hud-dedup-20261019/`. The latest log had grown from the reported 36
attempts to 49 at snapshot time; both the original first 36 and all 49 were checked.
Original logs/crops were read-only. The two earlier input hashes remain identical;
the latest original continued appending and retains the exact frozen byte prefix.
No live database, coordinator or remote capture was modified or started.

### Cause and bounded fix

The active path is still `multi_alpha` -> `shadow_capture.analyze` ->
`adaptive_hud.locate`. Both sparse-OCR scales contribute layout candidates, and
`merge_layouts()` previously required both EXP and level crops to agree within
5% of the smaller anchor step. A difference in level crop incorrectly survived
as an additional HUD, even when both candidates agreed on the EXP location.

For latest-run attempt 2, the native EXP rectangles are `(1025,1051,1120,1061)`
and `(1026,1051,1120,1062)`: one-pixel edge differences. MP positions differ by
0.167 pixels and EXP anchors by at most 0.833 pixels. Level rectangles start at
x605 and x594, differing by 11 pixels, beyond the unchanged 5.45-pixel tolerance.
Attempts 3 and 4 show the same pattern. This is duplicate EXP geometry with
disputed LV interpretation, not evidence of two independently positioned EXP HUDs.
Without full frames, the logs cannot establish every physical scene retrospectively.

`merge_layouts()` now groups candidates using the existing step, MP/EXP anchor
and EXP-edge tolerances, without requiring level agreement. It compares every
member of a group rather than allowing a near-duplicate chain to bridge different
EXP regions. `locate()` collects unmerged layouts from both unchanged OCR probes
and deduplicates once, preserving conflicting geometry until that decision.

For a group with disputed level rectangles, the returned candidate retains an
existing EXP rectangle and has `regions.level=null`, `anchors.lv=null`,
`anchor_mode=hp_mp_exp`, and `level_ambiguous=true`. No union, averaged crop,
confidence-based winner or inferred level coordinates are created. The ambiguity
flag survives repeated merging, so a later complete proposal cannot restore the
disputed level. Ordinary agreeing full layouts keep their existing level crop.

Both original four-anchor candidates must already pass the existing layout
checks. Discarding the disputed level crop does not change the missing-LV
three-anchor admission rules or EXP matching tolerances. The existing capture
path skips visual/neural level OCR for an unavailable crop, including discarding
an unexpected returned level. EXP OCR, receipt freshness, hashes, frame bounds,
grammar, numerical consistency, explicit character assignment and trusted
accounting remain unchanged. No grammar or UI change was needed.

### Frozen geometry replay

Paths below are relative to `private/multi-alpha/runs/`:

| Recording | Attempts | Unique before -> after | Multiple before -> after | New EXP OCR opportunities |
| --- | ---: | ---: | ---: | ---: |
| `20261019T092547Z-0e1bd0f9/streamer_a/capture.jsonl` | 60 | 43 -> 54 | 17 -> 6 | 11 |
| Same folder, `b84401fd96444d2582dc724ee8310584/capture.jsonl` | 11 | 9 -> 11 | 2 -> 0 | 2 |
| `20261019T095936Z-ef8a3750/streamer_a/capture.jsonl` (frozen snapshot) | 49 | 35 -> 48 | 14 -> 1 | 13 |
| Latest recording, reported first 36 only | 36 | 23 -> 35 | 13 -> 1 | 12 |

Across the non-overlapping 120 attempts, 26 of 33 multiple-HUD failures collapse
to unique EXP geometry with unavailable level. All 87 original unique candidates
remain exactly unchanged. The seven remaining EXP ambiguities are first-run
attempts 3, 12, 27, 29, 40, 55 and latest-run attempt 30. Their EXP rectangles
disagree by 6-9 pixels, or an EXP anchor is outside the existing tolerance.
For example, latest #30 proposes `(1021,1051,1114,1061)` versus
`(1026,1051,1120,1062)`, plus a 6.5-pixel EXP-anchor y discrepancy. The code
does not arbitrarily choose one. Full failing frames would be needed to decide
whether these are additional OCR artifacts or genuinely different source geometry.

None of the 26 formerly rejected attempts has a saved EXP crop or OCR text:
capture returned before those stages. No full frames are present in these run
directories. Therefore these counts establish localization opportunities, not 26
new EXP readings, a newly measured complete-pipeline success rate, or a physical
false-positive rate. Missing historical observations were not fabricated or
retroactively inserted. Saved-log replay compares candidate geometry and uses
the original receipt times/readings for causal public projection.

All 26 opportunities have distinct saved hashes, native 1920x1080 dimensions and
local post-localization ages of 1.789-2.546 seconds, below the existing 15-second
limit. They would still need to finish field OCR within that limit. Neither hashes
nor receipt ages establish broadcast freshness.

### Existing grammar and public projection

Read-time diagnostics already recover these malformed saved readings into public
numeric EXP: 29/29 in the first log, 8/8 in the rotation, and 29/30 in the latest
49-attempt snapshot. The reported first 36 contain 19/20 recoverable malformed
readings. All 66 recovered full pairs display level 69 and their own numeric EXP;
the raw text, grammar provenance and unverified status remain intact.

The remaining latest attempt 20 is `260,6SS113.33%1`, with letter substitutions
in the numeric digits. Existing grammar correctly abstains rather than supplying
digits. Representative saved EXP/level crops were inspected, but no new OCR or
digit-repair experiment was performed. The `malformed_or_unavailable` acquisition
status describes the strict parser result; it does not mean public grammar
recovery also failed. All existing saved numerical/public projections are unchanged
by this acquisition-only fix.

### Verification and limits

New regressions use the actual CharA anchor coordinates, optional private-log
replays and synthetic distinct HUDs/conflicting EXP regions. They cover ordinary
full layouts, level ambiguity in either order, sticky ambiguity, non-mutating
merges, EXP/MP/step conflicts, near-duplicate chains, joint cross-scale uniqueness,
level-OCR suppression, crop saving, stale frames and the existing public inference
path. Existing focused inference/interval tests cover level transitions, source
and character boundaries, stationary EXP and numerical contradictions.

The focused Python set passed 246 tests with no skips. No incorrect unique accept
was observed in the negative controls; seven disputed real EXP groups still
reject. This cannot establish OCR accuracy on the 26 unsaved crops or rule out
every wrong-target layout. A capture-process restart is required to load the
locator change; no restart was performed. Archived failures cannot be repaired
without their original pixels. No performance work, coordinator change or new
production tooling was introduced.

Final full `python -m pytest -q -rs --tb=short` result: **2,042 passed, one
skipped** in 673.42 seconds. The sole skip is the existing OS symlink-permission
test; there are no private-sample skips. The suite includes public API/background
publisher, identity-boundary, numerical-consistency and level-transition checks.
`git diff --check` passed. Frontend/browser checks were not repeated for this
locator-only change. Suggested commit:
`fix(capture): deduplicate EXP HUDs with ambiguous level crops`.

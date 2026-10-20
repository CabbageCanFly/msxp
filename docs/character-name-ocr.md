# Offline character-name OCR

The useful source is the **own-name line beneath the job in the bottom game status
panel**. Existing RapidOCR weights read it well in this small development set.
Automatic HUD localization is useful but incomplete. This prototype only proposes
a name for operator review; it never opens a tracker database, changes a roster,
selects a character, renames anything or merges EXP history.

The [diagnostic capture follow-up](#diagnostic-capture-follow-up) below reuses the
resident EXP worker and existing HUD layout, adds per-channel pending suggestions,
and measures per-capture overhead. The initial offline evaluation remains below.

## Run it

Run from this worktree. Its optional environments and footage remain at their
existing paths in the original checkout; nothing needs copying or installing:

```powershell
$repo = 'H:\Desktop\codex\msclassic-twitch-exp-tracker'
$python = "$repo\.venv\Scripts\python.exe"
$rapid = "$repo\private\rapidocr\.venv\Scripts\python.exe"

# Measured local-video example: proposes hefferheffer from two distinct frames.
& $python tools/character_name_ocr.py --video "$repo\samples\sample-stream2.mp4" --times 3129.51,6259.02 --engine rapidocr --rapid-python $rapid --output private/character-name/video.json

# Images: pass frames from ONE stream/character sequence, in capture order.
& $python tools/character_name_ocr.py "$repo\private\cross-stream\stream3\frames\0000.png" "$repo\private\cross-stream\stream3\frames\0022.png" --engine rapidocr --rapid-python $rapid --output private/character-name/images.json

# Smallest fallback when localization fails: operator marks the own-name line.
# This measured example proposes emmies; coordinates are SOURCE IMAGE pixels.
& $python tools/character_name_ocr.py "$repo\private\levelup-evaluation\overview-0000.png" "$repo\private\levelup-evaluation\overview-1200.png" --region 480,991,651,1015 --owner-field --engine rapidocr --rapid-python $rapid --output private/character-name/manual.json
```

For another installation, use its development Python (Pillow/pytesseract), installed
Tesseract, FFmpeg on PATH for videos, and an **existing** isolated RapidOCR 3.10.0
environment. `--engine tesseract` is the default and needs no neural environment;
`--engine both` retains both attempts and rejects confident spelling conflicts.
RapidOCR mode still needs Tesseract for automatic HUD localization, but manual-region
RapidOCR needs no Tesseract executable. No package/model downloads happen here.

`--region x0,y0,x1,y1` alone means **unverified ownership**: useful for checking a
floating name, party row or information window. It cannot produce an owner proposal.
`--owner-field` explicitly records the operator's assertion that the region contains
the streamer's own name. It is a calibration assertion, not independent verification.
Do not use it to assert that an arbitrary nearby player is the streamer.

Outputs are JSON (all frames, raw OCR, scores, boxes, hashes, timings and proposal),
CSV (one row per engine/region) and a PNG crop sheet when candidates exist. Boxes
are `[left, top, right, bottom]` in source pixels; Tesseract token boxes are also mapped
back to source pixels. Neural raw coordinates remain in the worker's 2x crop space;
the enclosing candidate supplies its full-frame region. Frames with no regions stay
in JSON. Output names overwrite earlier reports at the same path. Keep these private;
the default output and all evaluation evidence are under Git-ignored `private/`.
Exit 0 means a report was produced, **including unknown/ambiguous reports**; exit 1
means setup/input failure. An engine failure is retained in that attempt's `error`.

## Sources and ownership

| Source | What the saved evidence establishes | Prototype treatment |
| --- | --- | --- |
| Bottom status panel | Own name remains visible in ordinary gameplay, including crowded maps and combat | Bind HP/MP/EXP/LV geometry with the existing HUD locator, crop the lower text line |
| Floating nameplate | Readable names belong to players, pets and NPCs; effects and overlap interfere | Manual recognition only; ownership unverified |
| Party list | Multiple names, including the streamer; ordering does not establish self | Manual recognition only; no first-row selection |
| Character information window | No representative own-information window was found in this bounded selection | Untested; operator must establish whose window it is |
| Chat/stream overlays | Account names, speakers and stale tracker text need not be the current character | Not an ownership source |

Screenshot 2 shows the streamer as **Ryambi** in the status panel and on a floating
nameplate, alongside **Whoami**, **Stammi**, a **Black Pig** pet and a party list.
Whoami has an orange nameplate; color or the most confident name is insufficient.
The five screenshot layouts also include a VTuber/music overlay, large cat/camera
overlays, small inset gameplay, party play and two game/HUD scales. Status-panel
ownership is still an assumption about the active game feed: a replay, spectated
feed or a stale embedded game image could satisfy the same geometry.

## Bounded evaluation, 2026-10-20

All labels are **Codex visual transcriptions, zero independent human verification**.
This is a development feasibility check, not held-out accuracy. Geometry was
inspected on these layouts before the final run; no threshold/model was fitted,
no expected names enter the recognizer and no fuzzy spelling correction is used.
The existing recording manifests supplied timestamps, not character-name answers.

Positive set: **15 real full frames, five distinct character names**:

- Original screenshots `maplestory-classic-stream{1,2,4,5,6}.png` (five frames).
- Existing `private/cross-stream/{stream2,stream3}/frames/{0000,0022,0044}.png`
  (six frames): Stream 2 at 0, 3129.510, 6259.020 s; Stream 3 at 0, 1799.515,
  3599.030 s, covering both its larger and windowed layouts.
- Existing `private/levelup-evaluation/overview-{0000,0600,1200,1740}.png`
  (four frames from `sample-stream.mp4`).

Four negative frames: original recording at **454 s** (game area black, streamer
overlays still visible), existing `overlay-sample-reference.png`, the crowded
screenshot cropped above its status panel, and its isolated nearby Whoami plate.
The last two are private derivatives of one real frame, not independent captures.
There were no new network captures. No wider footage scan or OCR scale sweep.

Manually reviewed own-name readability is **15/15**. Automatic localization yields
the correct own-name region on **12/15**, no region on three positives, and none on
the four negatives. Recognition compares case-sensitive whole strings, ignoring
outer whitespace only. Candidate syntax is conservatively 2–12 Latin letters/digits,
starting with a letter, and engine score at least .5. Scores are uncalibrated.

| Input / engine | Exact raw name / 15 | Exact candidate / 15 | Wrong candidate | Positive abstentions |
| --- | ---: | ---: | ---: | ---: |
| Manual / Tesseract | 9 | 8 | 0 | 7 |
| Manual / RapidOCR | **15** | **15** | 0 | 0 |
| Automatic / Tesseract | 3 | 3 | 0 | 12 |
| Automatic / RapidOCR | **12** | **12** | 0 | 3 |
| Automatic / both | 12 | 12 | 0 | 3 |

The Tesseract raw mistakes include **five wrong spellings**, all below .5, plus
`Telfer |` containing a panel border. One exact raw reading also falls below .5.
Do not interpret zero *candidate* errors as zero OCR errors.

**Owner identification, separate from readability:** automatic RapidOCR supplies
12 correctly associated own-status-panel candidates, zero incorrect associations,
and seven abstentions across 19 frames (three localization misses + four negatives).
These are review evidence, not accepted tracker identities. Grouped temporal review
proposes the correct name on **3/3 multi-frame recording groups**:

| Recording group | Frames including corresponding screenshot | Distinct automatic support | Proposal |
| --- | ---: | ---: | --- |
| Original | 5 | 3 | emmies |
| Stream 2 | 4 | 3 | hefferheffer |
| Stream 3 | 4 | 4 | Mawile |

The Telfer and Ryambi singleton groups remain unknown for lack of another frame.
All four negatives yield no owner candidate/proposal. **False-owner identifications:
zero observed**, with only four limited negatives; this does not establish a safe
false-owner rate. Manual own-field RapidOCR also proposes the three recording names,
with 5/4/4 distinct supporting frames respectively. Tesseract alone proposes only
emmies automatically. Never pool different streams into one temporal invocation.

Concrete successes/failures:

- Screenshot 2: automatic RapidOCR `Ryambi`, box `[511,1053,697,1078]`.
  Nearby Whoami is read at ~1.000 score on a manually marked plate but stays
  unverified; the status panel establishes the useful ownership context.
- Stream 2 at 3129.510 and 6259.020 s: both automatic names `hefferheffer`;
  actual video CLI returns `review_required` with support 2.
- Original recording at 0 s and screenshot 4: status name `emmies` is readable,
  but the existing automatic locator finds no HUD. The manual fallback succeeds.
- Stream 2 at 0 s: same localization miss despite readable `hefferheffer`.
- Manual Tesseract `heternetier` / `hetfernetier` instead of `hefferheffer`,
  and `Mavwile` instead of `Mawile`; low scores retain abstention.
- Five extra manually inspected nameplate/party/pet regions on screenshot 2:
  RapidOCR exact raw text **3/5**. `Stammi` becomes **`Starmi` at .949**;
  `Black Pig` becomes `Alack Pig` at .943. These are generic-region readings,
  never owner proposals. This set is separate from the 19-frame status-panel test.

## Agreement and processing cost

`tools/character_name_ocr.py` reuses `adaptive_hud.locate`, Tesseract `_ocr`, the
existing FFmpeg `frame_at` helper and the unchanged `shadow_rapidocr.py` worker.
Both recognizers get one fixed 2x variant: inverted grayscale for Tesseract PSM 7,
RGB for RapidOCR direct line recognition. The existing local model hashes and
versions are preserved in neural raw evidence: RapidOCR 3.10.0 / ONNX Runtime 1.31.0,
PP-OCRv6 small models. No neural detector, new model or dependency was introduced.

Agreement requires the same exact spelling on at least two **different RGB frame
hashes**. Repeated files/pixels do not vote twice. Multiple detected HUDs, conflicting
scoped names anywhere in the batch, or confident engine disagreement force ambiguity;
there is no first/highest-score/majority winner. A missing final frame prevents a
stale proposal. Video times are sorted; image inputs must be supplied in capture
order. A batch is a short review sequence, not a production switch state machine.
Unverified manual regions never vote. Even successful agreement is `review_required`,
`trusted: false`. No previous accepted tracking state exists in this tool to overwrite.

Sequential workstation wall times, excluding video extraction/report rendering:

| Work | Measured approximate time |
| --- | ---: |
| Tesseract name region | 90 ms mean |
| RapidOCR worker per region, including startup/imports | 1.18–1.20 s mean |
| First neural inference in fresh worker | 160 ms mean |
| Existing two-scale full-frame HUD localization | 2.16 s mean over 19 frames |
| Automatic + both engines | 2.97 s/frame over all 19; 3.85 s on 12 located frames |

The worker starts afresh per region; these are cold process costs, not a resident
recognizer benchmark. Successful local-video extraction and manual-image CLI runs
were also checked. VPS CPU/RAM, live cadence, compressed low-resolution streams,
non-Latin names, actual character switches and long-run false-owner rates remain
unmeasured. Repeated stable OCR errors can still agree across frames.

Private review artifacts in **this worktree**: `private/character-name/manifest.json`
(paths, manual regions, labels), `evaluation.json` (all attempts), `summary.json`,
`auto-rapidocr.{json,csv,png}`, `manual-rapidocr.{json,csv,png}` and corresponding
Tesseract/both reports; `plate-results.json`, context sheets, `cli-video.*` and
`cli-manual.*`. The models and original inputs remain in the original checkout.

## Shortest integration path

1. Human-review the private labels and collect a few truly independent sequences,
   including switches, missing status panels and two visible game feeds.
2. Reuse the capture worker's existing HUD result for a name-region read at a modest
   cadence; avoid another full-frame localization pass. Keep one pending suggestion
   with source frame/time and last confirmed selection; unknown/conflict changes
   neither roster nor accepted EXP state.
3. Show the crop and suggested exact name to the operator. When localization fails,
   let the operator mark the own-name status field once for that layout, or manually
   supply the character name. Requesting an own-character information window is a
   secondary, untested fallback.
4. After explicit confirmation, use the existing character/session selection flow
   (`Store.add_character`, `select_character`, `start_session`) with its existing
   ownership and in-flight session guards. A switch ends the old session and begins
   a separate baseline; never infer identity from EXP/level, rename automatically,
   or join histories because strings resemble one another. No Store integration is
   included in this milestone.

Focused verification: `python -m pytest -q tests/test_character_name_ocr.py
tests/test_adaptive_hud.py tests/test_recognition.py tests/test_video.py
tests/test_shadow_neural_level.py tests/test_rapidocr_benchmark.py -n 0`.
The initial related run passed **177 tests, zero skips**. Coverage includes spelling
conflicts, unsupported syntax, score rejection, duplicate pixels, multiple HUDs,
missing latest evidence, manual ownership, OCR failures and CLI image/video paths.
The full suite and private sample-test suite were intentionally not run.

## Diagnostic capture follow-up

Branch preflight: `main` and local `origin/main` were both `48b5d80`, already ancestors
of this branch; the worktree was clean. This implementation reuses main's resident
worker, cache interfaces and bounded capture operation. Nothing was merged or committed.

From this worktree, with the existing environments in the original checkout:

```powershell
$repo = 'H:\Desktop\codex\msclassic-twitch-exp-tracker'
$python = "$repo\.venv\Scripts\python.exe"
$rapid = "$repo\private\rapidocr\.venv\Scripts\python.exe"

# Opt-in, local-video diagnostics only; NEW private output name required.
& $python tools/shadow_capture.py --file "$repo\samples\sample-stream2.mp4" --start 3120 --interval 15 --count 3 --character-names --ocr-python $rapid --output private/character-name/integration/demo-NEW.jsonl

# The private, clearly labeled splice made during this investigation:
# emmies / emmies / hefferheffer / hefferheffer, four 10-second segments.
# Numeric events override a deliberately long five-minute periodic interval.
& $python tools/shadow_capture.py --file private/character-name/integration/switch-montage.mkv --interval 10 --count 4 --character-names --name-interval 300 --experimental-neural-level --ocr-python $rapid --output private/character-name/integration/switch-NEW.jsonl
```

The second input is an ignored **synthetic splice of real full frames from different
recordings**, not a naturally observed same-channel switch. Its source paths/segment
labels are in `integration/montage-labels.json`. Public checkouts can use their own
local recording for the first command; no footage or model is distributed.

The CLI prints one compact JSON object per attempt, including the proposed name,
pending switch, observed name, numeric reason and dated crop/hash/score reference.
Example excerpt from the splice's fourth attempt:

```json
{
  "index": 4,
  "proposed_name": "emmies",
  "pending_switch": "hefferheffer",
  "observed_name": "hefferheffer",
  "numeric_reason": "level_change_requires_confirmation",
  "source_evidence": {"box": [917, 808, 1050, 826], "score": 0.99975},
  "trusted": false
}
```

Full private JSONL adds `character_name.evidence`, `suggestion`, `numeric_check`,
`verification_requested`, `identity_conflict`, `reading_hold_recommended`,
`hold_reasons` and `tracking_action: "none"` alongside the
existing EXP/level results. Evidence retains raw text/scores, inference and bridge
times, queue wait, source/canonical pixel hashes, receipt time, frame sequence,
source-pixel box, model provenance, layout search origin and full-scan age. Parent
capture records retain the file/seek provenance and explicitly unknown verified PTS.
No report claims verified broadcast freshness or ownership. A failed name attempt
preserves the completed EXP result, and an expired name result cannot vote.

### What is shared and bounded

`character_name_ocr.name_region(layout, size)` extracts the field from an **already
located** HUD. The offline tool and `shadow_capture.analyze` use the same geometry;
the capture path never calls the offline tool's full-frame discovery. Zero/multiple
layouts abstain before name inference. Cached layouts already have source coordinates;
their `search`/age provenance is retained. The cache remains off by default and its
existing competing-HUD blind window is not cured by name recognition.

`--character-names` implicitly enables the existing `ResidentNeural`. EXP runs first;
the name is a second direct-line request to **the same process and model**, with the
same command/protocol even when experimental level OCR is enabled. No new worker
protocol, model, dependency or training. The name request uses at most the existing
crop limit (1024x256, 1 MiB encoded); each worker reply remains bounded to 64 KiB.
Its response wait is at most two seconds, after acquiring the shared worker lock;
queue wait is measured separately and is not covered by that response timeout.
Default capture freshness still gates eligible name evidence.

All existing defaults remain disabled/unchanged when name OCR is off. The standalone
shadow CLI additionally exposes main's `--resident-neural` and `--hud-cache-seconds`
for local comparisons; no cache is implicitly enabled. Name mode rejects Twitch
inputs and `--db` before opening a connection/store. `multi_alpha.py` was reviewed
but remains unchanged: its normal path initializes assignments and persists diagnostics,
so this milestone deliberately demonstrates parallel callers without that writer.
The shared `capture_attempt(..., identity=...)` interface supports a separate
`IdentityCapture(channel)` per lane with one shared resident. Never share identity
state between lanes; the standalone channel key is the canonical local-video path.

### Suggestions and verification events

`tools/character_identity.py` keeps only two confirming references, a 128-hash
duplicate window and bounded numerical context per channel. Two exact names on
different RGB frames within the existing 120-second confirmation bound establish
an **unverified proposal**. A different name needs its own two frames and produces
`pending_switch.kind: "possible_character_switch"`; it never replaces the proposal.
No name comes from a level/EXP value. There is no fuzzy matching or confidence winner.

Unreadability, conflicts, multiple HUDs and capture failures clear an unfinished
confirmation. Duplicate or out-of-order frames cannot add support. Long gaps clear
confirmation too. Pending switches follow the lifecycle below; nothing is ever
automatically selected. The original offline batch tool keeps its stricter
whole-batch ambiguity policy.

Default `--name-interval 0` checks **every eligible capture**. With a longer interval,
initial confirmation, confirmation of a newly observed name and numerical events
bypass the timer. Numerical reasons reuse `validate_transition`, `assess` under both
existing display hypotheses, and the existing confirmation/wrap constants:

| Evidence | Verification classification; never a switch decision |
| --- | --- |
| Same-level loss/reset | Existing `reset_loss_or_character_switch` reason requests a check |
| Level decreases or any other level change | Existing `level_change_requires_confirmation` requests a check; direction is labeled |
| Adjacent +1 level and existing 95%-to-5% wrap range | `possible_normal_level_up`; still check, do not infer a switch |
| Higher level after a gap over 120 seconds | `possible_offstream_progression`; no claimed proof of off-stream activity |
| EXP/percentage contradict both supplied rounding hypotheses | `possible_bad_ocr`; do not replace the numerical comparison anchor |
| Incomplete current numerical evidence after a prior baseline/proposal | Request verification with `unknown` classification |

There is no new XP-rate or level-jump threshold. Larger jumps remain unresolved
changes under the existing validator; supported progression after a gap can be
legitimate. Numerical context uses complete EXP pairs and a visual level; checked
neural levels are retained independently, not silently substituted. A suspect numeric
sample does not advance the comparison anchor unless the same frame's name check
reads the reference identity (or it is a `possible_normal_level_up`), so unresolved
changes keep requesting checks. Only repeated independent **name** evidence can
suggest a switch.

### Identity lifecycle and attribution decisions (`identity_policy: review_only_v2`)

Each capture reports three separate outcomes. They are deliberately not one flag:

| Field | Meaning | Set by |
| --- | --- | --- |
| `verification_requested` | A name check is warranted now | Any numeric event above, or an unfinished name confirmation |
| `identity_conflict` | Name evidence disagrees with the **reference identity** | This frame's name differs, or a switch is pending |
| `reading_hold_recommended` + `hold_reasons` | Attributing this reading to the reference character could contaminate its EXP history | `name_mismatch`, `pending_switch`, `unverified_numeric_anomaly` |

The **reference identity** is the operator-confirmed name when one was supplied
(`reference_source: "operator_confirmed"`), otherwise the first two-frame OCR proposal
(`"ocr_proposed"`). `confirmed_name` and `proposed_name` are reported separately and
OCR never writes `confirmed_name`; two-frame agreement is evidence, not authorization.

Numeric anomalies are split by what they can mean. `reset_loss_or_character_switch`,
`level_decrease`, other `level_change_requires_confirmation` jumps and
`possible_offstream_progression` could be another character, so they hold **only
until** a name check on the same frame reads the reference identity (e.g. a death
EXP loss with the right name is not held). `possible_normal_level_up`,
`possible_bad_ocr` and incomplete numbers request verification but never an
identity hold: they are ordinary EXP-validity questions that `validate_transition`
already answers for the tracker. A verified level-up (or the wrap rule) becomes the
next numeric anchor, so one legitimate level-up no longer flags every later capture.
Before this change it did: the anchor stayed on the old level and the hold persisted
indefinitely.

A pending switch (`pending_switch.state: "pending"`) is created when a name other
than the reference gets two distinct frames. It ends, moving to the bounded
`history` (16 entries, with its two evidence references and `resolved_at`/`resolved_by`), as:

- `superseded`: the reference name returns with two frames (A→B→B→A→A), or a third
  name gets two frames and becomes the new pending switch.
- `expired`: at least 600 s since the pending name was last seen **and** the reference
  name has been seen since (one frame is enough). Absence of name evidence alone
  (unreadable, multiple HUDs, stale, failed) never expires a switch or lifts a hold.
- `dismissed`: operator `dismiss(at)`. The name needs two new frames to return, and
  single mismatching frames are still held: dismissal never authorizes the other
  name's readings for the reference character.
- `confirmed`: operator `select(name, at)` with the pending name. Selecting a different
  name records `superseded`.

`IdentityCapture.select(name, at)` is the only way to set the operator identity. It
also clears the OCR proposal, the confirmation streak and the numeric anchor, so the
new character's first reading is a `first_observation` baseline, never compared with
the previous character's EXP. One reference sighting alone (A→B→B→A) does not clear
a pending switch before expiry; a single-frame mismatch (A→A→B→A) is held only for
that frame and leaves no suggestion.

### Integration boundary with `multi_alpha.py` (not implemented)

In `multi_alpha.py` every attempt record is bound to a run, and every run is bound
to one `(character_id, session_id)` at startup. The record is then written by
`diagnostic.append(lane['run_id'], record)` inside `emit(lane, record)`. That is
the attribution point, so a future integration should:

1. Create one `IdentityCapture(channel, confirmed=<selected label>)` per lane, from
   the Store's existing `selected_character_id` label. Never derive it from OCR.
2. Pass it to `capture_attempt(..., identity=...)`, which already shares the lane's
   resident worker and located HUD.
3. In `emit`, **before** `diagnostic.append` attributes the reading, check
   `record['character_name']['reading_hold_recommended']`. A held record should keep
   its raw evidence but be stored as unattributed/held, not as an EXP observation of
   the selected character. How held records are stored is a schema decision for that
   milestone.
4. After an operator accepts a switch: `Store.select_character` (which ends the old
   session with `character_switch`) → `Store.start_session` → rotate the lane to a new
   run bound to the new session → `identity.select(label, at)`. Held readings from
   the pending window stay unattributed unless an operator assigns them explicitly.
   Do not replay them into either history automatically.

This milestone only reports these decisions. EXP ingestion, selection, sessions,
histories, roster, public UI/API and systemd configuration are unchanged.

Lifecycle verification: **283 focused tests passed** (the command below; 17 new
sequences cover A→A→B→B, A→A→B→A, A→B→B→A→A with and without an operator identity,
third names, similar-EXP switches, level-ups with and without a readable name, level
decreases, loss/gap/bad-OCR anomalies, missing/stale/duplicate evidence, expiry,
dismissal, operator selection and channel isolation). The full suite passed **2343,
skipped 118** (private fixtures absent from this worktree, one OS symlink test).
Replays to new ignored `integration/lifecycle-*.jsonl` reproduced the earlier name
outcomes: Stream 2 3/3 `hefferheffer` with no hold; the splice holds capture 3
(`name_mismatch`, `unverified_numeric_anomaly`) and adds `pending_switch` at capture 4.
The seek is wall-clock based, so replays decode different frames from earlier runs. Same-frame
EXP/level equality with names on vs off remains a unit test. Policy-only cost rose from 3.4
to 4.2 µs per observation, negligible against ~90 ms name OCR.

### Saved-video and focused verification results

- `real-stream2-enabled.jsonl`: original `sample-stream2.mp4`, start 3120 s,
  three captures. **3/3** names `hefferheffer`, proposal after capture 2, no switch.
  EXP and names alternate requests 1/2, 3/4, 5/6 in the same resident process.
  Name work 56–88 ms. Requested 5-second cadence actually produced approximately
  10-second starts because existing capture/localization work exceeded five seconds.
- `real-stream3-enabled.jsonl`: original `sample-stream3.mp4`, start 1790 s,
  two captures at requested 15 seconds. First reads **Mawile** (.93495); the next
  locator returns **two layout candidates**, so no name inference/proposal. This
  negative is preserved, not cropped around or retried with a different OCR strategy.
- `switch-montage.jsonl`: four decoded frames of the private splice, all four exact
  names; `emmies` proposal retained while `hefferheffer` becomes a pending switch
  only on its second distinct frame. Experimental neural levels and names share one
  worker (name requests 2/4/6/8).
- `switch-event-priority.jsonl`: same splice with `--name-interval 300`. Captures
  1–2 confirm `emmies`; capture 3's level decrease bypasses the timer immediately;
  capture 4 checks again and proposes the pending switch. The proposed name stays
  `emmies`. This proves the local workflow, not a naturally observed stream switch.
- Paired frozen-frame experiment: four real name-bearing frames (three names) and
  two negatives, two enabled and two disabled passes. All **8 enabled positive reads
  exact**, all **4 negative evaluations abstain**, zero incorrect owner-field associations.
  Every EXP/level status and candidate matches disabled results. Shared-worker burst
  comparisons also preserve exact EXP strings and scores.

**266 focused tests passed, zero skips**, including the original name/OCR tests,
capture, resident/cache/scheduler interfaces, validation and arithmetic boundaries.
New synthetic sequences cover stable names, repeated switches, similar-EXP switches,
temporary unreadability, alternating/conflicting names, same pixels in differently
encoded PNGs, multiple HUDs, channel isolation, failures, stale results, level drops,
large jumps, normal level-ups and possible progression after a gap. The similar-EXP
switch tests establish suggestions entirely from names, without any numeric anomaly.

```powershell
& $python -m pytest -q tests/test_character_identity.py tests/test_character_name_ocr.py tests/test_shadow_capture.py tests/test_shadow_neural_level.py tests/test_capture_performance.py tests/test_adaptive_hud.py tests/test_recognition.py tests/test_video.py tests/test_validation.py tests/test_exp_consistency.py tests/test_capture_ocr_guard.py -n 0
```

### Incremental overhead and 15-channel / 60-second target

Private reproducible experiment: `integration/benchmark.py` / `benchmark.json`.
Frozen actual HUD layouts avoid measuring Tesseract variability twice. After resident
startup, six frames run disabled/enabled/enabled/disabled; recognition and visual
level OCR remain real. Separately, 15 channel jobs x two rounds contend for one
resident, with 1/3/4 caller threads. This tests worker contention, **not** full live
15-channel capture throughput. No database or network is used.

| Paired six-frame pass (4 eligible, 2 negative) | Disabled mean | Enabled mean |
| --- | ---: | ---: |
| Wall time, excluding frozen localization/extraction | 2.385 s | 2.753 s |
| Corrected sampled process-tree CPU | 2.281 CPU-s | 2.625 CPU-s |
| Highest sampled process-tree RSS | 262.73 MiB | 263.30 MiB |

Increment: about **0.37 s wall / 0.34 CPU-s per six-frame pass**, or roughly
**90 ms per eligible capture** including pixel hashing/provenance. Negative frames
also spend ~22–27 ms hashing, so dividing the full difference by four is conservative.
Short-lived Tesseract CPU sampling and workstation noise limit the paired CPU estimate.
The worker-only CPU below uses exact process-tree CPU deltas. Windows venv Python
launches the real interpreter behind a small wrapper; measurements include both.
Sampled CPU subtracts the resident's pre-phase lifetime CPU, not only parent CPU.
The first exploratory wrapper-only CPU/RSS readings were invalid and are retained
privately as `benchmark-initial-wrapper-metrics-invalid.json`, not used here.

| Caller threads, 30 jobs | Disabled wall / worker CPU | Enabled wall / worker CPU | Name queue mean / max |
| --- | --- | --- | --- |
| 1 | 1.58 s / 1.52 CPU-s | 3.28 s / 3.08 CPU-s | <.01 / <.01 ms |
| 3 | 1.58 s / 1.44 CPU-s | 3.24 s / 3.09 CPU-s | 108 / 115 ms |
| 4 | 1.59 s / 1.48 CPU-s | 3.25 s / 3.16 CPU-s | 149 / 172 ms |

One resident command/model in every case; worker tree RSS stayed **131.13 MiB**.
Additional neural CPU is **52–56 ms/check**. At 15 channels every 60 seconds this
is ~0.014 of one workstation core for neural inference, or ~0.022 core including
the conservative paired hash/evidence cost. Applying the earlier performance report's
1.9x CPU factor gives ~0.04 VPS core; this is a **projection**, not a VPS measurement.
Three callers' mean RPC-only job time rises from .147 to .312 s; names share the
serialized worker and can delay other EXP calls. The 15-job burst adds about .83 s
of resident work, well below 60 s. This does not revalidate total capture/publisher
capacity, the dominant full-frame localization cost or network latency.

Recommend **every eligible capture**, keeping HUD caching a separate explicit choice.
With successful independent frames at interval I=60 s, a switch needs two name reads:
roughly **60–120 seconds plus capture/OCR completion** after the actual switch.
Missing/ambiguous/duplicate frames extend this; there is no bounded latency when
the own-name panel is unavailable. Numeric events cannot detect a switch between
similar levels/EXP, which is why periodic verification remains mandatory.

If later VPS measurements require a longer periodic interval C (e.g. 300 s), the
existing option combines periodic checks, immediate numeric-event checks and
next-capture confirmation of a newly seen name. Without an anomaly, best-case
switch suggestion latency becomes roughly **60–360 seconds plus work** at I=60,
and gaps/conflicts can delay it further. Numeric-triggered verification occurs in
the same acquired frame, never immediately at an unobserved event between captures.
The small measured name cost does not currently justify that latency tradeoff.

All new evidence is ignored under `private/character-name/integration/`. No naturally
occurring same-stream character switch, independent human label audit, VPS/live Twitch
trial, long-run false-owner rate, crowded multi-game-feed study or full/private-sample
test suite was performed. Cache blind spots, systematic repeated spelling errors,
arbitrary legitimate naming rules and stale/replayed game feeds remain limitations.

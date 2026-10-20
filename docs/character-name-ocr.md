# Offline character-name OCR

The useful source is the **own-name line beneath the job in the bottom game status
panel**. Existing RapidOCR weights read it well in this small development set.
Automatic HUD localization is useful but incomplete. This prototype only proposes
a name for operator review; it never opens a tracker database, changes a roster,
selects a character, renames anything or merges EXP history.

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

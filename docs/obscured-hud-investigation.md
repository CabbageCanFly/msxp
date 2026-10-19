# Tricia obscured-HUD investigation

Investigation on 2026-10-19, feature worktree `msclassic-level-inference` at
`8f5e86b`. Localization is the observed failure stage. Webcam obstruction is a
plausible cause, not an established root cause. No recognition policy was changed.

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
  the live database path. The current CLI has no full-frame save option.
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

Only this document changed. No production code, tests, trusted accounting, live
database, main-worktree files or performance work was changed. No commit or push
was made. Suggested commit: `docs: investigate Tricia HUD localization failures`.

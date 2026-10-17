# Opt-in neural level diagnostics in shadow capture

Follow-up: the [read-time provisional level/EXP policy](exp-validity-level-policy.md)
now combines these unchanged raw diagnostics for experimental product displays and
percentage progress. The original worker benchmark and raw-reader semantics below
remain unchanged; nothing is promoted into trusted Store accounting.

`--experimental-neural-level` adds the evaluated fixed **Neutral4** visual-level
diagnostic to the existing shadow worker. Default operation remains EXP-only neural
recognition plus unchanged Tesseract/arithmetic evidence. No live capture was run.
Production recognition, Store, trust guards, accounting, level-ups, EXP table,
percentage pace, OBS overlay and leaderboard statistics are unchanged.

## Small worker extension

Legacy callers still send one native PNG and receive the original EXP result keys.
Opt-in callers send two length-prefixed PNGs to **one process / one initialized
recognizer**. EXP is processed first with unchanged 2× bicubic preprocessing; the
same engine then processes the level with the exact frozen benchmark helper:
`invert(min(R,G,B))`, converted to RGB and enlarged 4× bicubic. No RGB fallback,
S→5/B→6 mapping, grammar recovery, score cutoff or EXP-based answer selection.
The shared worker uses RapidOCR 3.10.0 / ONNX Runtime 1.31.0, CPU and one inference
thread. Existing local model/dictionary files are required; downloads are refused.

Limits remain explicit: EXP **1024×256 native / 1 MiB**, level **256×128 native /
1 MiB**, paired stdin **2 MiB+8 bytes**, response **64 KiB**, one serial worker,
existing total subprocess timeout (default 10s, CLI maximum 30s). Zero-length level
payload means missing; EXP cannot be empty. Length overruns, extra bytes, non-PNG
and unsafe dimensions are refused. No queue, retry or separate level process exists.

An invalid/oversized optional crop or a level-stage exception records an unavailable
level while preserving the independent EXP result. Malformed EXP/whole-worker
responses fail safely. A timeout kills the combined worker and loses that attempt's
neural outputs; it does not recover a partial EXP result or launch another worker.
Tesseract still runs when freshness permits. A completed result exceeding local
age remains diagnostic with `current: false`; it never becomes current/trusted.
The paired stage can overrun the age budget before returning, as the prior single
stage could; it is not a hard real-time deadline.

Opt-in configuration records `experimental_neural_level: true` and preprocessing
`neutral4`. Every opt-in attempt has separate `neural_level` evidence, including
not-run states after capture/locator failure. A successful example has:

```json
{
  "neural_level": {
    "status": "numeric_candidate",
    "text": "51",
    "level": 51,
    "score": 0.97088,
    "raw": {"txts": ["51"], "scores": [0.97088], "boxes": null},
    "preprocessing": "neutral4",
    "preprocess_seconds": 0.0002,
    "inference_seconds": 0.021,
    "source_complete": null,
    "trusted": false
  }
}
```

Other statuses distinguish nonnumeric, invalid numeric (`0`, out of range or padded
numbers), ambiguous output, no output, missing/invalid crop, failure, invalid
response and not-run. Only a whole ASCII integer 1–200 is interpreted; internal
spaces and substituted glyphs are not repaired. Raw text and scores remain intact
in private JSONL. An inconsistent claimed level/text/status is rejected separately
without completing a missing visual reading.

**`visual_level` remains Tesseract only.** Existing full/percentage-only candidates,
arithmetic sets/relation and percentage-pace inputs retain that meaning. A neural
contradiction is visible in the diagnostic viewer but does not alter EXP candidate
semantics or replace visual evidence. Syntactic validity and confidence do not
prove that a complete tile group was present: `source_complete` stays unknown.

## Offline actual-interface replay

Reused the fixed 52 entries from [the isolated level experiment](rapidocr-level-evaluation.md):
50 available crops, two missing. This is familiar development data, not an
independent holdout. References retain James/ChatGPT-assisted provenance; the two
historical original-recording errors remain separately Codex-provisional.

The actual `neural_line` subprocess bridge and updated stdin interface were used,
not an in-process stand-in. **All 50 level raw strings and score arrays reproduce
the previous Neutral4 benchmark exactly.** All **48** same-input frozen EXP strings
and scores also match; the other two available EXP crops have no directly matching
saved neural baseline and are not scored as additional successes. Four additional
EXP-only worker controls match shared-worker EXP text/scores exactly.

| Fixed source | Scheduled | Correct numeric | Incorrect numeric | Unavailable | Missing crop |
|---|---:|---:|---:|---:|---:|
| Reviewed A, level 63 | 12 | 9 | 0 | 2 | 1 |
| Reviewed B, level 51 | 12 | 11 | 0 | 0 | 1 |
| User-reviewed original lower levels | 6 | 5 | 0 | 1 | 0 |
| User-reviewed Stream 2 lower levels | 6 | 6 | 0 | 0 | 0 |
| User-reviewed Stream 3 windowed, level 40 | 6 | 6 | 0 | 0 | 0 |
| User-reviewed Stream 3 large, level 40 | 6 | 6 | 0 | 0 | 0 |
| Historical known cases, Codex-provisional | 2 | 1 | 0 | 1 | 0 |
| Controlled negatives, no complete numerical reference | 2 | — | — | 2 | 0 |

The clipped tile control still produces raw **`0`**, rejected as invalid numeric;
the blank remains empty. These are not proof of a clipping detector. A synthetic
test explicitly makes an incomplete tile produce valid `1` and verifies that it
remains untrusted with unknown source completeness. The known 599s case retains
Tesseract 3 versus neural 8 (provisional reference 8); 1061.75s retains Tesseract 8
and nonnumeric neural output. A/R024 still has Tesseract 63 versus nonnumeric `B3`.
The native RGB high-confidence **51→50** errors from the previous experiment are
preserved evidence; RGB is never called as a fallback here.

Private `private/shadow-neural-level/replay-02/` contains input receipts, fixed plan,
copied native field pixels, raw per-call JSONL, `report.json`, and separately derived
`viewer-stream-a.jsonl` / `viewer-stream-b.jsonl`. Original captures/annotations and
prior benchmark outputs remain unchanged. Replay-01 is retained; replay-02 repeats
the same inputs after adding opt-in configuration metadata, with no recognition
change. All 193 original preparation receipts and current replay inputs verify.

## Actual workstation costs

The final run used **50 paired workers + four EXP-only controls**; no video capture,
localization or Tesseract was included. Process startup is paid once per attempt.

| Shared-worker stage | Mean | Median | p95 |
|---|---:|---:|---:|
| Worker-reported initialization | 688.76ms | 687.78ms | 703.38ms |
| EXP recognition | 161.37ms | 160.65ms | 184.60ms |
| Level preprocessing | 0.23ms | 0.23ms | 0.33ms |
| Warm level recognition | 21.57ms | 21.34ms | 23.06ms |
| Whole worker subprocess wall | 1,146.94ms | 1,144.66ms | 1,181.71ms |

Initialization excludes Python/module bootstrap; EXP's first inference includes
lazy recognition-model loading. Whole process wall also includes PNG I/O, helper
imports, model fingerprints, serialization and teardown. Four direct paired controls
add **5.1–43.2ms** wall versus EXP-only (mean **28.3ms**); small-sample startup/cache
variation prevents treating these differences as a calibrated latency guarantee.
Both modes use one worker, and the paired mode adds one warm level call.

Full replay: **62.33s wall**, **46.63s sampled parent+child CPU**, peak aggregate RSS
**183.14 MiB**, sampled at 20ms. This includes the offline parent and one neural
worker; brief peaks can be missed. These are Windows workstation measurements,
not Linux/VPS performance, livestream bandwidth or parallel-channel capacity.

## Read-only comparison and replay commands

`/dev/shadow` now appends **RapidOCR EXPERIMENTAL / UNVERIFIED** text, numeric
interpretation, score, status and visual/neural agreement/conflict to the existing
Tesseract level cell. Missing Tesseract stays missing. The EXP/percentage charts
still use only their existing fields, with visual levels from Tesseract. No new
pace section or trusted API field is added. Both visual sources remain unverified.
Privacy allowlisting, text redaction, file limits, opt-in routes, localhost bind,
polling and stale-log notices are retained; raw level text outside the existing safe
character set is explicitly redacted in HTTP, preserved in the private log.

```powershell
# Actual saved-crop worker replay; NEW output directory required, no live source.
.\.venv\Scripts\python private/shadow-neural-level/replay.py private/shadow-neural-level/repeat-01
# Existing current-schema DB, used read-only:
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/statistics-preview.sqlite3 --shadow-log private/shadow-neural-level/replay-02/viewer-stream-b.jsonl --port 8879
# Separate terminal:
Start-Process 'http://127.0.0.1:8879/dev/shadow'
node tools/shadow.browser.mjs http://127.0.0.1:8879/dev/shadow artifacts/shadow-neural-browser-repeat
.\.venv\Scripts\python -m pytest tests/test_shadow_neural_level.py tests/test_shadow_capture.py tests/test_shadow_view.py tests/test_server.py -q -rs
node --test tools/shadow.test.mjs
.\.venv\Scripts\python -m pytest -q -rs
```

The private replay helper needs existing private prepared evidence and RapidOCR
environment. Synthetic public tests need no models, crops or secrets.

## Later permitted live trial; do not start automatically

We have familiar reviewed **51** examples, but no independently reviewed genuine
**50** example in this selected material. Existing clipped/blank controls are
constructed, not new genuine obstructed-stream holdouts. Seek new permitted source
examples of real 50 and 51, partial/obstructed tiles and varied raster geometries.
Do not infer their level from the EXP table or prime the blinded reviewer with it.

For each new consenting stream, James can run **30 attempts** (~7.5 minutes) or
explicitly raise to **60** (~15 minutes), retaining every failure:

```powershell
.\.venv\Scripts\python tools/shadow_capture.py --channel NEW_CHANNEL --authorized --interval 15 --count 30 --experimental-neural-level --save-crops --output private/neural-level-trial/captures/new-stream-a.jsonl
# Repeat separately for the second permitted channel, using new-stream-b.jsonl.
.\.venv\Scripts\python tools/shadow_review.py prepare --run private/neural-level-trial/captures/new-stream-a.jsonl private/neural-level-trial/captures/new-stream-a --run private/neural-level-trial/captures/new-stream-b.jsonl private/neural-level-trial/captures/new-stream-b --output private/neural-level-trial/review-01 --seed 17
```

No streamer installation or OBS configuration is needed. Existing Streamlink/platform
limitations in [live capture](live-capture.md) still apply; `--authorized` records
the operator's permission assertion. Stop on access denial; do not retry individual
frames to replace failures. No trial ran in this milestone.

Give reviewers only the anonymous `review/` sheets and blank answer/provenance
forms. Do not open viewer/model logs before review. Preserve explicit unknown or
ambiguous fields; crop-only review cannot authenticate main-character identity or
competing HUD selection. Then copy/fill forms and freeze **before scoring**:

```powershell
Copy-Item private/neural-level-trial/review-01/review/answers-template.csv private/neural-level-trial/review-01/completed.csv
Copy-Item private/neural-level-trial/review-01/review/provenance-template.json private/neural-level-trial/review-01/provenance.json
# Fill the copied forms, retaining all IDs, before running these:
.\.venv\Scripts\python tools/shadow_review.py freeze --prepared private/neural-level-trial/review-01 --answers private/neural-level-trial/review-01/completed.csv --provenance private/neural-level-trial/review-01/provenance.json
.\.venv\Scripts\python tools/shadow_review.py evaluate --prepared private/neural-level-trial/review-01 --output private/neural-level-trial/review-01/evaluation.json
```

That unchanged evaluator scores EXP/Tesseract and arithmetic, **not neural levels**.
After freezing, a separate reference comparison must score `neural_level` per stream
from the saved log, retaining unknowns/abstentions and all denominators; do not read
its EXP/Tesseract triple metrics as neural validation. The viewer is a comparison
aid, not that accuracy evaluator. No frozen scoring implementation was modified.

## Changes, failures and next decision

Changed: `tools/shadow_capture.py`, `tools/shadow_rapidocr.py`; new bounded helper
`tools/shadow_neural.py`; `src/exp_tracker/shadow_view.py` and `web/shadow.js`;
`tests/test_shadow_neural_level.py`, existing capture tests and Node renderer tests;
capture/viewer documentation and this report. Existing worktree changes are preserved.

One initial synthetic assertion expected ValueError for a non-PNG; Pillow raises
OSError, already handled by the worker. The assertion now checks both supported
validation exceptions. Actual saved-crop replays had **zero worker failures/timeouts**.
No confidence/preprocessing tuning, grammar recovery, numerical reconstruction,
new dependencies/models, trusted writes, commits, pushes or deployment.

Next: conduct the new permitted trial and freeze genuinely new human references,
then compare the unchanged fixed neural level against them. In particular, high
confidence and model agreement must not validate 50/51 identities, crop completeness,
character identity or level transitions. This extension collects evidence only.

Validation: **210 focused Python tests passed; 935 full-suite tests passed, zero
skipped** (78.37s). All **10 Node renderer tests** and **six real Chrome cases**
passed, covering archived real rows, desktop/mobile, missing log, incomplete tail,
gaps/failures/stale samples and cached API failure. Screenshots/measurements remain
ignored under `artifacts/shadow-neural-level-browser/`; desktop rendering was visually
inspected. Two browser API requests measured 5.9/4.2ms, with about 1.08 MiB used V8
heap (not total browser RSS). There were no off-origin requests or page overflow.
CLI help, compilation, `git diff --check`, original receipt checks and private
artifact ignore checks passed. The preview server/browser were stopped afterward.
The complete report is copied to the requested local `.git/codex-output/latest.md`.
Linux/VPS operation, live acquisition and new-stream accuracy remain untested.

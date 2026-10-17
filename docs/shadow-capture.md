# Bounded shadow capture

`tools/shadow_capture.py` connects existing acquisition and experimental recognition
without importing the Store, choosing a character, or updating tracking/API/overlay
state. Every output has `trusted: false`. A complete candidate is not verified EXP.
No production modules, recognition parameters or frozen evidence were changed.

The optional [local shadow viewer](shadow-viewer.md) reads this existing JSONL
format and displays unverified evidence. It does not promote candidates or run OCR.

## Run locally

From the repository root, use the existing capture environment and private
RapidOCR environment/models. FFmpeg must be on PATH and Tesseract installed.
The runner does not install dependencies or download models. Defaults reference
`private/rapidocr/.venv` and `private/exp-consistency/requirements.json`.
Use `--ocr-python` and `--requirements` for alternate existing installations.
The neural worker requires the benchmarked RapidOCR **3.10.0**; this run used
ONNX Runtime **1.31.0**, CPU. Model hashes and runtime versions accompany results.

```powershell
# NEW output names required; existing results/crop directories are never overwritten.
.\.venv\Scripts\python tools/shadow_capture.py --file samples/sample-stream3.mp4 --start 991 --count 3 --output private/shadow-capture/offline-repeat.jsonl

# Replace NEW_CHANNEL with a channel whose streamer has permitted THIS trial.
.\.venv\Scripts\python tools/shadow_capture.py --channel NEW_CHANNEL --authorized --count 3 --output private/shadow-capture/live-trial.jsonl
```

Both use 15-second spacing. Optional `--save-crops` saves only native EXP (+2px)
and level crops next to the JSONL. Default saves no images. Output paths must be
under ignored `private/` or `artifacts/`, including after resolving symlinks.
No playback URLs, subprocess stderr, cookies or credentials are written. Only
channel login input is supported for Twitch; no arbitrary remote URLs or credentials.
`--authorized` records the operator's permission assertion, not platform approval.
Existing unofficial Streamlink restrictions in [live-capture.md](live-capture.md)
still apply. Access denial remains a failure; no bypass or browser launching.

## Fixed procedure and bounds

- Serial periodic `VideoSession` capture, using existing Streamlink/FFmpeg commands
  and keyframe decoding. Each connection is closed **before** recognition. No work
  queue, cached ROI, voting, neighboring-frame reuse or catch-up burst exists.
  Overruns skip elapsed schedule slots; local-file seeks advance with elapsed time.
- Default 3 attempts; count limited to 1–60, interval 5–300 seconds, capture wait
  1–30 seconds (default 20), plus existing bounded process/thread cleanup. One latest
  PNG buffer, existing 32 MiB/4096×2160 image limits, Streamlink 4 MiB ring buffer,
  one FFmpeg decoding/encoding thread. A stopped worker does not keep capturing.
- Fresh frames run unchanged `adaptive_hud.locate`. Zero/multiple returned layouts
  abstain. A unique returned layout does **not** establish main-feed/character
  identity or prove that the locator detected every secondary HUD. This remains an
  important limitation for multiple-feed layouts; no automatic identity assignment.
- Original source-pixel EXP crop gets fixed +2px bounded padding, then 2× bicubic
  direct-line RapidOCR. One isolated subprocess per crop: 1 MiB crop input limit,
  1024×256 native crop limit, 64 KiB result limit, default 10s subprocess timeout
  (maximum 30s), one intra/inter-op inference thread, existing local models only.
  Its one-shot initialization overhead is intentional for this small prototype.
- Unchanged strict complete-pair parser supplies `candidate`. Loose token diagnostics
  are retained separately and never rescue malformed punctuation/digits. Raw text,
  scores, model timings and all visual Tesseract attempts remain in JSONL.
- Visual Tesseract level and full nearest-half-up/truncation arithmetic level sets
  remain separate. Agreement, conflict, ambiguous sets, missing evidence and visual
  levels outside the supplied table are explicit. Arithmetic uses no visual level
  to select candidates. Table/build coverage and client rounding remain hypotheses;
  matching arithmetic is not independent numerical verification.
- Receipt age is checked before work and after each stage. Default maximum is 15s
  (configurable 1–30s). Expired completed diagnostics remain recorded but
  `current: false`, status `stale_local_frame`; no subsequent stage is started.
  Existing Tesseract calls each have a 10s timeout: locator has at most two calls,
  level reader at most six. A stage can overrun the age budget before it returns;
  this is not a hard real-time processing deadline or an OS-enforced RAM quota.
- Ctrl+C closes active/partially initialized captures and ends the run with a
  summary and exit 130. The neural subprocess is killed/waited by `subprocess.run`
  on timeout/interruption; normal completion returns 0 even when attempts failed.
  Inspect JSONL statuses, rather than treating exit 0 as successful recognition.

Freshness is **local decoder receipt-to-processing age only**. Frame PTS and the
age at the broadcaster/Twitch edge are unknown, explicitly recorded as such.
`requested_video_offset_seconds` is a seek request, not confirmed decoded PTS;
keyframe-only delivery can land later. Identical pixels can also be legitimate
unchanged gameplay or a frozen source; hashes permit review but do not prove
freshness. Keyframe decoding reduces CPU, not downloaded video bandwidth.

## Offline functionality check (not an accuracy benchmark)

`private/shadow-capture/offline-demo.jsonl` records three periodic captures from
the existing Stream 3 video, requested around 991, 1006 and 1021 seconds. No labels
were loaded, parameters tuned or observations promoted. Optional crops are in
`private/shadow-capture/offline-demo/`; no full frames were retained.

| Attempt | Strict diagnostic pair | Visual level | Nearest hypothesis | Receipt age at result |
|---|---|---:|---:|---:|
| 1 | 71,083 [24.16%] | 40 | unique 40 | 2.46s |
| 2 | 71,343 [24.25%] | 40 | unique 40 | 2.59s |
| 3 | 71,570 [24.33%] | 40 | unique 40 | 3.73s |

All three had one returned HUD and complete pairs/triples; no capture/recognition
failures. This familiar-video functionality check is neither new ground truth
nor independent-stream validation. Separate truncation sets are preserved.

Measured on this Windows workstation: 36.41s total including scheduled waits,
7.875 sampled process-tree CPU seconds, **192.35 MiB** sampled peak aggregate RSS.
Mean capture wait 3.039s, capture+close 3.045s, localization 1.276s, neural bridge
1.136s, visual level 0.495s; recognition total 2.916s and complete attempt 5.961s.
Neural import/model initialization averaged 0.749s, first inference 0.156s.
50ms process-tree sampling can miss short-lived CPU/peaks; measurements include
children but are not hard memory limits. `source_bytes` measures bytes relayed
from Streamlink, not total network traffic; it is zero for file capture.

Fifteen-second operation fit this three-attempt local run. Twitch startup latency,
bandwidth, denial/offline behavior, long trials, Linux/VPS performance and parallel
channels remain unmeasured here. No new livestream trial was run. Next: James can
run the short authorized command above and review crop identity, timestamps,
numerical outputs and resources before proposing any production acceptance policy.

## Tests and preservation

```powershell
.\.venv\Scripts\python -m pytest tests/test_shadow_capture.py -q -rs --basetemp private/shadow-capture/pytest-focused-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/shadow-capture/pytest-full-repeat
```

Synthetic tests cover missing/competing HUDs, fixed crop coordinates, malformed
pairs, zero ambiguity, contradictory/unsupported levels, rounding separation,
stale frames/results, capture/recognition failures, missed schedule slots,
bounded bridge input/output/timeouts, Ctrl+C cleanup and protected evidence paths.
Prior artifacts are fingerprinted in `private/shadow-capture/prior-input-hashes.json`.

Validation: **36 focused tests passed; full suite 718 passed, zero skipped**
(80.11s). Localhost tests used the permitted test environment. An initial test
parameter generated an overlong Windows environment-variable name; explicit short
test IDs fixed that test-harness issue. Final tests have no failures. Compilation,
CLI help and `git diff --check` pass; all **1,164** fingerprinted prior artifacts
remain byte-identical. No new dependencies, downloads, commits or pushes.

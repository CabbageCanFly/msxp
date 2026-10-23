# Real OCR → SQLite verification and profile setup

Historical integration results below used schema 1's pause policy. The later
[short OCR interruption change](accounting.md) now counts **6,121 EXP**, including
two explicitly marked bridged intervals. Existing saved rows retain their original
outcomes/gains; reproduce the new policy in a fresh dedicated replay database.

This verifies the existing SQLite milestone on saved private evidence. No new
Twitch footage was collected; no OCR thresholds, glyph algorithms or tracking
policy changed. The worktree started clean at `ba001c2`.

## Verified results

Replaying `green-test-20261015-215403` through actual Pillow/Tesseract/pixel OCR,
the shared guard and `Store.ingest` produced:

| Outcome | Count |
| --- | ---: |
| Accepted continuous observations | 11 |
| Trusted baselines | 3 |
| Diagnostic rejections | 3 |

All 14 trusted readings match the previously reviewed recorded values. This is
regression evidence on the existing dataset, not a new accuracy estimate. Last
trusted state is **level 60 / EXP 879,217 / 72.66%**. The final rejected frame
leaves it paused, without replacing the trusted value or timestamp. Closing and
reopening SQLite after every frame preserves the selected character, session,
state and observed gains. Replaying the CLI again returns duplicates; the database
still has 17 attempts and one session.

A real negative control uses original screenshot 1 with the current v2 profile:
pixel EXP matching fails, while Tesseract reports accepted **71,441 / 5.90%** at
score 0.52. SQLite rejects it as `unverified_tesseract_exp`, both before any baseline
and after a trusted reading. Diagnostic candidates do not become trusted columns.

The actual capture CLI was also exercised with explicit `--glyph-profile` and
`--database`: a saved HUD frame was reconstructed from crops, encoded as a local
lossless FFV1 clip and decoded by FFmpeg. Real OCR persisted **60 / 873,096 /
72.16%**, then a reopened store restored it. No OCR, frame transport or database
was mocked in that test. It does not verify new Twitch/network behavior.

## Changes needed

- Extend `tools/replay_capture_crops.py` with explicit profile and optional SQLite
  ingestion. Stored numeric answers are never reused as recognition output.
- Restore only fields actually saved. An early level failure legitimately has
  no EXP crop. Capture/processing failures without crops remain diagnostic.
- Add `tracking start/end --at` for historical replay sessions. Original receipt
  timestamps are retained; historical observations must not be made to look fresh.
- Report `glyph_profile_required` or `invalid_glyph_profile` clearly from database
  capture setup, before opening video capture or creating a database.
- Create `artifacts/` in fresh-install instructions before pytest `--basetemp`.

The original trust gate, SQLite schema, transition policy and OCR calibration
remain unchanged. Replay event IDs use recorded event IDs when available,
otherwise a hash of the immutable capture JSONL plus frame index. Reuse the same
file, profile and OCR version for idempotent reruns; use a separate replay database
when experimenting with changed recognition output. Nothing was committed/pushed.

## Run the complete saved-data pipeline locally

From the project root, with the existing private captures/profile and installed
dependencies/Tesseract. These commands use a **dedicated replay database**, never
your live tracking history. The recorded session begins at the explicit original
UTC timestamp. On a new database the character ID below is 1; otherwise use the
ID returned by `character`.

```powershell
.\.venv\Scripts\python -m exp_tracker.tracking --db artifacts/ocr-integration.sqlite3 --channel streamer_a init
.\.venv\Scripts\python -m exp_tracker.tracking --db artifacts/ocr-integration.sqlite3 --channel streamer_a character "Saved trial character"
.\.venv\Scripts\python -m exp_tracker.tracking --db artifacts/ocr-integration.sqlite3 --channel streamer_a select 1
.\.venv\Scripts\python -m exp_tracker.tracking --db artifacts/ocr-integration.sqlite3 --channel streamer_a start --at 2026-10-16T01:54:04Z
.\.venv\Scripts\python tools/replay_capture_crops.py artifacts/green-test-20261015-215403.jsonl artifacts/green-test-20261015-215403 --glyph-profile private/ocr-evaluation/glyph-profile-green-experimental.json --database artifacts/ocr-integration.sqlite3 --tracking-channel streamer_a
.\.venv\Scripts\python -m exp_tracker.tracking --db artifacts/ocr-integration.sqlite3 --channel streamer_a state
```

These exact commands were run. Historical state is correctly stale now. Rerunning
the replay with unchanged evidence does not add rows or gains. For ordinary
capture, the existing CLI still takes `--glyph-profile PATH --database PATH`
with an explicitly selected/open database session; no profile path is auto-found
or stored for future worker invocations. Pass it again after restart.

## Public checkout and a new v2 installation

No game-font profile, screenshots or annotations ship publicly. Existing public
tests construct synthetic seven-segment glyphs and train v1/v2 profiles in temporary
directories; these fixtures are not compatible game fonts. A clean installation
can run the synthetic SQLite demo and public tests without private materials.

Follow the README's normal `pip install -e '.[dev]'`. Install the optional capture
extra and FFmpeg for capture tests, and Tesseract for OCR. On Windows create the
pytest parent first: `New-Item -ItemType Directory -Force artifacts | Out-Null`.
On Linux use `mkdir -p artifacts` and `.venv/bin/python`.

For actual game tracking:

1. Obtain permitted **RGB** HUD crops at the intended resolution/UI scale. Color
   is necessary for green-excess calibration. Label development glyphs manually;
   reserve separate-session crops for evaluation.
2. Store images and annotation JSON under ignored `private/calibration/`.
   Use `version: 2`, `bracket_mode: "green_excess"`, and the measured glyph cell
   origins/advances. Cover all digits and `, [ . % ]`. See the complete annotation
   format in [OCR consolidation](ocr-consolidation.md#reproducible-calibration-and-a-new-installation).
3. Generate a local model:

   ```powershell
   .\.venv\Scripts\python tools/train_glyph_profile.py private/calibration/training.json private/calibration/glyph-profile-v2.json
   ```

4. Inspect consented screenshots with normalized ROIs and `--glyph-profile`.
   Require accepted **pixel** EXP evidence, not merely an accepted Tesseract
   candidate. Calibrate ROIs for the actual layout; the supplied streamer_a config
   only matches the existing saved layout. Do not weaken thresholds for coverage.
5. Select a character/start a session and pass the model explicitly to capture.
   Missing, inaccessible, incompatible-version or incomplete profiles fail setup.
   Store ingestion without a profile remains diagnostic, never trusted.

The existing private experimental model was not overwritten. Its reproducible
annotations/model and every private crop/database remain ignored by Git. A
calibrated model still needs independent evaluation; JSON validity is not proof
of accuracy. There is no automatic clean-install game calibration or cleared
redistributable game profile yet.

## Accounting review and overlay blockers

The current pause policy is conservative but undercounts short OCR interruptions.
This trial has **6,121 EXP** net change between first/last trusted endpoints, but
reports **4,529 observed session EXP**. Rebaselining after frames 3 and 6 excludes
**738 + 854 = 1,592 EXP**. That is a policy effect, not failed persistence.

Recommendation for a later small change: count net change between two trusted
same-session, explicitly selected same-character, same-level, nondecreasing
endpoints across isolated OCR failures within the existing 120-second gap limit.
Mark the interval as containing missing observations; do not invent intermediate
values or claim continuous rate coverage. Keep offline, explicit pauses/switches,
ambiguous resets/levels and longer gaps as hard continuity breaks. Endpoint
subtraction is observed net change, but cannot prove character identity or timing
inside the gap. **No accounting-policy change was made here.**

A supervised read-only overlay can use the current trusted value, observed gain,
pause reason and age. Fully automatic operation still has these blockers:

- Character selection/switching must be explicit; same-level switches cannot be
  inferred from HUD numbers. Configuration must expose selection clearly.
- Level changes remain ambiguous and keep the old trusted state until explicit
  rebaselining (`end`, then `start`). A confirmation workflow is needed for smooth
  level-ups; exact cross-level totals still require verified game data.
- New installations require operator calibration or a cleared distributable font
  profile. Rates/ETA are deferred. Freshness is local decoder receipt, not verified
  broadcast age; an overlay must show stale/paused state honestly.

No API, frontend, scheduler, deployment or new live capture is included.

## Validation boundary

- Targeted integration/setup tests: **16 passed**.
- Full local suite: **254 passed, zero skipped**, including 74 sample-marked tests.
- Public-file export with no private images/profiles/annotations: **181 passed,
  73 expected private-data skips**, using the already installed development/OCR
  dependencies. The core subset (`not ocr and not samples`) passed **179 tests**,
  with 75 deselected; that subset does not require Tesseract or private fixtures.
- The source checkout works without game assets. A cold dependency installation
  and wheel build were **not verified**: this session lacks `setuptools.build_meta`
  and package downloads are restricted. `pyproject.toml` already declares that
  build dependency; ordinary pip build isolation should install it when network
  access is available. No backend was vendored or dependency policy changed.
- Linux execution, new Twitch capture, public deployment authorization and
  broader font/scale accuracy remain outside this verification.

```powershell
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-ocr-persistence-full
```

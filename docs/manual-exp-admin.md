# Checkpoint A1: local Level / EXP corrections

Use the local CLI against an explicitly selected channel/character. There is no
HTTP write endpoint or operator dashboard. Nothing captures video or calls Twitch.
Run in the repository's Python environment, from the repository root:

```powershell
$db = 'private/offline-test/tracker.sqlite3' # choose the intended database
python -m exp_tracker.manual_admin --db $db --channel alpha inspect
python -m exp_tracker.manual_admin --db $db --channel alpha set --character 'Main' --level 64 --exp 749000 --percentage 50.00 --reason 'Corrected HUD reading'
python -m exp_tracker.manual_admin --db $db --channel alpha history
# A new set supersedes the previous override; omitted EXP/percentage stay unknown.
python -m exp_tracker.manual_admin --db $db --channel alpha set --character 'Main' --level 65
python -m exp_tracker.manual_admin --db $db --channel alpha clear --character 'Main' --reason 'Resume OCR'
```

`inspect` shows character IDs/labels, selection, session, current public reading,
level provenance and latest applicable correction. `history` includes all of this
channel's correction events, including clears and earlier character/session scopes.
Both commands are read-only and do not migrate the database. The database must
already exist; use the existing explicit channel/character/session setup first.

Level is **1..200**, EXP is an optional nonnegative SQLite integer (up to
9,223,372,036,854,775,807), and percentage is **0.00..99.99**, with at most two
decimal places. At least one value is required. Zero is a supplied value.
Omitted fields remain SQL NULL; a percentage-derived EXP estimate stays separate
from an entered integer. Neither a missing percentage nor EXP is backfilled from
an older OCR reading. If level is omitted, the usual last-known supported level
may still provide display context. Inconsistent operator-entered pairs are preserved as manual
information; community-table arithmetic does not authenticate them.

The default effective time is the current UTC time. Optionally supply
`--effective-at '2026-10-19T16:30:00Z'` (or an explicit offset). Naive, future,
pre-session and non-increasing effective timestamps in the same character/session
scope are rejected. Backdated corrections reproject history causally at that time;
newer eligible OCR may already have resumed by the time of submission. For an
idempotent retry, use the same `--event-id NAME` and identical values, reason and
effective time. Reusing an ID with different contents is rejected.

## Precedence and accounting

- Each set replaces the previous manual override in its entirety. It takes effect
  without another capture. Older OCR, delayed delivery of a pre-correction frame,
  and EXP-derived levels cannot immediately overwrite supplied values.
- A subsequent fresh, ordered, public-eligible OCR reading resumes the numeric
  pair together. It must pass the existing source/percentage checks and have no
  arithmetic contradiction. A percentage-only observation can resume with unknown
  integer EXP; it does not pair new percentages with the old manual integer.
  Duplicate source frames in the causal context do not release the override.
- A manual level supplies labeled context for **subsequent** fresh observations
  when readers are unavailable or weak. Reader agreement or the existing confirmed
  neural-reader policy releases it. A weaker inferred level cannot displace it.
  This context never establishes character identity, modifies raw reader results,
  or retroactively validates observations acquired before the correction.
- Every set and clear separates accounting segments. Manual coordinates themselves
  never become endpoints. Recent 5/10/15/30/60-minute and 24-hour totals retain valid
  OCR intervals on either side, excluding the cross-boundary difference. Rates use
  the sum of those observed spans, excluding the correction gap. A lone reading
  after the edit supplies a new baseline, not progress. Unknown level requirements
  and transitions remain unavailable; no missing progress is invented.
- Clear appends an event, removes the override and waits for fresh OCR rather than
  resurrecting an older overridden display. It preserves old accounting boundaries.
  Sets/clears also discard pre-correction current ETA estimates. A partial new
  override leaves omitted numeric fields unknown. Earlier valid historical gains
  and dated history remain inspectable.
- Events bind to the selected character and currently open session, or to no
  session when none is open. They never carry into another session, even when
  returning to the same character. A correction outside a session applies only
  until a new session starts. Explicit selection, never level/EXP, determines ownership.

SQLite schema **5** adds only `manual_corrections`, its index and append-only
triggers. Set/clear commands migrate earlier supported schemas transactionally.
Readers still support schemas 3 and 4. Prior observations/diagnostic attempts and
tracking state are not rewritten. Trusted ingestion establishes a new OCR baseline
after a correction instead of crediting the adjusted EXP. Trusted SQLite totals
remain separate from public experimental history.

The homepage, character page and experimental `/live/overlay/CHANNEL` share the
corrected player projection. Hover level/EXP/percentage for provenance; player APIs
include `manual_correction`, and Advanced diagnostic snapshots include the event
log and per-reading correction context. Treat reasons as public diagnostic text.
The original trusted `/overlay/CHANNEL` continues to show trusted OCR only.

A correction ID participates in the publisher revision, card cache, recent/24-hour
checkpoints, historical ETA cache and browser history revision. The background
publisher discovers external CLI writes on its normal idle poll (about one second,
plus pending builds); browsers poll every two seconds. No new frame is required.

## Limits and validation

Deploy this code before using schema 5 with a running process: older code may reject
that schema. Upgrading an existing operator installation requires its normal
controlled code rollout; A1 does not restart coordinators or migrate active data
on the operator's behalf. No live capture, identity detection, locking an override
forever, inferred manual level-ups, or A2 browser administration is included.
Level context/release follows the bounded causal OCR replay; operators can explicitly
clear a correction to stop supplying context. EXP requirements remain provisional.

Regression tests use fresh/migrated isolated databases and synthetic attempts:
`tests/test_manual_admin.py`, together with persistence, projection, publisher,
history and frontend suites. They cover restart, partial/zero values, delayed and
out-of-order OCR, duplicates, level and numeric boundaries, character/session
isolation, cache invalidation and unchanged raw/trusted evidence.

Final offline verification in this worktree:

- **2,080 Python tests passed**, **117 private-fixture skips**, **one Windows
  symlink-permission skip**; **95 Node tests passed**, zero skips. The correction
  module contributes 46 synthetic regression cases. Full Python output:
  `private/manual-a1/python-full-final.txt`; Node output:
  `private/manual-a1/node-full-final.txt`. `git diff --check` passed.
- Actual headless Chrome rendered the homepage, desktop/mobile character page,
  and transparent 500 x 160 overlay against a synthetic database. Two CLI writes
  appeared through polling with one navigation per page and no capture: an entered
  zero with missing percentage, then a complete correction. No artificial gains,
  browser exceptions or external requests were observed. Screenshots and the
  receipt are under `private/manual-a1/browser-final/` (ignored).
- Inspect the retained synthetic example without touching active tracking:

  ```powershell
  $env:PYTHONPATH = "$PWD\src"
  & ..\msclassic-twitch-exp-tracker\.venv\Scripts\python.exe -m exp_tracker.manual_admin --db private/manual-a1/preview.sqlite3 --channel manual_demo inspect
  # Substitute history for inspect to view the appended preview events.
  ```

The existing adjacent virtual environment supplied test dependencies; its Python
import path was set to this worktree's `src`. No dependency installation was needed.
No active tracking database was opened or changed, no coordinator was restarted,
and no Twitch connection, deployment, push or live OCR trial was performed.

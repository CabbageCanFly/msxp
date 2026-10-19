# Manual Level / EXP administration (A1)

Local CLI only. There are no HTTP write endpoints or browser administration forms.
Commands neither capture video nor contact Twitch. Run from this worktree with its
Python environment; set `PYTHONPATH=src` when using an interpreter from elsewhere.
The database must already exist. Do not use an active database for offline trials.

## Required input and inspection

Every new `set`, `correct` or `amend` requires the **existing character name**,
**level 1..200**, and **numerical EXP and/or percentage**. EXP is a nonnegative
SQLite integer, up to 9,223,372,036,854,775,807; percentage is 0.00..99.99 with at
most two decimals. Zero counts as supplied. Channel is always explicit.

Every such operation, and `clear`, requires exactly one of:

- `--effective-at '2026-10-19T16:30:00Z'`: complete year/month/day and
  hour/minute/second, optional microseconds, plus `Z` or an explicit `+/-HH:MM` offset.
- `--now`: the operator deliberately chooses the current UTC timestamp.

There is **no implicit current time**. Missing timestamps, timestamps without
seconds/timezone, future timestamps, and using both options are rejected. The
backend likewise requires an aware datetime or explicit `now=True`, exclusively.
This is also the contract for A2's future form: manual datetime entry by default,
with an explicit current-time choice. A2 itself is not included.

```powershell
$db = 'private/offline-test/tracker.sqlite3'
python -m exp_tracker.manual_admin --db $db --channel telfer1 inspect
python -m exp_tracker.manual_admin --db $db --channel telfer1 inspect --character 'Tricia' --session 7
python -m exp_tracker.manual_admin --db $db --channel telfer1 history
python -m exp_tracker.manual_admin --db $db --channel telfer1 history --correction-id 12
```

`inspect` returns character IDs/names, session choices, exact UTC reading timestamps
and identities, original OCR values and corrected presentation. Diagnostic identities
are `RUN_ID:ATTEMPT_INDEX`; trusted SQLite observations use their integer ID.
`history` returns correction events and rename audit records, including effective
and recorded times, reasons, `replaces_id`, `superseded_by` and `active` status.
Inspection/history are read-only, including on older schemas.

## Baseline versus historical reading

`set` establishes a baseline. Character/session ownership comes from the database,
not level/EXP arithmetic. `--session` explicitly targets an existing session;
otherwise effective time must identify a unique session for that character. Shared
session-end/start instants can be ambiguous and require `--session`. Out-of-session
timestamps require explicit `--no-session` when that character has sessions;
this creates an unbound baseline, useful between captures, that does not carry into
a new session. A character with no sessions can have an unbound baseline directly.
Older characters and closed sessions are supported without changing live selection.

```powershell
# Preview the complete write on a disposable snapshot; source SQLite is not migrated.
python -m exp_tracker.manual_admin --db $db --channel telfer1 set --character 'Tricia' --level 42 --percentage 99.40 --now --dry-run
python -m exp_tracker.manual_admin --db $db --channel telfer1 set --character 'Tricia' --level 42 --percentage 99.40 --now --reason 'Known starting level'
```

`correct` changes one historical point's **presentation**, retaining the original
OCR row and identity. Use a reading ID plus its exact original timestamp, or omit
the ID and resolve by exact timestamp and character/session scope. More than one
matching source reading is rejected; specify its identity. Use the timestamp from
`inspect`, including its fractional seconds. `--now` cannot retime an old reading.

```powershell
# Replace RUN_UUID:2 and the timestamp with the values printed by inspect.
python -m exp_tracker.manual_admin --db $db --channel telfer1 correct --character 'Tricia' --session 7 --reading 'RUN_UUID:2' --level 49 --exp 12345 --percentage 2.10 --effective-at '2026-10-19T15:20:30.123456Z' --reason 'Level was 49, not 50'
# Alternatively use --observation-id 123 for a trusted SQLite OCR observation.
```

A point correction does not seed adjacent level inference, authenticate identity,
or edit adjacent OCR. It blocks accounting into, out of, and across that point.
The corrected point is visible in public percentage history and Advanced session
views with manual provenance; newer valid readings retain the current live display.
Trusted-observation corrections have a separate manual presentation; the original
trusted OCR state and trusted overlay remain explicitly original OCR.

## Amend, undo and clear

Effective timestamps need **not** arrive in chronological order. At equal effective
times, the later recorded active baseline wins. `amend` supplies a complete
replacement, with required character, level, EXP/percentage, explicit time choice
and reason. It can move a correction to another time, session or character in the
same channel. Point amendments identify the replacement point at that time.

```powershell
python -m exp_tracker.manual_admin --db $db --channel telfer1 amend --correction-id 12 --character 'Tricia' --session 7 --level 49 --exp 12345 --effective-at '2026-10-19T15:20:00Z' --reason 'Correct earlier level/time' --dry-run
python -m exp_tracker.manual_admin --db $db --channel telfer1 undo --correction-id 13 --reason 'Entry was applied to the wrong character'
python -m exp_tracker.manual_admin --db $db --channel telfer1 clear --character 'Tricia' --now --reason 'Stop supplying manual context'
```

`undo` retracts an active revision and its superseded lineage; it does not revive an
older manual mistake. It inherits that revision's effective time and records the
actual retraction time. To restore operator information, submit a new set/correct.
Already superseded/retracted IDs are rejected with an inspection hint. Older active
corrections remain amendable even when newer independent corrections exist.

`clear` is a new time-scoped boundary that stops the baseline context from that
time forward and waits for fresh OCR. It preserves prior corrections/history.
`undo` removes that revision's projection and accounting boundaries, restoring the
underlying original OCR projection where no other active correction applies.

All mutations support `--dry-run`. Corrections/undo accept a stable `--event-id`
for retries: the same ID/content is idempotent; conflicting reuse is rejected.
Undo and amend require a reason. Treat reasons as public diagnostic text.

## Derived coordinates, precedence and EXP accounting

- Supplied fields remain nullable independently in SQLite. Numerical-only input
  derives an **estimated** displayed percentage when the provisional requirement
  is supported and EXP is below that requirement. This display uses truncation and
  is marked `~`; its `estimated_percentage` metadata records the source/requirement.
- Percentage-only input keeps `exp=null` and supplies a separately labeled
  `estimated_exp` when possible. It is never relabeled as an entered integer.
  Disputed/missing requirements leave conversions unavailable.
- When both values are entered, both are preserved. Existing arithmetic checks
  flag contradictions in `exp_validity`; tooltips explain them. Neither value is
  silently repaired or promoted to trusted OCR. Historical schema-5 partial events
  remain readable; the stricter contract applies only to new set/amend writes.
- A baseline immediately overrides older/delayed frames. Fresh ordered eligible
  OCR resumes the numeric pair together; an old manual integer is not paired with
  a new OCR percentage. Weak/conflicting evidence cannot immediately replace a
  manual level. Existing reader confirmation can release it, and the existing
  EXP-derived transition machinery can advance it after a corroborated adjacent
  level-up or its existing multi-frame forward confirmation. Manual seed provenance
  remains inspectable. No character-name OCR or new OCR acceptance policy is added.
- Manual coordinates never become earned-EXP endpoints. Each set/clear and each
  corrected point separates accounting segments. Valid OCR intervals on either
  side remain; correction deltas and unknown transitions supply no gain. The first
  fresh OCR after a boundary is a baseline, not earned progress from a manual entry.
  Rates use summed observed spans, excluding correction gaps. Observed losses still
  reduce net gain. Different characters/sessions never supply a connecting gain;
  5/10/15/30/60-minute and 24-hour totals sum their independent eligible spans.
- Append-only amendments/retractions are resolved before ownership/time filtering,
  so moving a correction to another character actually removes its old effect.
  Publisher revisions include every audit event and rename. Card, historical ETA,
  recent/24-hour checkpoints and browser histories refresh without another frame.
  The background publisher polls about once per second plus pending builds; browser
  polling is every two seconds. Corrections are local SQLite transactions.

Schema **6** additively extends schema 5 with correction kinds, replacement links,
retractions, stricter new-insert validation and rename audit history. Existing raw
observations/attempts are preserved. Read-only operation supports schemas 3–6.
Deploy updated serving/writer code before migrating an operator installation;
older processes can reject the new schema. No active installation is upgraded here.

## Rename a character without changing its identity

```powershell
python -m exp_tracker.manual_admin --db $db --channel telfer1 rename --character-id 7 --new-name 'Tricia' --reason 'Replace Main placeholder' --dry-run
python -m exp_tracker.manual_admin --db $db --channel telfer1 rename --character-id 7 --new-name 'Tricia' --reason 'Replace Main placeholder'
```

Rename updates the existing label, audits old/new names and invalidates publication.
It preserves the character ID, sessions, OCR, manual events and EXP history. Duplicate
channel labels, controls, empty names and outer whitespace are rejected.

**Coordinate the roster before the next startup.** `multi_alpha.py` and
`stream_roster.py` validate JSON character labels against the selected database
character. For a configured assignment, perform this workflow at a controlled pause:

1. Stop your coordinator normally in its own terminal when you choose; this CLI
   never stops/restarts it or edits its configuration.
2. Preview/apply the database rename. In the matching private roster JSON, change
   only that channel's `character` string from `Main` to `Tricia`, retaining its
   source, authorization, enabled flag and other settings. Do not add a character
   or remove/re-add the roster assignment. The two files are not one atomic transaction.
3. Run `python tools/stream_roster.py --config YOUR_ROSTER.json list`, then your
   normal coordinator `--check` before restarting. A stale label is a hard, explicit
   mismatch, not an automatic reassignment. If interrupted between the two edits,
   keep capture stopped and reconcile the labels before starting.

## Verification and remaining limits

Tests use isolated synthetic databases, saved-fixture skips and read-only previews.
No active tracking database, coordinator, Twitch connection or other worktree is
modified. No commit, merge, push or deployment is performed. Preview snapshots use
the OS temporary directory and are deleted after validation.

Final verification in this worktree: **2,119 Python passes**, **117 unavailable
private-fixture skips**, **one Windows symlink-permission skip**; **97 Node passes**,
zero Node skips. Focused regressions cover the operator contract, historical
revisions, inference, isolation and coordinated renaming. `git diff --check` passed.
Logs are ignored under
`private/manual-revision/` (`python-review-final.txt`, `node-full-final.txt`).

Headless Chrome verified a historical point correction, its amendment and undo,
original OCR preservation, explicit `--now`, estimated percentage labels, rename
preview/apply, and automatic homepage/character/overlay updates with one navigation
per page. Desktop, mobile and transparent 500 x 160 overlay screenshots and the
no-external-request/no-console-error receipt are under
`private/manual-revision/browser-evidence/`. Its synthetic database remains available
for local, read-only inspection; the preview server has stopped:

```powershell
$env:PYTHONPATH = "$PWD\src"
& ..\msclassic-twitch-exp-tracker\.venv\Scripts\python.exe -m exp_tracker.manual_admin --db private/manual-revision/browser.sqlite3 --channel alpha inspect
& ..\msclassic-twitch-exp-tracker\.venv\Scripts\python.exe -m exp_tracker.manual_admin --db private/manual-revision/browser.sqlite3 --channel alpha history
```

The adjacent existing interpreter supplied dependencies read-only; bytecode writes
were disabled and imports targeted this worktree's `src`. No dependencies were added.

Known limits: point targeting uses exact source timestamps/identities, not fuzzy
time matching; manual coordinates are excluded from earned-EXP endpoints; requirement
data remains provisional; native HUD availability and bounded causal inference can
delay a level-up. Naming is manual. A2 forms/authentication, live OCR validation and
automatic roster/coordinator reconfiguration are outside this milestone.

# Manual Level / EXP administration (A1 / A2)

The CLI and separate local browser dashboard share A1.1's SQLite correction rules.
The public server remains read-only. Neither interface captures video or contacts
Twitch. Run from this worktree with its
Python environment; set `PYTHONPATH=src` when using an interpreter from elsewhere.
The database must already exist. Do not use an active database for offline trials.

## Local browser dashboard (A2)

```powershell
$env:PYTHONPATH = "$PWD\src"
$db = 'private/offline-test/tracker.sqlite3' # Existing offline/synthetic database
python -m exp_tracker.admin_server --db $db --port 8766
# Open the exact URL printed by the command: http://127.0.0.1:8766/
# Ctrl+C stops only this operator server.
```

This is a separate process and port from the read-only tracker server. Starting it
only reads/validates the named database; it does not initialize or migrate it. A
confirmed save opens the existing writer and can apply A1.1's additive migration;
update any serving/writer installation before deliberately using an older database.
No new schema migration is needed for A2. Nothing starts, stops or reconfigures the
coordinator. Use a deliberate database path; the dashboard displays its absolute path.

1. Select a Twitch channel and existing character. Session view includes closed
   sessions and historical characters; selection does not switch live tracking.
   Latest level/EXP/percentage/source, original readings, correction revisions and
   rename history are shown. Use **Refresh readings and history** for new OCR or
   external CLI changes; the operator page does not poll while you edit.
2. **Establish baseline** requires level and numerical EXP and/or percentage. Enter
   the complete timestamp with seconds and timezone. Manual entry starts blank;
   **Use current timestamp** starts unchecked. That explicit choice freezes the
   current UTC time **at preview**, so saving never silently changes the reviewed
   effective time. Session scope can resolve from time, name an existing session,
   or explicitly choose an unbound baseline.
3. **Correct historical reading**: choose a session and a reading's **Correct**
   button. It fills the immutable identity, type and exact original timestamp.
   Enter corrected values and preview. For readings outside the bounded list,
   enter the original identity/time from CLI inspection or Advanced diagnostics.
   Both identity and timestamp are required in the browser contract.
4. History's **Amend** and **Undo** buttons target the exact correction ID.
   Amendment supplies a complete replacement and requires a reason. Undo requires
   a reason and retracts that revision/lineage; it does not restore superseded
   manual entries. To move an amendment to another character in the same channel,
   select the destination character, choose Amend, and explicitly enter the previous
   correction ID and the complete replacement scope/values. **Clear baseline from an
   effective time** creates a new boundary; undo a point correction to remove it.
5. **Rename this character** previews old/new names and the unchanged character ID.
   Follow the coordinated roster workflow below before the next coordinator startup.
6. **Preview changes** runs the real operation on a disposable SQLite backup. Review
   supplied/estimated values, arithmetic warnings, scope, reason and audit provenance,
   then **Confirm and save**. Editing any field or selection cancels the preview.
   Cancel makes no source write. Preview row IDs/recorded times are provisional;
   the saved receipt gives the real IDs and recorded time. Contradictory EXP and
   percentage remain allowed with an explicit arithmetic warning, as in A1.1.

The server retains at most 64 previews for 15 minutes; stopping it discards them.
Save accepts only a preview ID and re-runs Store validation, including active
revision and ownership checks. A renamed target requires a fresh preview. Retrying
the same successfully saved preview returns its receipt rather than writing twice.
Continuous OCR can arrive between preview/save: preview confirms the exact operator
event, not a frozen public projection. Existing precedence/accounting remains in
force, and fresh credible OCR can resume tracking after the effective time.

The listener is **always IPv4 `127.0.0.1`**, with no configurable host. It accepts
only the exact Host/port printed at startup, rejects cross-site requests, requires
an exact same-origin Origin for POST, and requires a random process-local request
token for all API reads/writes. The same-origin page supplies this token; there is
no CORS, cookie authentication, URL token or remotely accessible write route.
JSON writes are size-bounded, reject duplicate/unknown fields, and cannot bypass
preview. Responses are uncached, scripts are local, and framing is prohibited.
Opening `localhost` instead of the printed `127.0.0.1` URL is intentionally rejected.

This trusts processes/users on the operator's machine; it is not multi-user login
or protection against a compromised local account. Do not expose this port through
a proxy, tunnel, port forward, OBS browser source or public hosting. The public
server does not serve admin assets or gain any write endpoints. Keep serving public
pages from its existing port. Numerical EXP crosses the dashboard JSON boundary as
decimal strings so integers up to SQLite's limit retain their exact value.

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
The A2 form uses the same contract: manual datetime entry by default,
with an explicit current-time choice.

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

A1.1 verification: **2,119 Python passes**, **117 unavailable
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

The figures above describe A1.1 verification. A2 adds **55 operator API tests**;
the focused admin/manual/publisher run passed **163 tests**, with **3 private-fixture
skips**. The full Python suite passed **2,174 tests**, with **117 private-fixture
skips and one Windows symlink-permission skip**. All **97 Node tests** passed.
An existing OCR test now copies its cached fixture before deliberately mutating it,
removing test-order pollution without changing production OCR policy. Logs are under
`private/admin-a2/` (`python-focused-final.txt`, `python-review-final.txt`,
`node-full.txt`). The real Chrome workflow verifies desktop/mobile layout, original
OCR preservation, exact preview timestamps, public cache refresh and unchanged
tracked EXP. The final synthetic database, desktop/mobile screenshots and browser
receipt are under `private/admin-a2/browser-verified/`; its test servers have stopped.
The browser also checks that a successful save retains its receipt and reports a
subsequent refresh failure, so a read failure does not masquerade as a failed write.
To reproduce
the browser check with Python dependencies and Chrome already installed:

```powershell
node tools/admin.browser.mjs --python python --output private/admin-browser-review
# Optional: --chrome 'C:/Program Files/Google/Chrome/Application/chrome.exe'
```

This creates a **new** synthetic SQLite database, separate ephemeral operator/public
servers, and a private Chrome profile. It refuses an existing synthetic database.
It exercises preview, explicit-time validation, baseline creation, historical point
correction, amendment, undo, clear, rename, character/channel isolation and automatic
homepage/character/overlay publication without captured frames. Screenshots and a
JSON verification receipt stay under the ignored output directory; owned test
processes stop on completion. It requires a Node runtime with the built-in WebSocket
API (verified with Node 24), Chrome and permission to use local loopback sockets.
No packages, Twitch or private samples are needed.

Known limits: point targeting uses exact source timestamps/identities, not fuzzy
time matching; manual coordinates are excluded from earned-EXP endpoints; requirement
data remains provisional; native HUD availability and bounded causal inference can
delay a level-up. Naming is manual. Browser lists are bounded to recent readings
within the chosen session; this is not an unrestricted history search. Preview
copies the SQLite database into the OS temporary directory and can be slow for a
large database. Preview tickets and save receipts are held only in server memory;
after a server restart or an uncertain network result, inspect audit history before
submitting another operation. Live OCR validation, remote/multi-user administration
and automatic roster/coordinator reconfiguration are outside this milestone.

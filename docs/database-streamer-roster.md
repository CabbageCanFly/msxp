# Database-managed Twitch streamers

The existing coordinator now supports a database-owned roster and live reconciliation.
After a **one-time reviewed bootstrap and controlled restart**, open the existing
loopback admin portal's **Streamers** area to add, pause, resume, configure or hide
channels. Routine changes need neither JSON edits nor coordinator restarts. A new
streamer needs only a Twitch login; no MapleStory character name is required.

No command in this guide has been run against the user's database during development.
Do not run modifying or live steps until review and operator authorization. Never
start a second coordinator against the running tracker's database or log root.

## Architecture and safety

Schema **11** adds `streamer_capture` (desired settings and new-character identity
state), `streamer_roster_events` (configuration audit), `streamer_runtime` (observed
status/heartbeat), and `streamer_roster_bootstrap` (one-time import receipt). Existing
streamer/character IDs, selections, sessions, history, corrections, invalidations,
level guards, adoption receipts and daily statuses are preserved. No tables are
rebuilt. Existing schema-10 protected capture/repair paths remain supported.

Existing databases do **not** automatically migrate to schema 11 when opened for
writing. Ordinary `Store` opens (including `allow_migration=True`), admin corrections
and renames, JSON capture/replay, tracking/retention CLIs, standalone capture tools,
and adoption/floor-repair rehearsals stop at schema 10. Older supported schemas may
still receive their existing additive migrations through 10. Fresh empty databases
initialize at 11, and already-schema-11 databases remain writable; neither case
implicitly bootstraps a roster. For an existing database, only the explicit roster
bootstrap below applies migration 11, with its reviewed fingerprint, ownership lease,
confirmation, verified backup and atomic rollback boundary.

Writable entry points audited for this boundary:

- `manual_admin.writable_store` (also used by the admin portal), tracking CLI,
  diagnostic replay CLI and retention `--apply`: ordinary Store writers.
- `capture.py`, `tools/shadow_capture.py`, `tools/replay_capture_crops.py`,
  `tools/local_alpha.py` and JSON-mode `tools/multi_alpha.py` (initialization,
  capture and replay): ordinary writers, or the existing stricter no-migration mode.
- Automatic-adoption and floor-repair previews: ordinary writers on disposable
  snapshots; their apply paths explicitly preserve schema 10/11 and never apply 11.
- Demo, fixture and benchmark tools: ordinary writers, normally on fresh data.
- Roster preview: ordinary snapshot writer followed by explicit `bootstrap_change`;
  roster apply: read-only Store opened before taking the exclusive write transaction,
  then explicit migration after the backup checks. Public HTTP/publisher paths stay
  read-only throughout.

The admin server writes desired settings through its existing token, exact-loopback
Host, same-origin POST and preview/confirmation boundary. It does not capture frames
or perform EXP attribution. Capture workers still return to **one serialized capture
writer**. No write route is added to the public server or OBS API.

The scheduler checks desired settings about once a second. Changed lanes stop
scheduling, drain any in-flight attempt under its original run/settings, then close
that run and reopen with the new revision if tracking is enabled. With one worker,
reconciliation can wait for its bounded synchronous attempt. The global 1..8 worker
limit and one in-flight attempt per channel remain enforced. A pause may therefore
have one final already-started attempt. Rapid pause/resume changes can coalesce before
a boundary; the latest desired configuration wins and every approved edit is audited.

Visibility alone does not rotate capture. Settings changes preserve the selected
character and open session; they create new diagnostic runs. Scheduled 60-attempt
rotation remains separate. An admin character rename also refreshes the lane at a
safe boundary without changing its ID. Persistence failures stop the affected lane;
errors appear in Streamers. Pause/resume after reviewing the error retries safely.

Ownership is rechecked after draining: if a name conflict arrives while disabling
automatic recognition, the lane refuses manual capture rather than attributing it
to the wrong character. Re-enable automatic verification or keep tracking paused.
On restart, unresolved enabled policies must be corrected before capture can start.
Runtime heartbeat/status can become stale after a crash; desired policy persists.

## 1. Inspect and rehearse on a consistent copy

These are operator commands for after review. The source inspection/snapshot/report
steps use read-only SQLite connections. Windows may refuse reading a leased marker;
wait for an authorized stop rather than bypassing the lease. Copying a live SQLite
file with `Copy-Item` omits committed WAL data and is not a safe backup.

```powershell
Set-Location H:\Desktop\codex\msclassic-auto-existing-tracker
$main = 'H:\Desktop\codex\msclassic-twitch-exp-tracker'
$python = "$main\.venv\Scripts\python.exe"
$ocr = "$main\private\rapidocr\.venv\Scripts\python.exe"
$env:PYTHONPATH = "$PWD\src"
$db = "$main\private\multi-alpha\live-local.sqlite3"
$config = "$main\private\multi-alpha\live-local.json"
$trial = Join-Path $PWD "private\db-roster-rehearsal-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory $trial | Out-Null
$copy = Join-Path $trial 'rehearsal.sqlite3'

& $python tools/adopt_automatic.py --db $db inspect
& $python tools/adopt_automatic.py --db $db snapshot --output $copy

# Reads JSON settings, including disabled assignments; does not edit the JSON.
# Explicitly choose existing automatic channels whose historical identity was adopted.
# streamer_d/CharD is an example from the successful live trial, not inferred identity.
& $python tools/db_streamer_roster.py --db $copy preview --config $config `
  --automatic-channel streamer_d --reason 'Reviewed current thirteen-channel settings and adopted identities' `
  --preview "$trial\preview-copy.json"
```

Review all imported settings and the `identities` list read from SQLite. The numeric
IDs are not guessed. An automatic subset is optional: omitting `--automatic-channel`
imports all existing channels with automatic recognition **off**. Include each desired
automatic channel once during bootstrap; startup flags are not needed afterward.
The example requires an actual adoption receipt for `streamer_d`. Inspect and use the
[existing identity adoption workflow](existing-tracker-auto-adoption.md) first if it
is missing. A previously observed name or matching level is not historical approval.
Existing `streamer_a` / `CharA` can be approved without renaming; never use `streamer_a` or
assume its numeric ID. Ambiguous legacy aliases retain the prior review requirements.

```powershell
$review = Get-Content "$trial\preview-copy.json" -Raw | ConvertFrom-Json
$confirm = 'bootstrap-roster:' + $review.fingerprint.Substring(0,16)
& $python tools/db_streamer_roster.py --db $copy apply --preview "$trial\preview-copy.json" `
  --confirm $confirm --backup "$trial\before-copy-bootstrap.sqlite3"
& $python tools/db_streamer_roster.py --db $copy inspect

# No capture, network, DB writes or model initialization. Uses a separate test port.
& $python tools/multi_alpha.py --db-roster $copy --port 8879 --continuous `
  --ocr-python $ocr --workers 3 --check

# Optional UI-only rehearsal; no coordinator/capture is started by this command.
& $python -m exp_tracker.admin_server --db $copy --port 8890
# Open http://127.0.0.1:8890/ in a browser. Ctrl+C stops only this admin process.
```

UI saves on this copy modify only the disposable database. Do not start its Twitch
coordinator without explicit capture approval. Automated tests use generated frames
and mocked acquisition through the same Twitch coordinator and OCR evidence paths;
the database roster itself intentionally accepts Twitch sources only. Existing
JSON/local-video tools remain available for offline footage work.

Bootstrap requires a current owned multi-alpha database (schema 9, 10 or 11), existing
selected characters for its historical assignments, exclusive writer access, the
exact preview token and a NEW verified SQLite backup. The preview rehearses the
migration on a temporary copy. Apply migrates and imports atomically, leaves the
ownership marker unchanged, and rejects stale previews. Exceptions roll back all
database changes. Retrying the exact successful preview reports `duplicate: true`.
Keep failed-attempt backups and use a new backup filename for a retry after rollback.

## 2. One controlled transition of the original tracker

After merge/review and an operator-authorized stop of the original coordinator,
make a new preview against the **original**. A copy's preview cannot be applied to
another path. Never bypass a busy writer lease or change the original WAL files.

```powershell
& $python tools/db_streamer_roster.py --db $db preview --config $config `
  --automatic-channel streamer_d --reason 'Approved database-owned roster and existing adopted automatic subset' `
  --preview "$trial\preview-original.json"

$review = Get-Content "$trial\preview-original.json" -Raw | ConvertFrom-Json
$confirm = 'bootstrap-roster:' + $review.fingerprint.Substring(0,16)
& $python tools/db_streamer_roster.py --db $db apply --preview "$trial\preview-original.json" `
  --confirm $confirm --backup "$trial\before-original-bootstrap.sqlite3"
```

The configured intervals (including the existing 20s values), quality, timeouts,
neural-level option, crop setting, capture authorization and tracking enablement are
imported. Public visibility starts enabled for imported channels; paused/hidden
choices can then be reviewed in the portal. Historical streamers outside the import
are hidden from the directory, with their data and direct URLs retained.

Use the same public port **8766**. After merge, launching from the main checkout
uses its normal private log root. These commands are for the operator, not executed
during development. Keep any existing public-only, CORS and Twitch-status flags.

```powershell
Set-Location $main
$env:PYTHONPATH = "$main\src"
& $python tools/multi_alpha.py --db-roster $db --port 8766 --continuous `
  --ocr-python $ocr --workers 3 --check

# LIVE: only with operator authorization; short verification first, retention off.
& $python tools/multi_alpha.py --db-roster $db --port 8766 --continuous `
  --ocr-python $ocr --workers 3 --max-attempts 6 --exit-after-capture
```

Existing-mode coordinator preflight claims/probes the writer lease and port, so the
original must be stopped even for `--check`. Standalone read-only inspection does
not claim the port. Before bootstrap, the JSON commands remain compatible. After
bootstrap, JSON startup is refused to prevent it overriding paused/hidden/automatic
database policy; use `--db-roster`. JSON is no longer needed for routine operation.
Do not run older schema-10 binaries against schema 11. Keep the consistent backup;
rollback/promotion requires separate operator review and is never automatic.

## 3. Operate without restart

Start the protected admin portal on its own loopback port, separate from capture:

```powershell
& $python -m exp_tracker.admin_server --db $db --port 8890
```

In **Streamers**, choose **Add streamer**, enter its Twitch login, confirm capture
authorization and enable tracking. Automatic names are selected for new streamers;
tracking and authorization start unchecked. Review then confirm. The already-running
coordinator creates the lane at its next reconciliation boundary. No initial real
character is required. The internal pending character cannot receive accepted EXP
or appear as `PendingOCR` on public pages. Two strong, distinct, fresh full-frame name
readings establish the real character/session and its first numerically validated
baseline. Failed, duplicated, stale or multi-HUD frames cannot supply confirmation.

Configure a streamer to pause/resume, choose a 5..300s interval (automatic recognition
requires <=60s), rendition, timeouts, neural level/crops, public visibility or automatic
identity. Existing historical identities require adoption before enabling automatic
recognition; the portal refuses guessed mappings. New-streamer discovery uses separate
identity state, not legacy adoption. A -> B -> A reuses IDs. Unreadable names alone do
not interrupt plausible tracking after identity verification. Conflicts, held readings,
level floors and numerical validation retain their existing safeguards.

Paused tracking does not erase history or close the character's session. Hide only
removes directory entries (both Streamers and Characters modes); direct character
pages and OBS remain read-only and available. This is visibility, not access control.
Visibility is filtered in the metadata query **before** taking directory slots, so
unmanaged/hidden historical channels cannot crowd out visible managed channels or
cause a misleading truncation warning. Historical direct URLs warm on demand through
the same publisher, with eight additional channel views and a 60s idle expiry/LRU
replacement. Directory refreshes take priority. Browsing these URLs adds no Twitch
status requests or capture work. JSON-mode directories also have no fixed channel-count limit.
Status distinguishes desired tracking from observed waiting/running/draining/error,
shows last attempts/current character/identity where available and labels old runtime
heartbeats. The portal polls status every 5s. Changes while editing require another
preview if the settings revision changed. Repeated confirmation is idempotent.

## Retention and limits

The existing approximately 24h granular retention, causal checkpoints and at-most-one
eligible observed daily status per character/UTC date are unchanged. Adoption/bootstrap
alone does not prune history. Daily statuses remain storage-only. Audit/session tables
are not subject to a strict size ceiling. Keep initial verification retention-free,
then follow the [retention dry-run/copy rehearsal](existing-tracker-auto-adoption.md#4-separately-approve-and-enable-24h-retention)
before explicitly enabling it. Once approved:

```powershell
& $python tools/multi_alpha.py --db-roster $db --port 8766 --continuous `
  --ocr-python $ocr --workers 3 --retention-24h
```

Desired settings survive crashes and restarts, including automatically selected
characters and identity conflicts. There is **no fixed managed-channel count limit**;
pause/hide preserves membership rather than deleting history. There is no destructive
delete, global character linking, remote administration or automatic history merging.

Capture concurrency independently stays 1..8 workers with one serialized capture
writer. The public directory includes all visible managed channels; optional Twitch
status checks use batches of at most 100 logins. Hidden historical/character views,
per-history work bounds and acceleration caches retain their separate limits.
Removing the count cap does not establish throughput at larger rosters: capture
cadence, publication latency and memory remain limited by the host. No database
migration is needed; restart backend/admin processes to load this change. Do not set
workers equal to configured streamers.

Synthetic checks cover a 40-channel bootstrap and JSON coordinator, a 50-channel
managed directory, 81 published channels and 201 batched Twitch statuses, including
partial API failures. A 100-channel idle replay verifies that the 256-entry
checkpoint and ETA caches avoid rereading unchanged histories on the next pass.
These demonstrate software behavior, not live capture throughput at those sizes.

`PendingOCR` is an exact, reserved internal name, not a real identity or an alias to
rename into one. Shared diagnostic writes hold its numeric evidence even outside
automatic mode; trusted ingestion rejects progression, manual EXP assertions and
renaming to/from it are refused, and daily snapshot storage excludes it. OCR text
equal to this reserved name cannot confirm discovery. Public character rosters omit
it; live and legacy OBS responses show an em dash. A real verified name creates a
separate character/session through the existing two-frame policy. These guards do
not rewrite any pre-existing erroneous data or audit history.

HUD caching is refused in database-roster mode, since automation may be enabled
live. The existing shared resident recognizer service reuses a process per OCR command
for eligible crops; no extra video download, persistent Twitch session or second full-frame
OCR pass is introduced. Polling is bounded to one desired-roster check per second
and change/heartbeat updates (about 5s) on the serialized writer. Full-frame CPU cost,
actual cadence and model-worker contention still need the separate performance branch's
capacity validation; worker count in examples is not a throughput recommendation.

Two independent frames cannot defeat systematic wrong OCR or distinguish another
person's gameplay feed. Associations remain per-channel and auditable. A channel's
discovery cap and exceptional floor-repair limits still apply.

## Validation

`tests/test_db_streamer_roster.py` exercises thirteen-channel migration, protected
preview/save, unknown discovery through real generated-frame OCR interfaces, dynamic
add/pause/resume/settings changes, in-flight revision/disable races, selected-ID reuse,
restart, rotation, retention, visibility and failed transactions on disposable data.
`tools/admin-streamers.test.mjs` covers the form and stale-preview handling.

The roster-review Python regression run passed **2,662 tests**, with **122 skips** (private
fixtures and environment restrictions); the concurrent localhost viewer test was
excluded from that sandbox run. All three real localhost HTTP regressions, including
that test, passed separately with sockets permitted. Frontend tests passed **141/141**.
Focused roster, publisher, profile, Store, daily-snapshot, retention and server tests
passed **220 tests**, with six private/environment skips. The roster coverage includes
the operator CLI copy rehearsal, preview-version rejection, legacy interval defaults,
43-channel historical-directory visibility, bounded historical URL browsing and
reserved-placeholder guards through retention/restart and nonautomatic ingestion.

The migration-boundary follow-up passed **438 focused tests** with one OS hard-link
skip. Its full parallel run had **2,672 passes, 122 skips and one timing-sensitive
failure**: `test_thirteen_channels_mixed_workers_restart_expand_and_disable` did not
observe overlap between its 1 ms synthetic captures. That pre-existing test passed
in the focused run and an isolated serial rerun. Its fixture uses schema 11, not the
changed migration branch. No scheduler/performance changes were made to accommodate
the overlap assumption. New regressions cover ordinary schema-10 Store/admin/CLI/
JSON writes, fresh initialization, and explicit bootstrap rollback/retry through the CLI.

The isolated browser smoke uses a new profile and synthetic database, adds a streamer
without a character, confirms settings, changes visibility independently of tracking,
and checks desktop/mobile overflow and JS errors. It does not start capture. Private
results/crops/databases/logs remain ignored. No live production/Twitch/VPS validation
or capacity benchmark is implied.

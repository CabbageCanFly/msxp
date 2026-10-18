# Managing the local streamer roster

Use `tools/stream_roster.py` to edit the existing private multi-alpha JSON safely.
It never captures video, calls Twitch, writes SQLite, changes selected characters,
or deletes history. The coordinator now supports **1–25 enabled assignments**
within at most 25 configured assignments. Existing files need no conversion:
omitting `enabled` means enabled.

## Existing roster

Run from the repository root in PowerShell. These examples use the existing
two-stream config; substitute your actual config path if different.

```powershell
$roster = 'private/multi-alpha/live-telfer-shiphtur.json'
.\.venv\Scripts\python tools/stream_roster.py --config $roster list
.\.venv\Scripts\python tools/stream_roster.py --config $roster inspect telfer1
.\.venv\Scripts\python tools/stream_roster.py --config $roster disable shiphtur --dry-run
.\.venv\Scripts\python tools/stream_roster.py --config $roster disable shiphtur
.\.venv\Scripts\python tools/stream_roster.py --config $roster enable shiphtur
```

Disabling preserves every assignment setting, authorization choice, selected
character, open session, run and observation. Re-enabling uses the same settings.
`remove CHANNEL` only removes the JSON assignment; SQLite history remains and
`list` reports it as `historical_only`. Disabling is preferable for temporary pauses.

Add a new assignment with the **actual explicitly selected character label**:

```powershell
# Staged disabled by default: no permission to capture is assumed.
.\.venv\Scripts\python tools/stream_roster.py --config $roster add NEW_LOGIN --character 'Main' --interval 20 --count 12 --experimental-neural-level --save-crops --dry-run
.\.venv\Scripts\python tools/stream_roster.py --config $roster add NEW_LOGIN --character 'Main' --interval 20 --count 12 --experimental-neural-level --save-crops

# Only after obtaining permission, explicitly enable live capture:
.\.venv\Scripts\python tools/stream_roster.py --config $roster enable NEW_LOGIN --authorized
```

`add --authorized` can explicitly authorize and enable in one step. `--disabled`
keeps a new assignment disabled even when authorized. `enable` preserves a saved
authorization; otherwise Twitch requires `--authorized`. No credentials belong in
this config: use the ignored `.env` described in [Twitch authentication](twitch-authentication.md).
Unknown config fields (including token/secret fields), duplicates, invalid logins,
invalid settings and mismatched saved character selections are rejected before
the config is changed. There is deliberately no command that switches a character.
Use explicit existing Store administration for an intentional character switch.

## Controlled restart

1. Preview/edit the roster. An already-running coordinator keeps its original lanes.
2. Press **Ctrl+C in that coordinator's terminal** and wait for shutdown. Do not kill
   workers or start a second coordinator on the same DB.
3. Validate and restart with the same config and database:

```powershell
.\.venv\Scripts\python tools/multi_alpha.py --config $roster --check
# Starts live capture ONLY for explicitly authorized enabled Twitch assignments.
.\.venv\Scripts\python tools/multi_alpha.py --config $roster --continuous --twitch-status
Start-Process 'http://127.0.0.1:8765/streams'
```

The OS coordinator lock still prevents duplicate workers. Restart reuses exact
channel/character/session bindings but creates fresh run UUIDs (`process_start`),
so it never treats the restart as a clean 60-attempt rotation or bridges progress
across the interruption. Enabled lanes are due immediately, served sequentially;
OCR/tool startup and lane count determine how soon each gets its first capture.
The persisted chart, last-known level and historical estimates are available
before new readings; they retain their actual ages and are not newly confirmed.
New current pace needs fresh eligible evidence. An unfinished crashed run remains
visible as activity unknown and is preserved, not silently finalized or replayed.

Zero enabled assignments is a valid parked roster, but capture refuses to start.
For historical viewing, launch only the existing read-only server with the
**same `database` path shown in your config**, e.g.:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --diagnostic-dashboard
```

`list` separates `configured`, `disabled` and `historical_only`, with saved run and
attempt counts. `inspect` also prints assignment settings. These are configuration
and historical facts, **not a running-worker detector**. Use `/streams` on the
coordinator's own server for truthful capturing/waiting/failing/stopped activity.
An independent read-only server cannot claim another process is actively capturing.
Disabling does not hide a saved streamer from historical pages. The existing
website directory is bounded to 25 saved channels; removing JSON entries does not
remove those SQLite identities or expand that display limit.

## New roster or offline check

```powershell
# Init refuses to overwrite an existing file; this does not create the database.
.\.venv\Scripts\python tools/stream_roster.py --config private/roster-test/config.json init --database private/roster-test/tracking.sqlite3
.\.venv\Scripts\python tools/stream_roster.py --config private/roster-test/config.json add local_one --source file --file samples/sample-stream3.mp4 --start 1145 --character 'Local test' --interval 15 --count 2
.\.venv\Scripts\python tools/multi_alpha.py --config private/roster-test/config.json --check
.\.venv\Scripts\python tools/multi_alpha.py --config private/roster-test/config.json --exit-after-capture
```

For a roster using explicit local-video 3s settings, pass `--offline-fast-test`
before the roster subcommand and to the coordinator. Disabled Twitch entries do
not run; enabled Twitch entries still prohibit fast mode. Config validation does
not verify installed OCR tools or video existence; coordinator `--check` remains
the tool preflight. Missing enabled videos still produce bounded failed attempts.

## Safety and validation

Edits use an OS-released per-config lock, same-directory temporary file, flush,
`fsync` and atomic replacement. Existing values/order are preserved; JSON whitespace
is reformatted. An external edit detected before replacement aborts. Use this
tool for concurrent edits: a separate editor that ignores the lock can still race
the final check. Dry-run changes neither JSON nor SQLite (a lock file may remain).
All configs, temporary/lock files and test evidence remain in ignored directories.
Inspection is bounded to 100 saved channels; this is an operator CLI, not a new
historical analytics service.

Offline regression tests exercise add/preview, authorization, disabled validation,
duplicates, invalid JSON, write failure, concurrent edits, exact character mismatch,
one active stream, all-disabled refusal, in-flight config edits and controlled
restart. They use virtual scheduling/capture stubs with actual SQLite/server
lifecycle; they are not an acquisition-speed or OCR-accuracy benchmark.

```powershell
.\.venv\Scripts\python -m pytest tests/test_stream_roster.py tests/test_multi_alpha.py tests/test_hud_resilience.py tests/test_diagnostic_history.py -q
.\.venv\Scripts\python -m pytest -q
```

Hot add/remove is deferred. It needs lane changes at safe attempt boundaries,
per-channel run closure/start, active-status updates, authorization and ownership
rechecks, and tests for rotation/interruption races. A controlled restart is small
and safe at this stage. No capture/OCR, Helix, EXP arithmetic, quarantine, schema
or trusted-accounting policy changes are needed for roster management.

Validation on this workspace: **15 new roster tests passed**; full Python suite
**1,396 passed, zero skips** in 119.79s with localhost access enabled; **70 Node
tests passed**. The initial restricted full run was 1,395 passes plus one
loopback-policy skip, subsequently exercised successfully. `git diff --check`
passed. Existing live-roster `list` and capture `--check` passed without network
connections or database writes.

A separate real localhost HTTP check reopened the saved two-stream database with
two fresh server instances. Telfer1's supported level 66 and 394 history points,
and Shiphtur's level 57 and 393 points, returned identically before new capture.
Private reproduction script/results: `private/roster-tests/check_saved_history.py`
and `saved-history-check.json` (the script writes its result exclusively; use a new
output filename for a repeat). No Twitch request or new capture was made. No new
browser rendering checks were needed because frontend assets were unchanged.

Changed public files: `tools/stream_roster.py`, `tools/multi_alpha.py`,
`tests/test_stream_roster.py`, `README.md`, `docs/multi-alpha.md`,
`docs/continuous-alpha.md`, and this guide. Existing private roster contents,
capture evidence and SQLite payloads were preserved. No commit or push was made.

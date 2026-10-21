# Restart recovery and independent capture/API services

This is an opt-in backend integration. No VPS operations are performed by the code
or installer. Existing bundled JSON and database-roster commands keep their current
behavior unless the new options are supplied. Caddy, the frontend, capture/OCR
acceptance rules, tracking schema and retention settings are unchanged.

## What survives a restart

`--publication-cache PATH` on `exp_tracker.server` (or the bundled coordinator)
stores publications and settled recent/24h replay checkpoints in a **separate,
disposable SQLite file**. It never adds tables to the tracking database. The existing
retention JSON codec preserves fractions, tuples, sets, deques and aware timestamps;
no executable object serialization is used. Checkpoints are written when their
settled run prefix changes, rather than serializing the full state on every poll.
Publications are saved after successful builds. SQLite transactions protect both
against interrupted writes. The cache has one API owner, using an OS-released lease.

Restored publications retain their original computation and reading timestamps.
They are immediately available while the publisher rebuilds, with
`publication.state = "restored"`, `computed_at` and `updating = true`. The homepage
also includes these channels in `warming`. Existing age/stale presentation is
reapplied at the request clock. Twitch status is fetched independently; an old
cached status is not restored. Publications older than 24h, or from a future clock,
are withheld. Cache restoration does not claim a fresh capture or a fresh window.

Compatibility includes the absolute database path and file identity, schema, the
backend Python/data-file digest, selected character/session and correction,
rename, invalidation and retention revisions. Raw input fingerprints include run
configuration, summary and original payloads. Closed inputs are memoized only within
one API lifetime; a restart verifies their bytes again. Capture appends can leave an
older dated publication available, but a new build must incorporate the new revision.
Existing causal replay validates every restored checkpoint prefix before reuse.
Changing accounting code intentionally requires a cold rebuild. Old retention
checkpoints are not rewritten or repaired by this disposable cache.

Each cache record and source scan uses the existing 128 MiB / 65,536-event /
1,024-run limits. Runtime checkpoint memory retains its existing 256-entry bound.
Removed directory channels are pruned from disk on startup. Decode/source failures
discard the affected record. An unreadable SQLite cache falls back to cold
publication; it does not replace the file or tracking data. Cache write failures
leave the live publication usable. Publisher diagnostics report `restored` and
`cache_error`. A busy cache lease or a path pointing at another valid SQLite
database is a configuration error, not permission to overwrite it.

The cache contains private diagnostic context: keep its directory private. It is
not a backup. When deliberately restoring/replacing the tracking database, keep the
SQLite file and matching `.multi-alpha.json` marker together using the existing
[snapshot/restore procedure](vps-roster-rollout.md). The disposable publication cache
and runtime heartbeat need not be backed up or copied between machines.

## Separate processes, one capture writer

`multi_alpha.py --db-roster DB --continuous --capture-only --runtime-state FILE`
keeps the existing exclusive ownership-marker lease, scheduler, automation, worker
bounds, retention and shutdown behavior. It starts **no HTTP listener, publisher or
Twitch status client**, and does not probe port 8765. This mode is restricted to the
explicit schema-11 database roster. HTTP/CORS/cache/status flags belong on the API
command and are rejected on capture-only startup. `--check` remains read-only and
does not create the heartbeat or connect to Twitch.

Capture writes a bounded, atomic, private JSON heartbeat once per second. It carries
database identity, active run IDs and current scheduler states. The API reads it via
`--runtime-state FILE`. Missing, malformed, foreign, future or >15-second-old
heartbeats cannot assert active capture. Graceful capture shutdown publishes empty
runtime state; a crash expires naturally. The API owns no capture lease and opens
the tracking database read-only. Runtime files must be distinct from the database,
its marker and the API cache. No admin endpoint or IPC port is added.

### Local Windows example

Stop the existing local coordinator first; these commands do not transfer history
from the VPS. From the repository root, start the API in one PowerShell terminal:

```powershell
$env:PYTHONPATH = "$PWD\src"
& .\.venv\Scripts\python.exe -m exp_tracker.server --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --port 8765 --public-only --cors-origin https://msxp.pages.dev --publication-cache private/multi-alpha/publication-cache/publications.sqlite3 --runtime-state private/multi-alpha/publication-cache/capture-runtime.json
```

In another terminal, start the sole capture coordinator. This opens live Twitch
connections; use it only for the already reviewed local roster:

```powershell
& .\.venv\Scripts\python.exe tools/multi_alpha.py --db-roster private/multi-alpha/live-telfer-shiphtur.sqlite3 --continuous --capture-only --runtime-state private/multi-alpha/publication-cache/capture-runtime.json --ocr-python private/rapidocr/.venv/Scripts/python.exe --workers 6 --stagger-capture --resident-neural --resident-tesseract
```

Append `--check` to that capture command for preflight only. Ctrl+C in capture's
terminal leaves the API running. Ctrl+C in the API terminal leaves capture running.
For a bundled local process, add only `--publication-cache PATH` to the existing
command; no heartbeat option is needed. Retention remains separately opt-in.

## Reviewed Ubuntu cutover

These commands are an operator runbook, **not an automatic deployment**. First review
`systemctl cat msxp-tracker` and the existing database/marker, environment files,
capture bounds and retention choice. Keep the current database authoritative; no
Windows/VPS database synchronization or migration is implied. Do not rerun the
legacy installer. Prepare the new files without changing the running service:

```bash
cd /opt/msxp/app
sudo install -d -o msxp -g msxp -m 0750 /opt/msxp/app/private/publication-cache
sudo install -o root -g msxp -m 0640 deploy/msxp-split.env.example /etc/msxp/split.env
sudoedit /etc/msxp/split.env
```

Both services must use the exact same explicitly reviewed `MSXP_DATABASE` and
`MSXP_RUNTIME_STATE`. The cache path must be a new dedicated file. Optional Twitch
status uses the existing credentials in `/etc/msxp/msxp.env`. Capture bounds and
retention remain those already reviewed in `roster.env`/production overrides; the
new files do not clear a bounded trial or turn retention on.

After explicit cutover approval, stop the old bundled coordinator and confirm the
writer has exited. The API needs its former port; there is one brief transition
from the bundled deployment, not a claim of zero downtime:

```bash
sudo systemctl stop msxp-tracker
sudo systemctl status msxp-tracker --no-pager
sudo ss -ltnp 'sport = :8765'
pgrep -af 'multi_alpha.py' || true
```

Do not continue if another coordinator is still running. Retain the existing roster
and production drop-ins; install the capture override **after** them:

```bash
sudo install -o root -g root -m 0644 deploy/msxp-api.service /etc/systemd/system/msxp-api.service
sudo install -o root -g root -m 0644 deploy/msxp-tracker-capture-only.conf /etc/systemd/system/msxp-tracker.service.d/40-capture-only.conf
sudo systemctl daemon-reload
sudo systemctl cat msxp-tracker msxp-api
sudo systemd-analyze verify msxp-tracker.service msxp-api.service
```

Confirm the tracker command contains `--capture-only`, the API command contains
`--public-only`, and the database/runtime paths match. Run the rendered capture
`ExecStartPre` command with `--check` if a standalone preflight is desired; it must
not require the API port to be free. Then start the API and the single capture
service, preserving any existing trial limits:

```bash
sudo systemctl start msxp-api
sudo systemctl start msxp-tracker
sudo systemctl status msxp-api msxp-tracker --no-pager
sudo journalctl -u msxp-api -u msxp-tracker -n 80 --no-pager
curl -fsS http://127.0.0.1:8765/api/players
```

Verify the authoritative database, unchanged IDs, fresh captures, correct character
ownership, API timestamps, and absence of errors before production enablement.
Developer/admin paths remain outside Caddy's existing allowlist. The first API
startup is cold; subsequent compatible API restarts restore the cache. No restart
duration improvement or VPS load result is claimed here.

After the bounded rollout is approved, enable the API at boot:

```bash
sudo systemctl enable msxp-api
```

The two services intentionally have no `PartOf`/`Requires` restart coupling. For
capture-only changes, use `sudo systemctl restart msxp-tracker`; the API stays up
with its memory caches. For accounting, public API or shared-code changes, restart
the API too so it uses the new code. `sudo systemctl restart msxp-api` does not
restart capture. Stage dependencies before stopping services. All writers remain
serialized through the existing capture lease and Store transactions.

## Rollback and recovery

To return to the previously reviewed bundled roster configuration, stop **both**
services first. Preserve every new attempt in the current database; process layout
rollback does not require a database restore. Move only the new drop-in aside,
disable the new API unit, reload and start the old bundled unit:

```bash
sudo systemctl stop msxp-tracker msxp-api
sudo systemctl disable msxp-api
sudo mv /etc/systemd/system/msxp-tracker.service.d/40-capture-only.conf /etc/msxp/40-capture-only.conf.disabled
sudo systemctl daemon-reload
sudo systemctl cat msxp-tracker
sudo systemctl start msxp-tracker
```

The old `20-roster.conf`/`30-production.conf` must still name the same authoritative
database and reviewed retention/bounds. Do not restart an older-schema executable
or revert the tracking database just to undo service separation. If an actual code
rollback changes accounting, discard incompatible cached results and rebuild.

To abandon a cache after corruption, stop `msxp-api` and move only
`publications.sqlite3` and any associated cache journal into a new private recovery
directory. Leave `capture-runtime.json` in place; capture can keep running. Restart
the API to create a fresh cache. Never move the production database directory or
ownership marker. This loses only disposable warm state. Retention, backup
activation and database restore remain separate reviewed operations under the
existing runbook.

## Local validation

Focused tests use disposable databases and synthetic captures. They cover typed
checkpoint recovery, original publication timestamps, full-rebuild parity, source
drift, code/policy changes, correction and ownership invalidation, clock regression,
corruption fallback, cache leases, heartbeat expiry, port-independent capture
preflight, retained single-writer ownership and API/capture coexistence. No live
Twitch/VPS connection, full private-history sweep or deployment benchmark is needed.

Validation on Windows: **151 focused tests passed, no skips**; eight saved-history
cases were deliberately deselected. The initial sandbox run blocked a local
loopback client; the final bounded run with loopback access passed. `git diff
--check` also passed. Ubuntu systemd installation, live capture and restart timing
have not been exercised for this integration.

# Ubuntu VPS backend deployment (Phase 2, Track A)

For the current schema-11 database-roster rollout, use the
[operator runbook and opt-in service drop-in](vps-roster-rollout.md). The JSON unit
and installation recipe below remain legacy; do not reinstall them or enable their
retention flag as part of the roster cutover.

The public frontend is hosted separately on Cloudflare Pages (`https://msxp.pages.dev`).
The VPS runs Twitch capture, OCR, SQLite, EXP calculations, background publishing and a
read-only HTTPS JSON API. Background: [VPS readiness](vps-readiness.md).
The backend has passed the separate Ubuntu 26.04 VPS capture/API trial. The
Windows production DB has not been migrated and the VPS production tracker service
is not yet enabled. The [24-hour retention changes](24h-retention.md) have not been deployed.

```
browser ── https://msxp.pages.dev (Cloudflare Pages: HTML/JS/CSS, other worktree)
   │ fetch, simple GET, no credentials
   ▼
Caddy :443 (TLS, HSTS, gzip/zstd) ── only GET /api/players[/{ch}[/history]]
   ▼
multi_alpha --public-only --cors-origin https://msxp.pages.dev   127.0.0.1:8765
   capture + OCR workers ─► SQLite (WAL) ◄─ background publisher ─► public JSON
admin_server (manual EXP), 127.0.0.1:8766: never proxied; SSH tunnel only
```

## API contract for the frontend

Unchanged from the same-origin product. Base URL `https://API_HOSTNAME`.

| Request | 200 body |
|---|---|
| `GET /api/players` | `players[]`, `served_at`, `truncated`, `experimental`, `poll_seconds` (2), `warming[]` while cold |
| `GET /api/players/{ch}` | `player`, `history`, `tracked_history`, `history_revision`, `tracked_revision`, `truncated`, `served_at`, `experimental`, `poll_seconds` |
| `GET /api/players/{ch}?history=H&tracked=T` | As above, omitting `history` / `tracked_history` while the page holds exactly those revisions ([conditional history](vps-readiness.md#conditional-character-history)) |
| `GET /api/players/{ch}/history` | The tracked packet plus `served_at` |

Errors are JSON with an `error` field:

- `400 invalid_channel`, `404 unknown_channel`;
- `503 warming_up` with `Retry-After: 2`;
- `503 publication_limit` and `503 database_unavailable`;
- `404 not_found` from Caddy for every other path or method.

Fields are the [public projection](vps-readiness.md#public-projection).

**CORS.** The tracker answers CORS on every response, errors included, for the exact
origins given by `--cors-origin`. It sends `Access-Control-Allow-Origin: <origin>`,
`Vary: Origin` and `Access-Control-Expose-Headers: Retry-After`. Other origins get no
CORS headers. Requests must stay CORS-simple: `GET`, no custom request headers, no
credentials. `fetch(url, {cache: 'no-store'})` qualifies. There is no preflight
support: `OPTIONS` returns 404 at Caddy. If the tracker is down, Caddy's 502/504 has
no CORS headers, so `fetch` rejects; treat that like any other outage. Cloudflare
Pages preview origins (`https://<hash>.msxp.pages.dev`) are not allowed unless added
as another exact `--cors-origin`.

## Install (Ubuntu 24.04, as root)

```sh
git clone <repository> /opt/msxp/app        # The units assume this path.
sh /opt/msxp/app/deploy/install-ubuntu.sh api.example.org
```

The script:

- installs `python3-venv`, `tesseract-ocr`, `ffmpeg`, `sqlite3` and Caddy (Ubuntu
  2.6.2);
- creates the `msxp` system user;
- builds `.venv` (`.[capture,dev]`) and the pinned RapidOCR worker in
  `private/rapidocr/.venv`;
- installs `deploy/config.example.json` → `private/vps/config.json` and
  `deploy/msxp.env.example` → `/etc/msxp/msxp.env`, unless they already exist;
- installs the systemd units and the Caddyfile, then runs `caddy validate`.

It **enables and starts nothing**. Code stays root-owned; only `private/` is writable by
`msxp`. Mutable data must physically live in `/opt/msxp/app/private`, because the
tools reject paths outside the checkout's `private/`, symlinks included.

## Offline validation (before any live data)

```sh
cd /opt/msxp/app
.venv/bin/python -m pytest -q tests/test_server.py tests/test_publisher.py tests/test_multi_alpha.py -k 'not saved'
sh deploy/offline-check.sh        # Synthetic DB + real Caddyfile on 127.0.0.1:18080; no TLS/Twitch
sudo -u msxp .venv/bin/python tools/multi_alpha.py --config private/vps/config.json --check --twitch-status
```

`offline-check.sh` verifies:

- the API with CORS, including the 400/404 error bodies;
- the refusal of other origins;
- that `/`, pages, static files, `/dev/*`, `/dashboard/*`, trusted state, shadow,
  `/admin` and `POST` all get 404 at the proxy;
- the tracker's own refusal of developer routes;
- gzip compression.

`--check` validates the capture configuration, OCR worker and tools without connecting
or writing.

Measured on this workstation's WSL Ubuntu with Python 3.12.3 and Caddy 2.6.2 (not a
VPS):

- the focused server/publisher/multi_alpha/product/history/auth tests: **158 passed**;
- `offline-check.sh`: **16/16**;
- `caddy validate`: valid, and `caddy fmt` makes no changes;
- `systemd-analyze verify` parses all three units.

Linux Tesseract 5.3.4, FFmpeg, Streamlink and RapidOCR were **not** exercised. Run a
bounded local-video trial on the VPS first (`docs/multi-alpha.md`), then measure with
`tools/benchmark_homepage.py` against a copy.

## Configure

- `/etc/msxp/msxp.env` (root:msxp, 0640): `MSXP_FRONTEND_ORIGIN`, plus optional
  `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` for `--twitch-status`.
- `private/vps/config.json`: one `"source": "twitch"` row per channel with
  `"authorized": true`, the selected character label and its cadence. Validate it
  with `--check`.
- DNS: an `A`/`AAAA` record for `API_HOSTNAME` → the VPS. Firewall:
  `ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable`. Never open 8765 or 8766.

## Database migration: coordinated cutover (later)

Exactly one coordinator may ever write a tracking history. A copy taken while Windows
capture keeps running is out of date as soon as the next reading is recorded. Starting
the VPS on such a copy while Windows continues forks the history into two.

**Trial copies (any time, non-final).** Rehearse on the VPS with copies taken while
Windows keeps capturing: offline check, `--check`, benchmark, restore drill, and the
validation in step 5. `python tools/backup_database.py <live.sqlite3>
private/migration/trial-<UTC>.sqlite3` stays consistent during capture. Delete trial
copies before the cutover. A VPS coordinator started on a trial copy for testing must
never become production.

Fingerprint: run on either machine, against a file not being written. It prints schema
version, attempt count, last attempt time, `integrity_check` and the file hash:

```sh
python -c "import sys,hashlib,sqlite3,pathlib;p=pathlib.Path(sys.argv[1]).resolve();d=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);print(d.execute('PRAGMA user_version').fetchone()[0],*d.execute('SELECT COUNT(*),MAX(attempted_at) FROM diagnostic_attempts').fetchone(),d.execute('PRAGMA integrity_check').fetchone()[0],hashlib.sha256(p.read_bytes()).hexdigest()[:16])" FILE
```

**Final cutover.**

1. **Prepare the VPS completely first.** Install, offline check, `/etc/msxp/msxp.env`,
   `config.json` matching the Windows channels and characters, DNS, firewall and a
   rehearsed trial copy. `msxp-tracker` stays disabled and stopped.
2. **Stop Windows capture, in coordination.** Announce the downtime. Press Ctrl+C in
   the `multi_alpha` console: it finalizes runs and writes summaries. Wait for it to
   exit. Stop any admin or developer server using the database, then confirm no Python
   process remains (`Get-Process python`). Windows capture is not restarted from here
   on, except in a rollback.
3. **Take the final verified backup on Windows.**
   `python tools/backup_database.py <live.sqlite3> private/migration/final-<UTC>.sqlite3`
   copies every committed transaction, including any left in the `-wal` file, then
   runs `integrity_check` and `foreign_key_check`. Record the fingerprint of the
   **live** database and of `final-*`; their version, count and last attempt must
   agree. Keep the live database untouched as the rollback copy.
4. **Transfer the database and its ownership marker.** Copy `final-*.sqlite3` and the
   marker `<live.sqlite3>.multi-alpha.json` to the VPS, for example with `scp`. Install
   them as `private/vps/tracker.sqlite3` and `private/vps/tracker.sqlite3.multi-alpha.json`,
   leaving no `-wal`/`-shm` beside them, then `chown msxp:msxp private/vps/*`.
   `multi_alpha` refuses a database without its marker, and a marker without its
   database.
5. **Validate the destination before starting.**
   - Its fingerprint (as `msxp`) equals the Windows `final-*` fingerprint: same
     version, count, last attempt and hash, with `integrity_check` = `ok`.
   - This code supports its schema:
     `sudo -u msxp env PYTHONPATH=src .venv/bin/python -c "import sys;from exp_tracker.store import Store;print(Store(sys.argv[1],read_only=True).schema_version)" private/vps/tracker.sqlite3`
     raises for a version this checkout cannot read. The VPS code must be at least as
     new as the code that last wrote the database (the manual-EXP admin adds schema 7).
   - `sudo -u msxp .venv/bin/python tools/multi_alpha.py --config private/vps/config.json --check --twitch-status`
     passes.
6. **Controlled start.** `systemctl start msxp-tracker`, without enabling it yet, then
   `systemctl reload caddy`. Watch `journalctl -u msxp-tracker -f`.
7. **Verify after starting.**
   - `curl -s http://127.0.0.1:8765/api/players` lists every channel: warming at first,
     then players.
   - Within a few capture intervals the fingerprint's attempt count rises above the
     final Windows count, with new `attempted_at` values.
   - A GET through Caddy returns 200 with the exact origin. HEAD is refused by design,
     so use a GET that prints only the headers:
     ```sh
     h=$(curl -sS -o /dev/null -D - -H 'Origin: https://msxp.pages.dev' https://API_HOSTNAME/api/players | tr -d '\r')
     printf '%s\n' "$h" | grep -E '^HTTP/[0-9.]+ 200' && printf '%s\n' "$h" | grep -ix 'access-control-allow-origin: https://msxp.pages.dev'
     ```
     Both lines must print.
   - The Pages frontend shows current readings.

   Only then run `systemctl enable msxp-tracker`. Leave `msxp-backup.timer` disabled;
   the provider already supplies seven-day automatic snapshots for MVP.
8. **Roll back if startup or verification fails.**
   - *The VPS has not recorded any new attempt* (count still equals the final Windows
     count): `systemctl stop msxp-tracker` and keep the VPS copy for diagnosis.
     Restart Windows capture on its untouched live database. Only capture downtime is
     lost.
   - *The VPS has already recorded attempts*: the copies have diverged. Do **not**
     restart Windows on its old database. Either fix forward on the VPS, or return the
     complete history to Windows by the same steps in reverse:
     1. `systemctl stop msxp-tracker` (SIGINT finalizes runs) and confirm it exited.
     2. Take a fresh final backup with `tools/backup_database.py`, then fingerprint it.
        Never use an older scheduled backup: it can omit the latest readings.
     3. Transfer that backup and `tracker.sqlite3.multi-alpha.json` together.
     4. Validate them on Windows before restarting capture there.

**Requirement-table hash.** Git stores `src/exp_tracker/data/community-exp-v2.json`
with LF line endings. The current Windows capture checkout holds a CRLF copy, so its
runs record `requirements_sha256` `4a7728…`, while the VPS checkout records `ffb597…`
for identical content. Only consecutive runs of one coordinator compare it, so the
migration's process start is unaffected. Decide before go-live whether to pin line
endings (for example `*.json -text` in `.gitattributes` and re-checking out the
Windows file), or to accept the differing hash.

## Backups and restore

For MVP, use the provider's seven-day automatic server snapshots. The separate
14-day local `msxp-backup.timer` remains disabled; off-site automation is outside
this feature. `tools/backup_database.py` remains available for explicit consistent
migration/rehearsal copies (WAL included), with integrity and FK validation.
See [retention and snapshot restore risks](24h-retention.md#snapshots-and-remaining-limits):
restoring rewinds admin actions and readings, and expired evidence is not recoverable
from a compact checkpoint. Rehearse restore on a disposable copy first.

Restore uses the same verified copy, into the database path:

```sh
systemctl stop msxp-tracker
cd /opt/msxp/app && old=private/vps/replaced-$(date -u +%Y%m%dT%H%M%SZ) && mkdir "$old"
mv private/vps/tracker.sqlite3* "$old"/   # Database, -wal, -shm and marker.
cp "$old"/tracker.sqlite3.multi-alpha.json private/vps/
sudo -u msxp .venv/bin/python tools/backup_database.py private/backups/tracker-<UTC>.sqlite3 private/vps/tracker.sqlite3
systemctl start msxp-tracker
```

**Restore drill (disposable first).** Practise on a throwaway database, never by
replacing production:

```sh
cd /opt/msxp/app
sudo -u msxp .venv/bin/python tools/backup_database.py private/backups/tracker-<UTC>.sqlite3 private/restore-drill/tracker.sqlite3
sudo -u msxp env PYTHONPATH=src .venv/bin/python -m exp_tracker.server --db private/restore-drill/tracker.sqlite3 --port 18765 --public-only &
pid=$!
for _ in $(seq 30); do curl -sf http://127.0.0.1:18765/api/players >/dev/null && break; sleep 1; done
curl -s http://127.0.0.1:18765/api/players | head -c 300; echo
kill "$pid"          # SIGTERM; sudo relays it to the server.
wait "$pid" || true  # Returns only once the server has exited.
rm -r private/restore-drill
```

Also compare the drill copy's fingerprint with its backup's. Use the production
procedure above only for a real recovery.

## Operations

- `journalctl -u msxp-tracker -f`
- The proposed unit includes `--retention-24h`; see [reporting, boundary allowances and expired admin targets](24h-retention.md).
- `systemctl stop msxp-tracker`: SIGINT finalizes runs; allow up to 60 s.
- The manual-EXP admin server is started by hand only when needed, then reached by
  tunnel: `ssh -L 8766:127.0.0.1:8766 vps`, then `sudo -u msxp .venv/bin/python -m
  exp_tracker.admin_server --db private/vps/tracker.sqlite3 --port 8766`.
- Developer diagnostics run the same way: a separate
  `python -m exp_tracker.server --diagnostic-dashboard` on another loopback port.

Not prepared here: Cloudflare in front of the API, rate limiting (stock Caddy has
none), off-host backup automation, monitoring and alerting.

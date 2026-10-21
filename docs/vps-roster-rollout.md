# Schema-11 VPS roster rollout

Operator runbook for the **existing Ubuntu 26.04 VPS**, `/opt/msxp/app`, service
`msxp-tracker`, API `127.0.0.1:8765`. These are proposed commands, **not executed
deployment steps**. Each live/migration/retention gate needs explicit operator
approval. Do not run `install-ubuntu.sh`: it reinstalls the legacy JSON unit and
Caddy configuration. Do not use `/opt/msxp/bench` as production.

The reported offline benchmark exercised 15 channels/30s, six workers, staggered
capture and resident neural OCR; resident Tesseract used about 18% less sampled CPU,
with zero capture/OCR failures or skipped deadlines. This is supplied benchmark
evidence, not a new measurement or validation of live Twitch capacity.

## Readiness findings and integration

- The legacy unit uses JSON, omits the performance flags and enables retention at
  startup. **Do not start it against the migrated database.** The opt-in
  `deploy/msxp-tracker-roster.conf` replaces only its launch command and adds an
  identical offline startup preflight. The installer never installs this drop-in.
- `--db-roster` requires schema 11 **and** a bootstrap receipt, an ordinary owned
  multi-alpha marker, exclusive coordinator lease and free port. Startup never
  applies the schema-11 migration or adopts identities. JSON startup refuses a
  bootstrapped roster. Fresh schema 11 alone is insufficient.
- Imported cadence/authorization/visibility/automatic settings need review. Bootstrap
  does not change 20s rows into the benchmark's 30s rows. Existing automatic channels
  require adoption receipts; matching Twitch/character names prove nothing.
- The required pinned OCR interpreter is
  `/opt/msxp/app/private/rapidocr/.venv/bin/python`. `--check` verifies its presence,
  FFmpeg/Streamlink and resident Tesseract identity, **not** neural package/model
  health. Check pinned packages and preserve the benchmarked model cache separately.
- The base unit's `msxp` user, private-only writable path, SIGINT and mixed kill mode
  remain. The drop-in allows 180s for draining, treats coordinator exit 130 as a
  clean stop, disables automatic restart and defaults to a 600s trial. The main
  coordinator holds the writer lease; workers never become database writers.
- Caddy stays unchanged: only GET `/api/players` and its existing descendants are
  forwarded; the tracker still validates routes. Admin/developer paths and port
  8766 stay private. CORS is exactly `https://msxp.pages.dev`; no preview origins.
- Retention defaults **off**. Missing `/etc/msxp/roster.env`, a missing chosen DB,
  missing marker, unbootstrapped DB, occupied lease or occupied port blocks startup.
  The marker lock is local to a machine: it cannot prevent Windows/VPS history forks.

Actual host readiness remains blocked on choosing the authoritative history,
reviewing its migration, checking the installed unit/dependencies/permissions and
authorizing a single-writer cutover. Nothing here changes an installed service.

## 1. Read-only inventory

Windows PowerShell, from this reviewed checkout (adjust only explicitly chosen paths):

```powershell
Set-Location H:\Desktop\codex\msclassic-vps-rollout
$python = 'H:\Desktop\codex\msclassic-twitch-exp-tracker\.venv\Scripts\python.exe'
$env:PYTHONPATH = "$PWD\src"
$source = Read-Host 'Absolute path of authoritative Windows database to inspect'
$config = Read-Host 'Absolute path of its current JSON config (if not already roster-managed)'
& $python tools/adopt_automatic.py --db $source inspect
# Only for an already-bootstrapped schema-11 source:
& $python tools/db_streamer_roster.py --db $source inspect
Get-CimInstance Win32_Process | Where-Object CommandLine -Match 'multi_alpha.py|admin_server' |
  Select-Object ProcessId,CommandLine
```

On Ubuntu, inventory only; do not stop/start or migrate anything yet:

```bash
cd /opt/msxp/app
git status --short; git rev-parse HEAD
systemctl cat msxp-tracker
systemctl show msxp-tracker -p ActiveState -p MainPID -p User -p Group -p FragmentPath -p DropInPaths
ss -ltnp | grep -E ':(8765|8766)\b' || true
pgrep -af 'multi_alpha.py|admin_server' || true
ls -ld /opt/msxp/app/private /opt/msxp/app/private/vps
find private/vps -maxdepth 1 -name '*.sqlite3*' -printf '%M %u:%g %p\n'
# Choose the existing VPS DB independently; do not assume it matches Windows.
VPS_DB=/opt/msxp/app/private/vps/tracker.sqlite3
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/adopt_automatic.py --db "$VPS_DB" inspect
```

An absent VPS database/marker is an inventory result, not permission to create one.
Compare IDs, selections, adoption state, last attempts and running coordinators.
Resolve any independently written VPS history before choosing Windows as authority;
there is no automatic merge. Do not print credential file contents. Windows can deny
marker reads while capture holds its lease: wait for an approved stop, never bypass it.
The reviewed release must contain schema-11 roster/adoption, retention, both resident
OCR modes, staggered scheduling and the historical accounting fixes. Do not run an
older VPS checkout against the transferred DB. The adoption guide's former "future
roster" section is superseded by `database-streamer-roster.md`; retention docs describe
storage policy, not permission to turn it on during this rollout.

## 2. Consistent backup and disposable migration rehearsal

These commands write **only a new rehearsal directory**. `snapshot` uses SQLite's
backup API, includes committed WAL and copies the ordinary marker. Never copy a live
`.sqlite3` with `Copy-Item` or `cp`. `backup_database.py` alone does not copy a marker.

```powershell
$trial = Join-Path $PWD ('private\rollout-' + (Get-Date -Format yyyyMMdd-HHmmss))
New-Item -ItemType Directory $trial | Out-Null
$copy = Join-Path $trial 'rehearsal.sqlite3'
& $python tools/adopt_automatic.py --db $source snapshot --output $copy
if ($LASTEXITCODE -ne 0) { throw 'Snapshot failed; do not continue' }
& $python tools/adopt_automatic.py --db $copy inspect
```

If an intended existing automatic channel lacks an adoption receipt, first create
`$trial\mappings.json`: a JSON array with exactly `channel`, numeric `character_id`,
current `character` label and historically verified `name` per approved channel.
Use inspection IDs and reviewed footage/operator evidence, never username inference.
Already adopted channels must not be remapped. Optional copy-only adoption:

```powershell
& $python tools/adopt_automatic.py --db $copy preview --mappings "$trial\mappings.json" `
  --reason 'Operator reviewed historical identity for rollout rehearsal' --preview "$trial\adoption.json"
# STOP and review the printed identities, floors and preserved history before apply.
$review = Get-Content "$trial\adoption.json" -Raw | ConvertFrom-Json
& $python tools/adopt_automatic.py --db $copy apply --preview "$trial\adoption.json" `
  --confirm ('adopt-existing:' + $review.fingerprint.Substring(0,16)) --backup "$trial\before-adoption.sqlite3"
```

For schema 9/10, or schema 11 **without** a bootstrap receipt, rehearse the roster
bootstrap. For an already managed schema-11 source, skip this block and preserve its
roster. Choose the automatic subset explicitly; an empty array imports manual mode.

```powershell
$automaticChannels = @() # Fill only with reviewed, already-adopted logins.
$autoArgs = @()
foreach ($channel in $automaticChannels) { $autoArgs += @('--automatic-channel', $channel) }
& $python tools/db_streamer_roster.py --db $copy preview --config $config @autoArgs `
  --reason 'Reviewed roster settings and selected identities for VPS rehearsal' --preview "$trial\roster.json"
# STOP and review identities, IDs, every row's flags/cadence and fingerprint.
$review = Get-Content "$trial\roster.json" -Raw | ConvertFrom-Json
& $python tools/db_streamer_roster.py --db $copy apply --preview "$trial\roster.json" `
  --confirm ('bootstrap-roster:' + $review.fingerprint.Substring(0,16)) --backup "$trial\before-roster.sqlite3"
& $python tools/db_streamer_roster.py --db $copy inspect
if ($LASTEXITCODE -ne 0) { throw 'Roster rehearsal failed' }
```

Every preview/apply command must succeed; do not continue on a nonzero exit. Apply
creates a NEW verified pre-change backup and is atomic. A preview is bound to its
database path and content: **never reuse the rehearsal preview on another file**.

## 3. Validate identities, roster and permissions

Compare pre/post inspection: all existing streamer/character IDs, selections,
sessions, manual corrections and adopted identity receipts must survive. Bootstrap
adds policy/audit state, not earned EXP. Automatic verification may remain pending
until independent live frames arrive. A conflict/hold is not permission to clear it.

Use the existing local admin portal on the **copy** to review all settings. Pause
every channel except the explicitly authorized 1–2 for the initial trial. Set their
cadence to 30s if that is the approved target, and review authorization, automatic
identity, rendition, timeouts, neural-level evidence and crop saving. Do not assign a
character from its Twitch login. Example Windows copy-only portal:

```powershell
& $python -m exp_tracker.admin_server --db $copy --port 8890
# Open http://127.0.0.1:8890; Ctrl+C after reviewing/testing the copy.
```

Rehearsal settings do not alter the final snapshot. Repeat approved settings on the
final VPS candidate before starting. Existing-roster rows must also be reviewed.

## 4. Ubuntu offline preflight (no Twitch connections)

Transfer a **rehearsal** snapshot plus marker to a new private directory using the
same transfer procedure as section 5, with `rehearsal` in its name. Do not point a
coordinator at it without `--check`. Preserve the existing pinned environment; do
not reinstall or upgrade packages during rollout. Use Bash for the Ubuntu blocks:

```bash
cd /opt/msxp/app
.venv/bin/python -m pip check
sudo -u msxp private/rapidocr/.venv/bin/python -m pip check
sudo -u msxp private/rapidocr/.venv/bin/python -c 'from importlib.metadata import version; expected={"rapidocr":"3.10.0","onnxruntime":"1.31.0","psutil":"7.2.2","Pillow":"12.3.0"}; actual={p:version(p) for p in expected}; print(actual); assert actual==expected'
command -v ffmpeg streamlink tesseract
tesseract --version
REHEARSAL=/opt/msxp/app/private/rollout-rehearsal/tracker.sqlite3 # Choose the new copy.
sudo -u msxp test -r "$REHEARSAL"
sudo -u msxp test -w "$REHEARSAL"
sudo -u msxp test -w "$REHEARSAL.multi-alpha.json"
sudo -u msxp test -w "$(dirname "$REHEARSAL")"
namei -l "$REHEARSAL"
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/multi_alpha.py \
  --db-roster "$REHEARSAL" --port 18865 --continuous --public-only \
  --cors-origin https://msxp.pages.dev --workers 6 --stagger-capture \
  --resident-neural --resident-tesseract --ocr-python /opt/msxp/app/private/rapidocr/.venv/bin/python \
  --stop-after-seconds 600 --exit-after-capture --check
timeout 90s sh deploy/offline-check.sh
```

If Streamlink is installed only in the app venv, use `.venv/bin/streamlink --version`
instead of requiring it on the interactive shell PATH. The service's Python resolves
its installed capture module. Retain the already warmed model cache and verify the
service user can read it. Missing packages/models, libtesseract/CLI mismatch, forbidden
paths or unexpected old hooks/drop-ins are blockers, not reasons to weaken preflight.
`offline-check.sh` uses disposable SQLite and spare loopback ports with the unchanged
Caddyfile; it does not modify the installed proxy. No admin route is added.

## 5. Approval gate: coordinated final handoff

**Only after explicit cutover approval:** stop Windows capture with Ctrl+C and wait
for summaries/process exit. Stop its admin/repair writers too. Confirm the inventory
process list; disable any independent launcher/restart job. Stop any existing VPS
coordinator through its owning service/session. Keep both stopped throughout transfer
and migration. Do not infer writer absence from a stale heartbeat alone.

```powershell
# In the same reviewed PowerShell session, after the source writer has exited:
$final = Join-Path $trial 'final.sqlite3'
& $python tools/adopt_automatic.py --db $source snapshot --output $final
if ($LASTEXITCODE -ne 0) { throw 'Final snapshot failed' }
& $python tools/adopt_automatic.py --db $final inspect
Get-FileHash -Algorithm SHA256 $final,"$final.multi-alpha.json"
$vps = Read-Host 'Approved SSH destination user@host'
# Explicit operator transfer only; unique staging directory, not the production path.
$stage = '/tmp/msxp-cutover-' + (Get-Date -Format yyyyMMddHHmmss)
ssh $vps "umask 077; mkdir '$stage'"
scp $final "$final.multi-alpha.json" "${vps}:${stage}/"
# If bootstrap is needed, also transfer a COPY of the legacy JSON; it contains no credentials.
if ($config) { scp $config "${vps}:${stage}/legacy.json" }
```

Ubuntu commands, after verifying `msxp-tracker` is stopped and Windows stays stopped:

```bash
sudo systemctl stop msxp-tracker
systemctl show msxp-tracker -p ActiveState -p MainPID
ss -ltnp | grep ':8765\b' || true
pgrep -af 'multi_alpha.py' || true
cd /opt/msxp/app
RELEASE=CHOOSE-REVIEWED-COMMIT-ALREADY-PRESENT-LOCALLY
sudo git cat-file -e "$RELEASE^{commit}" # Release transfer/update requires separate approval.
test -z "$(sudo git status --porcelain)" || exit 1
sudo git switch --detach "$RELEASE" # Approved stopped-service cutover only; no fetch/reset/clean.
STAGE=/tmp/msxp-cutover-CHOOSE-THE-TRANSFERRED-TIMESTAMP
sha256sum "$STAGE/final.sqlite3" "$STAGE/final.sqlite3.multi-alpha.json" # Must match Windows.
DEST=/opt/msxp/app/private/cutover-$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -o msxp -g msxp -m 0750 "$DEST"
DB="$DEST/tracker.sqlite3"
sudo test ! -e "$DB" && sudo test ! -e "$DB.multi-alpha.json" || exit 1
sudo install -o msxp -g msxp -m 0640 "$STAGE/final.sqlite3" "$DB"
sudo install -o msxp -g msxp -m 0640 "$STAGE/final.sqlite3.multi-alpha.json" "$DB.multi-alpha.json"
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/adopt_automatic.py --db "$DB" inspect
sudo -u msxp sqlite3 -readonly "$DB" 'PRAGMA user_version; PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT COUNT(*),MAX(attempted_at) FROM diagnostic_attempts;'
```

Do not delete/reuse the old VPS database, its WAL/SHM or its marker. Use the new
directory and keep the stopped Windows original. If schema/roster migration is still
needed, create a portable bootstrap JSON from the transferred JSON (same reviewed
rows; replace only its database path), then make a **new destination-bound preview**.
If missing historical adoption is required, approve `$DEST/mappings.json` first and
run this optional block **before** creating the roster preview:

```bash
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/adopt_automatic.py --db "$DB" preview \
  --mappings "$DEST/mappings.json" --reason 'Reviewed final historical identities' --preview "$DEST/adoption.json"
# STOP and review this destination-bound adoption plan before applying.
TOKEN=$(sudo -u msxp .venv/bin/python -c 'import json,sys; print("adopt-existing:"+json.load(open(sys.argv[1]))["fingerprint"][:16])' "$DEST/adoption.json")
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/adopt_automatic.py --db "$DB" apply \
  --preview "$DEST/adoption.json" --confirm "$TOKEN" --backup "$DEST/before-adoption.sqlite3"
```

Bootstrap only if not already roster-managed:

```bash
sudo install -o msxp -g msxp -m 0640 "$STAGE/legacy.json" "$DEST/legacy-source.json"
sudo -u msxp .venv/bin/python - "$DEST/legacy-source.json" "$DEST/legacy.json" "$DB" <<'PY'
import json,sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
value['database']=sys.argv[3]
with open(sys.argv[2],'x') as out: json.dump(value,out,indent=2)
PY
AUTO=() # Explicit reviewed/adopted subset: pairs of --automatic-channel LOGIN, or manual mode.
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/db_streamer_roster.py --db "$DB" preview \
  --config "$DEST/legacy.json" "${AUTO[@]}" --reason 'Approved final VPS roster bootstrap' --preview "$DEST/roster.json"
# STOP and review the new plan before applying.
TOKEN=$(sudo -u msxp .venv/bin/python -c 'import json,sys; print("bootstrap-roster:"+json.load(open(sys.argv[1]))["fingerprint"][:16])' "$DEST/roster.json")
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/db_streamer_roster.py --db "$DB" apply \
  --preview "$DEST/roster.json" --confirm "$TOKEN" --backup "$DEST/before-roster.sqlite3"
```

Never transfer/apply a Windows preview. Already bootstrapped candidates skip the
entire bootstrap block. Any failure stops this procedure before service installation.

## 6. Bounded live trial, only after capture approval

Review/pause the final candidate's roster through the loopback admin portal before
starting the coordinator. Ubuntu: `sudo -u msxp env PYTHONPATH=src .venv/bin/python
-m exp_tracker.admin_server --db "$DB" --port 8766`. Windows operator tunnel:
`ssh -N -L 8890:127.0.0.1:8766 user@host`, then open `http://127.0.0.1:8890`.
Do not proxy admin through Caddy. Stop the admin process after review.

After approval, install the opt-in files (never overwrite an existing reviewed env
file without reviewing it). Set `MSXP_DATABASE` to the exact `$DB` above. Keep the
600s limits, `MSXP_RETENTION=` and initially `MSXP_TWITCH_STATUS=`. Optional Twitch
status requires existing local `TWITCH_CLIENT_ID`/`TWITCH_CLIENT_SECRET` in
`/etc/msxp/msxp.env`; never copy Windows credentials in the database bundle.

```bash
sudo install -d -o root -g msxp -m 0750 /etc/msxp
sudo test ! -e /etc/msxp/roster.env || exit 1 # Otherwise inspect/edit the existing file deliberately.
sudo install -o root -g msxp -m 0640 deploy/msxp-roster.env.example /etc/msxp/roster.env
sudoedit /etc/msxp/roster.env
sudo install -d -m 0755 /etc/systemd/system/msxp-tracker.service.d
sudo install -m 0644 deploy/msxp-tracker-roster.conf /etc/systemd/system/msxp-tracker.service.d/20-roster.conf
sudo systemd-analyze verify /etc/systemd/system/msxp-tracker.service
sudo systemctl daemon-reload
systemctl cat msxp-tracker # Verify merged command, sandbox, exact DB, no retention, no competing overrides.
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/db_streamer_roster.py --db "$DB" inspect
sudo systemctl start msxp-tracker # Still NOT enabled for boot; preflight precedes capture.
timeout 660s journalctl -u msxp-tracker -f
```

The timer stops **scheduling** after 600s; in-flight work drains before exit. Allow
up to the service's 180s shutdown budget. Do not start a replacement until MainPID
is zero and workers have exited. Failed trials remain stopped (`Restart=no`).

From another operator shell while the trial is running:

```bash
systemctl show msxp-tracker -p MainPID -p CPUUsageNSec -p MemoryCurrent -p TasksCurrent
vmstat 1 10
curl --max-time 10 -sS http://127.0.0.1:8765/api/players
curl --max-time 10 -sS -D - -o /dev/null -H 'Origin: https://msxp.pages.dev' https://API_HOSTNAME/api/players
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/db_streamer_roster.py --db "$DB" inspect
# Use the exact new directory printed as 'Private capture logs' in this trial's journal:
sudo -u msxp .venv/bin/python tools/summarize_capture_run.py private/multi-alpha/runs/CHOOSE-TRIAL-RUN
```

Require fresh `attempted_at`/runtime heartbeat, increasing committed attempts, correct
IDs/identity states (holds remain held), 30s cadence, zero skipped deadlines and
capture/OCR/persistence failures, acceptable CPU/RAM without sustained swap, matching
card/history publication clocks and exact CORS. Initial 503 warming is expected;
persistent warming, growing publication age, worker failures, identity conflicts or
forced shutdown block promotion. Review resident Tesseract shutdown/queue metrics.
If a finished trial has closed its API, inspect SQLite/journal; do not restart just
to make a curl succeed. Keep its exit status and logs for review.

## 7. Production approval and rollback

Only after trial review and explicit production approval: restore the approved
roster scope through admin, leave retention off, edit `/etc/msxp/roster.env` to set
`MSXP_CAPTURE_LIMITS=` (unbounded), optionally `MSXP_TWITCH_STATUS=--twitch-status`,
and install a separate restart override:

```bash
printf '[Service]\nRestart=on-failure\nRestartSec=15\n' | sudo tee /etc/systemd/system/msxp-tracker.service.d/30-production.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl start msxp-tracker
# Repeat freshness/identity/resources checks before approving boot enablement:
sudo systemctl enable msxp-tracker
```

No Caddy/DNS reload or frontend change is needed. Review the merged service and
repeat checks after every restart. Leave all other launchers disabled.

Rollback starts by stopping/disabling the VPS tracker and confirming all writers
are gone. Do not downgrade code/schema or remove the roster drop-in to launch JSON
against a bootstrapped DB. If the VPS recorded **no new attempts or other history/
admin changes**, the untouched stopped Windows source can resume under its original
compatible mode after approval. Otherwise fix forward or return the **latest complete
VPS history**; never resume the stale Windows copy, merge SQLite files or use an
older backup as if no observations were lost:

```bash
sudo systemctl disable --now msxp-tracker
systemctl show msxp-tracker -p ActiveState -p MainPID
RETURN=/opt/msxp/app/private/return-$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -o msxp -g msxp -m 0750 "$RETURN"
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/adopt_automatic.py --db "$DB" snapshot --output "$RETURN/tracker.sqlite3"
sudo -u msxp sha256sum "$RETURN/tracker.sqlite3" "$RETURN/tracker.sqlite3.multi-alpha.json"
# Create an operator-owned, protected transfer directory; do not relax private/ permissions.
RETURN_STAGE=$(mktemp -d /tmp/msxp-return-XXXXXXXX)
sudo install -o "$(id -un)" -g "$(id -gn)" -m 0600 "$RETURN/tracker.sqlite3" "$RETURN_STAGE/tracker.sqlite3"
sudo install -o "$(id -un)" -g "$(id -gn)" -m 0600 "$RETURN/tracker.sqlite3.multi-alpha.json" "$RETURN_STAGE/tracker.sqlite3.multi-alpha.json"
printf 'Return staging directory: %s\n' "$RETURN_STAGE"
```

On Windows, transfer into a **new** directory; compare both hashes to Ubuntu:

```powershell
$returned = Join-Path $PWD ('private\returned-' + (Get-Date -Format yyyyMMddHHmmss))
New-Item -ItemType Directory $returned | Out-Null
$returnStage = Read-Host 'Return staging directory printed on Ubuntu'
scp "${vps}:${returnStage}/tracker.sqlite3" "${vps}:${returnStage}/tracker.sqlite3.multi-alpha.json" $returned
$returnDb = Join-Path $returned 'tracker.sqlite3'
Get-FileHash -Algorithm SHA256 $returnDb,"$returnDb.multi-alpha.json"
& $python tools/adopt_automatic.py --db $returnDb inspect
& $python tools/db_streamer_roster.py --db $returnDb inspect
$ocr = 'H:\Desktop\codex\msclassic-twitch-exp-tracker\private\rapidocr\.venv\Scripts\python.exe'
$resume = @('--db-roster',$returnDb,'--port','8765','--continuous','--public-only',
  '--cors-origin','https://msxp.pages.dev','--ocr-python',$ocr,'--workers','6',
  '--stagger-capture','--resident-neural','--resident-tesseract',
  '--stop-after-seconds','600','--exit-after-capture')
& $python tools/multi_alpha.py @resume --check
# Only after explicit return-to-Windows capture approval, and successful preflight:
& $python tools/multi_alpha.py @resume
```

The Windows port must be free; keep the VPS disabled. Start only after approval.
Schema 11 stays schema 11. If returning to older evidence is unavoidable, explicitly
approve and record that data loss; keep the newer complete branch for diagnosis.

## 8. Separate backup/restore and retention approvals

Do not enable retention or the existing backup timer as a side effect of cutover.
The backup unit hardcodes `private/vps/tracker.sqlite3`; it would back up the wrong
file if the reviewed path differs. Rehearse and approve its path override first.

```bash
# Consistent explicit backup and restore drill; source remains untouched.
BACKUP=/opt/msxp/app/private/backups/roster-$(date -u +%Y%m%dT%H%M%SZ).sqlite3
DRILL=/opt/msxp/app/private/restore-$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -o msxp -g msxp -m 0750 "$(dirname "$BACKUP")" "$DRILL"
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/adopt_automatic.py --db "$DB" snapshot --output "$BACKUP"
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/adopt_automatic.py --db "$BACKUP" snapshot --output "$DRILL/tracker.sqlite3"
sudo -u msxp chmod 0640 "$BACKUP" "$BACKUP.multi-alpha.json" "$DRILL/tracker.sqlite3" "$DRILL/tracker.sqlite3.multi-alpha.json"
sudo -u msxp cmp "$BACKUP.multi-alpha.json" "$DRILL/tracker.sqlite3.multi-alpha.json"
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/adopt_automatic.py --db "$DRILL/tracker.sqlite3" inspect
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/db_streamer_roster.py --db "$DRILL/tracker.sqlite3" inspect
# Capture readiness on the restored pair: free spare port, no capture/network/writes.
sudo -u msxp env PYTHONPATH=src .venv/bin/python tools/multi_alpha.py \
  --db-roster "$DRILL/tracker.sqlite3" --port 18865 --continuous --public-only \
  --cors-origin https://msxp.pages.dev --workers 6 --stagger-capture \
  --resident-neural --resident-tesseract --ocr-python /opt/msxp/app/private/rapidocr/.venv/bin/python \
  --stop-after-seconds 600 --exit-after-capture --check
# Read-only reports; then deliberate deletion ONLY in this drill copy:
sudo -u msxp env PYTHONPATH=src .venv/bin/python -m exp_tracker.retention --db "$DB"
sudo -u msxp env PYTHONPATH=src .venv/bin/python -m exp_tracker.retention --db "$DRILL/tracker.sqlite3" --apply
```

Backups for resuming capture need the matching marker and reviewed configuration
alongside the SQLite snapshot; protect them and keep off-host recovery copies under
a separately approved policy. Both snapshot commands verify SQLite integrity/FKs and
copy the matching marker; `cmp`, inspection and capture preflight must all succeed
before the retention rehearsal modifies the restored copy. The legacy SQLite-only
backup unit omits the marker. Keep `--check`: never start capture from the drill
while another coordinator owns this tracking history.
After separate backup approval, `sudo systemctl edit msxp-backup.service` can use
the same reviewed DB and existing snapshot CLI (paste this override, not a new unit):

```ini
[Service]
EnvironmentFile=/etc/msxp/roster.env
ExecStart=
ExecStart=/bin/sh -c 'mkdir -p private/backups && exec .venv/bin/python tools/adopt_automatic.py --db "$${MSXP_DATABASE}" snapshot --output "private/backups/roster-$(date -u +%%Y%%m%%dT%%H%%M%%SZ).sqlite3"'
ExecStartPost=
```

The reset disables the legacy DB-only expiry command; these paired backups do not
auto-delete. Approve a storage/off-host/expiry budget before enabling the timer.
Validate the merged backup unit, then explicitly test/enable it:
`sudo systemd-analyze verify /etc/systemd/system/msxp-backup.service`,
`sudo systemctl daemon-reload`, `sudo systemctl start msxp-backup.service`, inspect
the new DB/marker pair, then `sudo systemctl enable --now msxp-backup.timer`.
Test restored IDs, retained display, schema, FK/integrity, rolling totals and public
API on a spare loopback port with **no coordinator**. Restore does not merge newer
attempts; keep the whole replaced directory, including WAL/SHM, while stopped.

```bash
sudo -u msxp sqlite3 -readonly "$DRILL/tracker.sqlite3" 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
sudo -u msxp env PYTHONPATH=src .venv/bin/python -m exp_tracker.server \
  --db "$DRILL/tracker.sqlite3" --port 18765 --public-only --cors-origin https://msxp.pages.dev
# In another shell: curl --max-time 10 -sS http://127.0.0.1:18765/api/players
# Ctrl+C closes only this read-only drill server.
```

After a successful drill and explicit retention approval, stop the tracker cleanly,
take a verified recovery snapshot, set `MSXP_RETENTION=--retention-24h`, and restart
the **same roster service**. Inspect `Retention SQLite`, `Retention files` and
`Retention postponed` messages. This enables irreversible raw-evidence expiry, not
a strict DB-size cap. All readers/admin tools must support schema 11 and compact
checkpoints. Never run standalone retention `--apply` on the live database.

## Local validation

The deployment regression tests execute the drop-in's expanded preflight arguments
against disposable 13-channel databases with mocked tools/native workers. They cover
optional Twitch status, unchanged IDs/data/marker, missing DB/marker, missing bootstrap,
busy lease/port and schema-10 refusal without migration. No live Twitch/VPS connection,
frontend modification, service installation or production migration was performed.
Ubuntu systemd/Caddy validation remains an operator check; WSL access is denied in
this managed Windows environment.

Windows results: **122 passed, 0 skipped (0 sample skips)**. The six-module run
(`test_deploy_roster`, `test_db_streamer_roster`, `test_automatic_adoption`,
`test_backup_database`, `test_staggered_schedule`, `test_resident_tesseract`) passed
120 tests in 87.84s under a 180s subprocess timeout. The `test_server.py` selection
`-k 'cors or public_only'` passed two tests in 0.23s (54 deselected) under 60s.
All runs used `python -m pytest -n 0`, disposable workspace temporary directories
and the existing Windows venv. Nine of those checks specifically cover this drop-in.
All seven PowerShell blocks parse; `git diff --check` is clean. Bash/systemd/Caddy
execution was not validated locally; Git Bash also could not start in this sandbox.
No complete saved-history sweeps or live rollout were run.

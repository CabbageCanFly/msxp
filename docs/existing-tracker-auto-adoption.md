# Automatic tracking on an existing multi-alpha database

After identity approval, the [database-managed roster](database-streamer-roster.md)
can import these settings once and replace routine JSON/startup-channel arguments
with protected live admin changes. Adoption/level-floor tools also support schema 11.

This is an explicit operator workflow, not an automatic upgrade. The same owned
database can run manual and automatic channels together, at their configured 20s
intervals, using the existing scheduler, serialized writer, resident OCR worker,
60-attempt rotation and optional 24h retention. No Twitch broadcast resets or new
downloads are introduced. The public URLs and character IDs remain unchanged.

**Do not run the modifying/live steps until the changes have been reviewed and the
operator has authorized a controlled stop of the existing writer.** Development
tests never access that database. An occupied writer lease or port is a refusal,
not an instruction to terminate another process.

The existing tracker has thirteen authorized Twitch channels, port **8766** and
configured **20-second** intervals. Its login is **`streamer_a`**, not `streamer_a`. The
operator has already renamed that character to **`CharA`** through the admin portal
and updated its JSON assignment to `"character": "CharA"`. Inspect the database to
confirm that label and obtain the numeric ID; this guide never assumes an ID.

The shortest post-merge path is: inspect and review; make a consistent disposable
copy; rehearse approval; stop the original coordinator with operator authorization;
preview/apply adoption on the original; preflight and activate only `streamer_a`;
verify, then separately approve retention and expand the automatic subset.
**Merge** installs code but does not adopt identities, enable automation or restart
the running process. **Adoption** records explicit identity approval. **Activation**
requires channel flags on launch. **Restart** reuses persisted selections and history.

## What adoption approves

Each mapping names a channel, its exact selected character ID and old label, and
the reviewed in-game name. A label such as `Main` is ambiguous: the operator must
review footage/records and affirm that its accumulated history belongs to the
named character. Two OCR names alone cannot prove historical ownership.

Adoption renames that existing ID through the audited rename API when needed. It
does not merge IDs, select another character, create placeholders, close sessions,
add EXP baselines, rewrite readings/corrections/invalidations, or rebuild frozen
history. A name already used by another character in the same channel is refused.
Review that exceptional conflict separately; never merge histories to bypass it.
This command maps the currently selected legacy character. Review other saved
legacy aliases through the existing audited rename workflow before expecting OCR
to reuse those IDs; unknown aliases are not inferred from level/EXP or joined by
similar spelling.
If the saved label already equals the reviewed name (`CharA` -> `CharA`), adoption
records approval only: no rename audit, duplicate character or history reset is
created. The same applies to other correctly named channels. A mismatched alias
still requires explicit historical-identity review; never infer the mapping from
a newly observed name or its level/EXP.

Schema 9 is migrated to 10 inside the adoption transaction; schemas 10 and 11 remain
at their existing version. Schema 11 adds the optional database-managed roster.
Existing level floors and checkpoints are preserved. Legacy raw OCR maxima are
not imported as validated floors. Existing manual level assertions and the normal
two-frame arithmetic-supported level policy still apply. Review any suspect legacy
level assertion before enabling, using the separate level-floor repair procedure
where applicable; adoption is not historical data repair.

The pre-change SQLite backup is mandatory. Migration, reviewed renames and receipts
commit together or roll back together. The existing ownership marker is **unchanged**:
SQLite receipts authorize the separate existing-database mode, avoiding a two-file
commit. New trial-mode ownership/path/channel/worker/retention restrictions remain.

## 1. Read-only inspection and a disposable rehearsal

Run from this worktree in PowerShell. Python and models may be reused read-only from
the original checkout. These commands are for the operator after review; they are
not run against the user's database during development.

```powershell
$repo = '<branch checkout>' # Copy rehearsal before merge.
Set-Location $repo
$main = '<your msxp folder>'
$python = "$main\.venv\Scripts\python.exe"
$ocr = "$main\private\rapidocr\.venv\Scripts\python.exe"
$env:PYTHONPATH = "$PWD\src"
$db = "$main\private\multi-alpha\live-local.sqlite3"
$config = "$main\private\multi-alpha\live-local.json"
$trial = Join-Path $repo "private\existing-auto-rehearsal-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory $trial | Out-Null

# Read-only database/marker inspection; no migration, OCR or network.
& $python tools/adopt_automatic.py --db $db inspect

# Consistent SQLite backup, including committed WAL data, to a NEW destination.
# Source is read-only; writes only the disposable copy and its copied marker.
# If Windows refuses access to a locked marker, wait for an authorized stop.
$copy = Join-Path (Resolve-Path $trial) 'rehearsal.sqlite3'
& $python tools/adopt_automatic.py --db $db snapshot --output $copy

# Copy configuration without editing the original. Preflight does not capture.
$settings = Get-Content $config -Raw | ConvertFrom-Json
if ($settings.port -ne 8766) { throw 'Review the actual tracker port before proceeding' }
$configured = @($settings.streams | Where-Object { $_.channel -eq 'streamer_a' })
if ($configured.Count -ne 1 -or $configured[0].character -cne 'CharA') {
  throw 'Review the streamer_a assignment; do not guess or edit the original config here'
}
$settings.database = $copy
$settings.port = 8879
$settings | ConvertTo-Json -Depth 10 | Set-Content "$trial\config.json" -Encoding utf8
& $python tools/adopt_automatic.py --db $copy inspect
```

`snapshot` copies a consistent database and its ordinary ownership marker. It does
not copy capture logs or media. Keep existing retained-file evidence in place;
rehearse SQLite behavior on this copy without pointing retention-file cleanup at
the original capture directories. Never copy just a live `.sqlite3` file with
`Copy-Item`, and never copy/rename its WAL files manually.

Create the private mapping from **inspection output**, after reviewing historical
identity. The example below deliberately stops if the expected login/label is absent.
You may approve one channel now or review all thirteen up front; approval does not
activate capture or automation. Do not guess a legacy identity or numeric ID.

```powershell
$inspectionJson = & $python tools/adopt_automatic.py --db $copy inspect
if ($LASTEXITCODE -ne 0) { throw 'Database inspection failed' }
$inspection = ($inspectionJson -join "`n") | ConvertFrom-Json
$characterRows = @($inspection.channels | Where-Object { $_.channel -eq 'streamer_a' })
if ($characterRows.Count -ne 1 -or $characterRows[0].character -cne 'CharA' -or $characterRows[0].character_id -lt 1) {
  throw 'Review the selected streamer_a ID/name; this example requires the saved label CharA'
}
$mapping = @([ordered]@{
  channel = $characterRows[0].channel
  character_id = $characterRows[0].character_id
  character = $characterRows[0].character
  name = 'CharA'
})
ConvertTo-Json -InputObject $mapping -Depth 10 |
  Set-Content "$trial\mappings.json" -Encoding utf8

& $python tools/adopt_automatic.py --db $copy preview `
  --mappings "$trial\mappings.json" --preview "$trial\preview-copy.json" `
  --reason 'Reviewed streamer_a history and confirmed the existing CharA character identity'

# Read the printed mappings, current floors, tracking state, history counts,
# source schema, fingerprint and confirmation token before continuing.
$review = Get-Content "$trial\preview-copy.json" -Raw | ConvertFrom-Json
$confirm = 'adopt-existing:' + $review.fingerprint.Substring(0,16)
& $python tools/adopt_automatic.py --db $copy apply `
  --preview "$trial\preview-copy.json" --confirm $confirm `
  --backup "$trial\before-copy-adoption.sqlite3"

# Read-only startup preflight: model/FFmpeg/authorization/ownership/port checks,
# no model startup, network capture, database migration or new capture logs.
& $python tools/multi_alpha.py --config "$trial\config.json" --existing-tracker `
  --automatic-existing-channel streamer_a --ocr-python $ocr --workers 3 `
  --log-root "$trial\runs" --check
```

For fully offline capture rehearsal, replace the copied config's sources with
explicit saved local videos (`source: file`, `file: ...`) and then use the same
coordinator flags with `--exit-after-capture`. Keep recordings private. `--check`
alone does not test OCR accuracy. Do not launch the Twitch configuration on the copy
without separate capture approval: it contains the same thirteen authorized sources.

Inspection, snapshot and adoption preview do not claim the coordinator lease or port.
They may be used while capture runs if the read-only marker/database access succeeds;
on Windows a locked marker may require waiting for an authorized stop. An original
preview will become stale if capture writes afterward. Coordinator `--check` in
existing mode **does** probe its writer lease and configured port even though it is
read-only: the original's port 8766/lease must be free. The disposable config's 8879
and copied marker permit that check while the original remains running.

## 2. Adopt the original, only after an authorized stop

Stop only the intended writer through the operator's normal procedure. No command
here stops a process. Preserve the original configuration, database, marker and logs.
Generate a **new** preview against the stopped original: a copy's preview cannot be
applied to another path. If readings/selection/metadata change, the preview is stale
and must be reviewed again. Hard-linked, unowned, trial and incompatible databases
are refused. Never hand-edit the marker to bypass a refusal.

```powershell
# Only after the reviewed code is merged and the operator has stopped the writer:
# Return to the original checkout; its same config/database/port are retained.
Set-Location $main
$env:PYTHONPATH = "$main\src"

& $python tools/adopt_automatic.py --db $db preview `
  --mappings "$trial\mappings.json" --preview "$trial\preview-original.json" `
  --reason 'Reviewed streamer_a history and confirmed the existing CharA character identity'

# Review again, then explicitly supply the printed token.
$review = Get-Content "$trial\preview-original.json" -Raw | ConvertFrom-Json
$confirm = 'adopt-existing:' + $review.fingerprint.Substring(0,16)
& $python tools/adopt_automatic.py --db $db apply `
  --preview "$trial\preview-original.json" --confirm $confirm `
  --backup "$trial\before-original-adoption.sqlite3"
```

`apply` is the modifying step. It requires the OS writer lease and SQLite exclusive
writer access, verifies the complete reviewed snapshot, makes/verifies a consistent
backup, and then commits. Receipts retain the preview/backup hashes, old mapping,
reason and ownership metadata; renames have their normal audit entries. An exact
retry after a successful commit reports `duplicate: true` without applying again.
After a failed attempt, retain its backup and choose a new backup filename for retry.
No automatic backup promotion or server rollback is performed. Schema-9 binaries
cannot be assumed to read schema 10; rehearse rollback separately before activation.

## 3. Enable one channel, expand and restart

With the writer stopped and port 8766 free, use the original configuration and
database. Its requested intervals stay 20s. The command below captures from all
enabled configured channels, but enables name OCR/switching **only for streamer_a**.
The remaining channels keep their normal numerical tracking. No `--interval` override
or config edit is needed. Leave retention **off for this brief identity verification**:
adoption alone does not prune old readings, and recovery evidence stays available.

```powershell
& $python tools/multi_alpha.py --config $config --existing-tracker --automatic-existing-channel streamer_a `
  --ocr-python $ocr --workers 3 --continuous --check

# LIVE: run only with operator capture approval. Short bounded rollout first.
& $python tools/multi_alpha.py --config $config --existing-tracker --automatic-existing-channel streamer_a `
  --ocr-python $ocr --workers 3 --continuous `
  --max-attempts 6 --exit-after-capture
```

Retain any existing `--public-only`, CORS and Twitch-status flags required
by your normal launch command. Rehearsal logs stay under the disposable worktree's
private paths. After merge and the authorized stop, launching from the main checkout
uses its normal private log root; never share it with another running instance.
The homepage, `/stream/CHANNEL`, character-query URLs
and OBS overlay continue using the same database and configured port.

The first adopted identity needs two strong distinct frames no more than 120s apart.
Pre-adoption/manual frames cannot supply a vote. Duplicate, failed, unreadable,
conflicting, multi-HUD and stale evidence cannot confirm it. During this one-time
verification, readings are held; prior history remains visible. A different name
twice creates/selects a separate ID rather than relabelling the reviewed history.
After verification, unreadable names do not themselves hold plausible numerical
progress. A conflicting name holds immediately; its second independent frame can
switch. A returning name reuses its channel-owned ID. Floors and arithmetic checks
can still withhold a numerically invalid confirming capture.

Inspect the private `capture.jsonl` files and the read-only adoption report:

```powershell
& $python tools/adopt_automatic.py --db $db inspect
Get-ChildItem private/multi-alpha/runs -Recurse -Filter capture.jsonl |
  Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName
```

Evidence is in `character_name` (or nested `identity_hold.evidence` /
`level_hold.evidence`), with raw text, score, pixel hash, timing and provenance.
`automatic_selection` records committed switches. `level_policy` records floors and
proof; the adoption report includes durable verification/conflict state. Held EXP
is never moved later to another character. Check IDs, floors, current readings and
per-character public history before expanding.

Approve additional channels with a fresh mapping/preview/apply while stopped, then
repeat `--automatic-existing-channel CHANNEL` for each desired automatic channel.
Once all thirteen are reviewed, a supported PowerShell launch pattern is:

```powershell
$autoChannels = @('streamer_a','streamer_b') # Include streamer_b only after inspecting and approving it.
$autoArgs = @()
foreach ($channel in $autoChannels) { $autoArgs += @('--automatic-existing-channel', $channel) }
& $python tools/multi_alpha.py --config $config --existing-tracker @autoArgs --ocr-python $ocr `
  --workers 3 --continuous --check
# After approval, remove --check to capture. Use --max-attempts for a bounded trial.
```

Restart with the same flags. Persisted selection wins over stale configuration labels
for adopted channels, including after switching to B. Disabling is an ordinary
controlled restart with the relevant channel flags omitted (keep `--existing-tracker`
when using the other checkout's config path); no data/IDs are removed
and stale config labels do not switch the selection back. If an activated channel
has unresolved identity verification/conflict, disabling it is refused: resume that
channel's automatic verification first. Approved but never activated channels may
remain manual. Existing level-floor protection remains active when automation is off.

## 4. Separately approve and enable 24h retention

Retention is wanted for normal continuous operation, but is independent of adoption
and automatic identity. Neither merge, adoption nor launch without `--retention-24h`
prunes history. Before first activation on this accumulated database, review the
[retention policy](24h-retention.md), run its read-only report, and rehearse on a
separate disposable copy. Keep the adopted rehearsal copy intact for comparison.

```powershell
# Read-only reports: no lease/port claim, migration, snapshots or pruning.
# These may run while the coordinator is active if SQLite read access succeeds.
& $python -m exp_tracker.retention --db $db
& $python -m exp_tracker.retention --db $copy

# A separate NEW copy; only this copy is modified by the next --apply command.
$retentionCopy = Join-Path $trial 'retention-rehearsal.sqlite3'
& $python tools/adopt_automatic.py --db $copy snapshot --output $retentionCopy
& $python -m exp_tracker.retention --db $retentionCopy --apply
& $python tools/adopt_automatic.py --db $retentionCopy inspect
```

Standalone reporting/application protects unfinished runs. The owning coordinator
knows its actual active runs and can also expire abandoned unfinished runs, so its
initial sweep may compact more than the standalone report. Inspect that case on the
copy using saved local-video coordinator rehearsal before authorizing cleanup. Do
not run standalone `--apply` on the original, or point copy log cleanup at its logs.

Retention checkpoints the eligible old prefix and saves the last usable observed
status per character/UTC day **before** granular deletion. This is at most one
daily row, not a promise of one for every date: absent or ineligible readings create
no snapshot. Older diagnostic evidence/trusted observations and eligible owned,
inactive capture/operator logs and known OCR crops are removed. Unowned files and
active evidence are protected. Existing pre-retention logs may remain unless they
meet the ownership/recognition rules. **Daily snapshots are storage-only**, not
public historical graph points; no missing observations are fabricated.

The granular cutoff is about 24h plus 5m, with complete-run boundaries, hourly
maintenance and bounded batches. At 20s, the normal run/hour allowance is about
25h25m; protected runs or backlogs can retain more. This is not a strict database
size cap: character/session identities, corrections, invalidation/rename/adoption
audits and daily statuses persist. Pruning also limits later source-level repairs,
so retain the pre-adoption backup and approve cleanup separately.

After identity verification, dry-run/copy review and an operator-controlled stop,
preflight and resume the original thirteen-channel tracker with retention enabled:

```powershell
& $python tools/multi_alpha.py --config $config --existing-tracker `
  --automatic-existing-channel streamer_a --ocr-python $ocr --workers 3 `
  --continuous --retention-24h --check

# LIVE: only after approval. Same database, port 8766 and configured 20s intervals.
& $python tools/multi_alpha.py --config $config --existing-tracker `
  --automatic-existing-channel streamer_a --ocr-python $ocr --workers 3 `
  --continuous --retention-24h
```

Preserve normal public-only/CORS/status flags as needed. All enabled channels are
captured; only explicitly approved automatic channels receive name OCR. Expand by
repeating their channel flags after their own approval. Retention is database-wide,
not limited to the automatic subset. The original coordinator must be stopped for
both existing-mode `--check` and the actual restart because they require its lease
and port; a read-only retention report does not require that stop.

## Future database-managed roster (not implemented here)

A later protected admin portal should persist streamer additions, tracking/pause,
independent directory visibility and validated capture settings in SQLite. New
streamers should not need a known character name; OCR discovery and the same
two-frame attribution policy would establish a separate initial baseline. The
coordinator would reconcile those changes safely without restart.

This adoption path is compatible with an additive implementation: receipts/state
reference persistent streamer and character IDs, independent of the JSON label or
process, and are already stored in SQLite. Keep those IDs, histories, identity risk,
floors and audits when moving settings/authorization to database-owned policy; do
not rebuild accounts or interpret JSON removal as permission to delete history.
Preserve separate capture authorization and public visibility, validate settings at
the admin boundary, and serialize roster changes with the existing writer. Drain
in-flight work before changing a lane's ownership/settings; immutable run/session
bindings and receipt-time checks still apply. New unknown characters must not use
legacy adoption to guess historical mappings. Existing approved channels should
carry their approvals forward without repeating destructive initialization.

The current CLI reads JSON and snapshots lanes at startup; changing this needs an
explicit future roster/scheduler feature. No dynamic configuration, admin endpoint,
new roster schema or UI is introduced in this branch.

## Limits and validation

Full-frame localization is mandatory for automatic channels. HUD caching is refused
while any existing channel is automatic, including mixed configurations. After all
automatic channel flags are omitted, normal manual-mode caching can resume. One shared resident worker serves
eligible name crops; manual channels do not acquire name OCR just because another
channel is automatic. No second video acquisition is added. Late/skipped work still
uses receipt times and distinct pixel evidence, never scheduled time as a vote.

The 20s setting is a requested cadence, not a capacity guarantee. The existing
scheduler skips missed deadlines instead of queuing frames, serializes SQLite and
protects each channel's in-flight capture. Thirteen channels at 20s/full-frame scans
need separate capacity validation; this branch does not tune workers/localization
or run a benchmark matrix. Start with a small automatic subset and inspect actual
cadence, stage times, skipped deadlines and resource summaries.

Two independent images cannot defeat a systematic wrong name or distinguish a
streamer's own play from a watched gameplay feed. Such associations remain separate
and auditable, not global identity proof. Repeated wrong names can create separate
records subject to the existing per-channel discovery cap. Adoption/decision audits
are durable; 24h retention is not an absolute database-size cap.

Performance-branch integration contract: preserve the per-lane
`args.automatic_characters` / `args.character_names` flags, fresh full-frame name
provenance and receipt-time checks, one shared resident worker and serialized emit.
The integration adds a keyed state read/update per automatic attempt, not another
OCR pass or download. Missed deadlines must never manufacture identity votes.

`tests/test_automatic_adoption.py` uses generated thirteen-channel databases, mocked
Twitch attempts and real coordinator/persistence paths. It covers schema 9/10,
preservation, rollback/retry/locks, mixed operation, expansion, restart/disable,
rotation, retention and interrupted identity verification. No live Twitch or original
database test is implied by those results.

Validation on generated/disposable databases: the combined adoption/automation/trial/
scheduler run passed 112 tests; retention/repair/Store/public integration passed 167
with two environment skips. The broader regression run passed **2,621**, skipped
**122** (118 unavailable private fixtures, two OS-link restrictions, two sandbox
socket restrictions). The three real localhost HTTP tests separately passed with
sockets permitted; the frontend suite passed all **74**. These are correctness
results, not Twitch/VPS performance measurements.
One concurrent-viewer socket test was excluded from the sandboxed broader command
and included in that successful real-HTTP rerun. The final adoption/trial/scheduler
rerun after checking disabled-mode caching passed **82**, zero skips.

Operator-readiness follow-up: **112 passed, zero skips** across adoption, trial,
scheduler, retention and daily snapshots. New regressions use an inspected,
already-admin-renamed `streamer_a` / `CharA` identity and another correctly named
character: approval makes no rename/history changes, and activation, expansion,
switch/restart and disabling retain the right IDs. All eight PowerShell blocks
parse without execution. The broader results above are from the initial
implementation; this documentation/test-only follow-up does not rerun that suite.

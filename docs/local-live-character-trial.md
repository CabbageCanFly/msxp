# Isolated local Twitch character trial

Existing accumulated multi-channel databases use the separate explicit
[existing-tracker adoption workflow](existing-tracker-auto-adoption.md). The trial
restrictions below are unchanged; do not use trial flags to bypass adoption.

Run these commands **after review**. No live capture was performed for this milestone.
Leave the existing main tracker running: never edit its config, use its DB/port,
restart it or kill its processes. Start with **one authorized channel**, six captures
at a 15–60-second interval, using a new private trial folder in this feature worktree.

## Activation and isolation

The previous blockers were the coordinator's file-only name restriction,
`shadow_capture.prepare` requiring a local file for standalone name review, and its
standalone identity label calling `args.file.resolve()`. Capture, full-frame HUD
extraction, resident OCR, identity policy and transactional attribution already work
with Twitch. No other file-only guards were found in those runtime paths.

`--automatic-characters` stays **off by default**, implies name/resident OCR, and uses
the existing two-frame policy: exact matching names, confidence >= .90, one fresh
full-frame HUD, distinct decoded pixels, increasing receipt times <=120 seconds apart.
The first mismatch holds; the second creates/selects a streamer-scoped character and
supplies its baseline. Returning names reuse IDs. Histories never merge. Unreadable
names keep plausible numeric tracking active unless an actual conflict remains.
Level floors, normal level-ups and rolling-window gap accounting remain intact. There
are no new Twitch broadcast resets or session-boundary heuristics.

Twitch name/automatic mode requires:

- DB under this checkout's `private/character-live-trial/TRIAL/`, config beside it,
  explicit `--log-root` inside that trial. Canonical paths are checked; hard-linked
  DB aliases are refused.
- A **new** DB/marker or the exact prior live-trial DB/marker, with the same channels
  and automation mode. Unowned, nonautomatic and offline-auto DBs cannot be adopted.
  An existing trial must already have the current schema: restart never migrates it.
- One or two authorized Twitch channels, a **15–60-second** interval (any value,
  including decimals; omitted means the normal 15-second default), one worker, no HUD
  cache, and **no 24h retention**. Names reuse the EXP/level resident on every eligible frame.

### Why 15–60 seconds

Two-frame confirmation needs consecutive name frames at most `CONFIRM_GAP_SECONDS`
(120 s) apart (`character_automation.independent`, `IdentitySuggestions.observe`).
The ceiling is half that gap, `LIVE_TRIAL_INTERVAL` in `tools/multi_alpha.py`, so
scheduler and capture jitter cannot make confirmation impossible. At exactly 60 s one
missed attempt lands at the 120-second edge and may reset the streak; shorter
intervals tolerate misses better. The floor is the normal 15-second default; the
general 5..300 bound for non-trial tracking is unchanged. With two channels and one
worker, attempts run serially: if one attempt takes longer than about half the
interval, slots are skipped (never queued) and reported as skipped deadlines.
15–30-second live cadence has been exercised only in the operator's local 30-second
trial and in mocked tests, not measured for resources; start at 30–60 s.
- A separate port; the normal default 8765 is refused. Preflight probes localhost
  availability before DB/marker initialization. This is not a reservation: a later
  bind race can initialize the disposable DB, but capture still never starts.

OS coordinator leases and SQLite write transactions remain in force. `--check` also
checks the trial lease, performs only a local port bind (no remote requests/capture),
and writes no DB, marker or logs. It does not initialize OCR models. Standalone
`shadow_capture --character-names` can review authorized Twitch without a DB;
persisted automatic attribution belongs in this isolated coordinator workflow.
`--character-names` alone supplies review/holds, not automatic selection.

## 1. Create the isolated configuration

Open a **new PowerShell terminal** and reuse the existing environments read-only.
Do not install into or edit them. Replace `AUTHORIZED_LOGIN` with a permitted channel.

```powershell
Set-Location 'H:\Desktop\codex\msclassic-character-name-ocr'
$original = 'H:\Desktop\codex\msclassic-twitch-exp-tracker'
$python = Join-Path $original '.venv\Scripts\python.exe'
$rapid = Join-Path $original 'private\rapidocr\.venv\Scripts\python.exe'
$env:PYTHONPATH = (Resolve-Path src).Path
$trialName = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$trial = Join-Path (Get-Location).Path ('private\character-live-trial\' + $trialName)
New-Item -ItemType Directory -Path $trial -ErrorAction Stop | Out-Null
$database = Join-Path $trial 'tracking.sqlite3'
$config = Join-Path $trial 'config.json'
$logs = Join-Path $trial 'logs'
$channels = @('AUTHORIZED_LOGIN') # Start with one; a NEW trial can configure up to two.
$streams = @($channels | ForEach-Object {
  [ordered]@{ channel=$_; character='PendingOCR'; source='twitch'; authorized=$true
    interval=60; count=6; timeout=20; ocr_timeout=10; max_age=15  # interval: 15..60
    experimental_neural_level=$true; quality='best' }
})
[ordered]@{ database=$database; port=8879; streams=$streams } |
  ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $config -Encoding UTF8
Get-Content -LiteralPath $config
```

The real character name is **not** needed beforehand. Before discovery, accepted
placeholder readings stay with that placeholder; they are never moved into the real
character's history. Existing FFmpeg, Tesseract, Streamlink and local RapidOCR models
are required. Model downloads remain disabled.

## 2. Check without capture

```powershell
$captureArgs = @('--config',$config,'--automatic-characters','--resident-neural',
                 '--ocr-python',$rapid,'--log-root',$logs,'--exit-after-capture')
& $python tools/multi_alpha.py @captureArgs --check
if ($LASTEXITCODE -ne 0) { throw 'Preflight failed; leave the main tracker alone and inspect the error.' }
```

Expect `Preflight passed; no connections, database changes or capture started.` The
port probe only binds localhost. If 8879 is occupied, choose another port in **this
trial config** and repeat; do not terminate whoever owns it. Check verifies paths,
tools and settings, not model inference or the channel's current broadcast status.

## 3–4. Start the bounded test and open the feature site

Only after review and successful preflight:

```powershell
Start-Process 'http://127.0.0.1:8879/streams'
& $python tools/multi_alpha.py @captureArgs
```

Refresh after `Directory: http://127.0.0.1:8879/streams` appears. The character page is
`/stream/CHANNEL`; experimental diagnostics are `/dashboard/CHANNEL`, all on **8879**.
The main viewer remains on its existing port. Six captures normally take about five
minutes plus final work. Two channels run serially and may finish later/skip slots.
`--exit-after-capture` closes the feature server at the end. For this first test do
not add `--continuous`, `--retention-24h`, `--hud-cache-seconds`, `--twitch-status` or
extra workers. This is still experimental diagnostic tracking, not trusted ingestion.

## 5. Inspect evidence, committed decisions and resources

`automatically selected NAME / character ID / session ID` prints only after SQLite
commits. Candidate names, suggestions and private switch intents are provisional;
a failed commit can leave a log intent without a durable decision receipt.

```powershell
& $python -m exp_tracker.manual_admin --db $database --channel $channels[0] inspect
@'
import json, sys
from exp_tracker.store import Store
with Store(sys.argv[1], read_only=True) as s:
    for r in s.db.execute('SELECT event_id,character_id,run_id,receipt_json FROM automatic_character_events ORDER BY recorded_at DESC LIMIT 10'):
        print(json.dumps(dict(r), indent=2))
    for r in s.db.execute('SELECT c.id,c.label,g.level,g.proof_json FROM characters c LEFT JOIN character_level_guard g ON g.character_id=c.id ORDER BY c.id'):
        print(json.dumps(dict(r), indent=2))
'@ | & $python - $database
```

Private `capture.jsonl` files retain raw name OCR/confidence, hashes, source channel,
HUD provenance, numeric checks, timings and suggestions, including held evidence:

```powershell
$attempts = @(Get-ChildItem -LiteralPath $logs -Recurse -File -Filter capture.jsonl |
  ForEach-Object { Get-Content -LiteralPath $_.FullName | ForEach-Object { $_ | ConvertFrom-Json } } |
  Where-Object type -eq 'attempt' | Sort-Object attempted_at)
$attempts | ForEach-Object {
  $raw = $_; $hold = $_.level_hold.reason
  if ($raw.level_hold) { $raw = $raw.level_hold.evidence }
  if ($raw.identity_hold) { $hold = $raw.identity_hold.hold_reasons -join ','; $raw = $raw.identity_hold.evidence }
  [pscustomobject]@{ At=$_.attempted_at; Current=$_.current; Name=$raw.character_name.evidence.name
    Score=$raw.character_name.evidence.score; NameStatus=$raw.character_name.evidence.status
    Hold=$hold; SwitchIntent=$raw.automatic_selection.name; Frame=$raw.character_name.evidence.pixel_sha256 }
} | Format-Table -AutoSize
$attempts[-1].resources | Format-List
```

`identity_hold`/`level_hold` with `current: false` withhold that reading. `candidate`
can be below the switching threshold; even strong OCR needs two independent eligible
frames. SQLite's receipt confirms the association, while public numerical projection
still applies its own EXP/level checks. Raw candidates are not earned EXP. With a
known character and plausible numbers, temporary unreadability should not pause EXP.

Final terminal/per-attempt resource summaries report sampled process-tree CPU seconds,
one-core CPU percentage and peak aggregate RSS, plus actual cadence, stage durations,
failures and skipped deadlines. These measure this feature process and its children,
**not the main tracker**. Name `raw.request_metrics` includes resident queue/bridge
timing. Sampling can miss brief child work. Stop the feature if it causes resource
pressure; leave the main tracker unchanged. No live performance claims are made here.

## 6–7. Stop safely or restart the same test

Let the bounded capture finish or press **Ctrl+C in the feature terminal only**.
The coordinator closes its capture/OCR children, writes summaries where possible,
releases the lease and closes its HTTP server. Do not broadly kill Python processes.
Retain DB, marker, config and logs together; evidence does not expire in this trial.

```powershell
# Same variables/config, same TEST database; another bounded run:
& $python tools/multi_alpha.py @captureArgs --check
if ($LASTEXITCODE -ne 0) { throw 'Restart preflight failed' }
& $python tools/multi_alpha.py @captureArgs
```

Each restart uses a new log directory/run and retains selected IDs, open session and
level floors. The placeholder config does not reset a discovered name. A brief
restart is not a broadcast boundary. Same-character gaps retain the rolling-window
rules. Changing channel set/automation mode requires another **new** trial folder/DB.

## Offline evidence and limitations

Tests feed generated PNGs and mocked OCR/network responses through the real
Twitch-source `capture_attempt` and coordinator, using disposable SQLite. They cover
placeholder discovery, unreadability, stable names, A→B→A/ID reuse, two-channel
separation, restart, verified 67→70 return, network failure, stale/duplicate/multiple
HUD frames, nonautomatic compatibility, ownership/schema refusals, writer locks and
port collisions. Earlier real saved-footage/performance evidence remains in the
[OCR guide](character-name-ocr.md) and [review](character-name-ocr-review.md).

Final verification: **241 focused passes**, zero skips; **2,552 broader passes,
121 skips**. Those skips are 118 unavailable private-fixture checks, two OS link
restrictions and one sandbox loopback restriction. One additional concurrent-viewer
socket test was excluded. All six PowerShell blocks above parsed successfully
without execution. `git diff --check` passes. No frontend files changed.

```powershell
python -m pytest -q tests/test_live_character_trial.py tests/test_character_identity.py tests/test_multi_alpha.py tests/test_identity_coordinator.py tests/test_autonomous_characters.py tests/test_shadow_capture.py tests/test_rolling_gap_windows.py tests/test_store.py
python -m pytest -q -n 8 -k 'not test_concurrent_viewers_share_one_projection_per_publication'
```

At interval I, clean switching takes roughly **I–2I seconds plus capture/OCR**
from an arbitrary switch time (60–120 s at I=60, 15–30 s at I=15). Failures/unreadable HUDs can extend this indefinitely.
Freshness proves local decoder age, not broadcast age/PTS. A streamer watching another
feed can associate its visible character with that streamer. Repeated confident OCR
mistakes can create wrong records or poison a floor; ASCII/UI-layout limits remain.
Keep evidence; use [exceptional floor repair](level-floor-repair.md) only after review.
No Twitch connection, main DB access, deployment or production migration was performed.

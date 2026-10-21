# Exceptional validated-level repair

The [isolated local Twitch trial](local-live-character-trial.md) deliberately leaves
retention off so short-trial recovery evidence remains available. Never point its
commands or this exceptional repair workflow at the running main tracker.

The existing local manual-admin CLI now supports `repair-floor preview` and
`repair-floor apply`. This recovers a reviewed false floor, such as repeated 87 OCR
blocking a character actually at 67. Capture, ingestion, public APIs and the Admin
browser never invoke it. Schema remains **10**. This milestone uses disposable DBs only.

Stop **all writers** and rehearse on a consistent private copy first. Use SQLite's
backup API, not a copy of just the main file from a running WAL database. Preserve
the coordinator marker beside its DB. Previews bind to the exact database path and
contents: a rehearsal-copy preview cannot authorize another database.

## Preview and apply

Find the exact channel, selected character ID and name with `inspect`. The first
version only repairs the explicitly selected character. These are examples for a
**disposable** DB; substitute reviewed timestamps and EXP, not these example values.

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path # Use this checkout, including with the shared OCR virtualenv.
python -m exp_tracker.manual_admin --db private/recovery/disposable.sqlite3 --channel alpha inspect

python -m exp_tracker.manual_admin --db private/recovery/disposable.sqlite3 --channel alpha repair-floor preview `
  --character-id 1 --character Alpha --since "2026-10-19T12:00:45Z" `
  --at "2026-10-19T12:02:00Z" --level 67 --exp 1000 `
  --reason "Reviewed original footage: repeated 87 OCR was actually level 67." `
  --preview private/recovery/repair.json

Get-Content private/recovery/repair.json
```

Preview opens the source read-only and rehearses the entire operation on a temporary
SQLite backup. The **new** private JSON file includes the exact old guard, decoded
proof, guard/proof SHA256 hashes, proposed numeric state, affected source identities
and original OCR values, conflicting active manual assertions and database digest.
It prints an explicit confirmation token containing the channel, ID, old/new levels
and fingerprint. Reasons require 15–250 characters and at least three words.
Optional `--percentage 12.34` is checked against EXP and the existing requirement
table. Unknown requirements remain an operator assertion.

`--since` is inclusive and must include both original false-floor frames (or the
manual proof), plus earlier conflicting evidence. `--at` is a corrected baseline
strictly after recorded captures, observations and session boundaries, no later than
now. It is not an earned-EXP observation.

Review the full JSON. Then paste the **actual printed token**, quoting its `>`:

```powershell
python -m exp_tracker.manual_admin --db private/recovery/disposable.sqlite3 --channel alpha repair-floor apply `
  --character-id 1 --character Alpha --preview private/recovery/repair.json `
  --confirm "repair:alpha:1:87->67:PRINTED_HASH" `
  --backup private/recovery/before-repair.sqlite3
```

Neither file is overwritten. Any committed DB change, including another channel's
capture, makes an unused preview stale; generate and review a new one. The tool does
not stop processes or alter configuration.

## Safety and audit

Apply acquires `multi_alpha`'s OS writer lease when its marker exists, then a fail-fast
SQLite `BEGIN EXCLUSIVE` writer transaction. WAL readers can continue; competing
writers cannot write during recovery. Legacy writers without a coordinator lease
must also be stopped. An occupied lease or SQLite write lock refuses the operation.

Before recovery writes, a second read-only connection creates the requested consistent
backup. Integrity, foreign keys and its full logical digest must match the preview.
The file SHA256 is recorded. An unavailable/invalid backup aborts recovery. A failed
attempt can leave a partial backup or valid pre-repair backup; inspect it and use a
new filename for retry. No repair data was committed.

One outer transaction performs these changes using the existing audit APIs:

1. Retract conflicting active manual assertions, retaining their append-only audit.
2. Invalidate explicit conflicting readings inside `[since, at)`. Candidate levels,
   saved level-policy evidence and existing arithmetic/level inference identify
   conflicts. Valid interleaved readings and valid manual point corrections survive.
   Raw OCR and original stored gains remain intact; public projections exclude bad
   evidence rather than rewriting it.
3. Finalize unfinished runs, end the old session and open a new session for the
   **same character ID/name**, with an explicit corrected manual baseline. Manual
   accounting boundaries prevent manufactured gains across the repair.
4. Deliberately delete/reinsert only this guard, clearing pending evidence. Keep the
   exact normal monotone UPDATE trigger installed. Ordinary OCR still cannot lower it.
5. Check SQLite integrity and foreign keys before committing everything together.

The durable baseline audit reason includes the human explanation, original level,
canonical old guard/proof hashes, preview fingerprint, backup SHA256 and invalidation
batch ID. The new proof carries the same receipt and `basis: manual_admin_repair`.
Preserve the private preview and backup: they contain the exact original proof and
pending evidence. Later legitimate level advances may replace the current proof,
but the manual audit survives.

Repeating the same confirmed preview returns `duplicate: true` and the original
receipt without another session, baseline, invalidation or backup. This also works
after retention or later level advancement. Exceptions roll everything back; true
crashes rely on SQLite WAL recovery. Tests inject exceptions, not physical power loss.
There is no generic undo for the whole repair: do not separately restore its bad
reading batch or undo its baseline as a substitute. Review the backup and complete
audit before any further recovery.

## Fail-closed limitations

- Only schema 10 with the exact normal monotone trigger is supported. No migrations
  occur. Wrong identity/selection, modified/stale preview, missing original independent
  frames/manual proof, invalid arithmetic, bad time boundaries and retry conflicts fail.
  Paths are canonicalized before acquiring the coordinator lease; hard-linked DB
  aliases are refused because their WAL and lease filenames can differ.
- **Any** retention state, trusted checkpoint or frozen daily row for this character
  refuses repair, even if some frozen history could be legitimate. The first version
  cannot prove or rebuild compacted totals. Expired or contradictory frozen history
  needs separately reviewed reconstruction from a trustworthy older backup. Do not
  delete checkpoints or replace only the guard to bypass this restriction.
- The existing 20,000-reading range limit bounds review. Missing/ambiguous evidence
  fails closed. Fingerprinting, rehearsal and backup examine the DB; this is offline
  maintenance, not a per-capture operation or a performance feature.
- The operator asserts the corrected name/numeric state belong together. This does
  not authenticate character ownership or repair unrelated EXP errors. Keep evidence.
  Repeated systematic bad OCR can establish another false floor; address its cause
  before resuming capture.

## Disposable verification

`tests/test_floor_repair.py` covers false 87 → actual 67, resumed captures, normal
non-regression, preserved public gains/history, interleaved valid frames, manual-only
floors, conflicting manual points/baselines, trusted observations, restart, subsequent
retention, full rollback after replacement, wrong identities, tampering, stale previews,
duplicates, unavailable backups, both writer locks, missing proof, old schema, altered
trigger and expired/frozen history. Existing coordinator, manual, invalidation and
retention regressions exercise unchanged defaults.

Final results on the feature worktree: **194 passed, 1 skipped** in the focused group;
**2,526 passed, 121 skipped** in the broader Python run; **57 passed**, zero skips in
the frontend checks. The broader skips are 118 unavailable private-fixture checks,
two OS link restrictions and one sandbox loopback restriction. One additional
concurrent-viewer socket test was excluded because the sandbox blocks it. The
hard-link refusal also passes a synthetic test. TEMP/TMP pointed to ignored workspace
storage. A separate CLI process retried the disposable repair and returned the same
audit with `duplicate: true`, without making another backup. `git diff --check` passes.

```powershell
python -m pytest -q tests/test_floor_repair.py tests/test_invalidations.py tests/test_manual_admin.py tests/test_autonomous_characters.py tests/test_multi_alpha.py tests/test_retention.py
python -m pytest -q -n 8 -k 'not test_concurrent_viewers_share_one_projection_per_publication'
node --test tools/product.test.mjs
```

Rolling-window help cleanup changes tooltip wording only: eligible gain is normalized
over the selected window duration; separate complete comparisons retain their existing
coverage requirement. Layout, styling, rate calculations and OCR defaults are unchanged.

# Character identity: pre-merge safety and performance review

The previous offline milestone was committed as `a657300`. The clean worktree was
rebased onto **local main `4ab2293`**, incorporating both the `790c273` percentage-context
fix and the opt-in eight-worker limit. No conflicts; the rebased milestone is
`b3ba305`. Main's checkout, running tracker, database and deployment files were not
modified. New review fixes remain uncommitted. No new schema migration or default flag.

## Safety findings and fixes

The existing two-frame switching transaction is retained. Exact names with score
>= .90, increasing receipt times <=120 seconds apart, distinct full-frame pixel hashes
and a unique fresh full-frame HUD establish a switch. The first different-name reading
remains held in the original run; the second is the new session's first baseline.
Return visits reuse the channel's character ID. No backfill, ID merge or cross-session
EXP subtraction was introduced.

Three narrowly scoped defects were fixed in `character_automation.py`:

- **Replayed policy receipts:** `guard_level` previously trusted an existing
  `level_policy` field. A saved level-67 receipt could consequently bypass a later
  level-68 floor when imported into a different run. New attempts now revalidate
  against the current floor. Exact already-stored retries remain idempotent;
  held numeric evidence stays excluded.
- **Uninformative arithmetic:** 0 EXP / 0% fits every level requirement. It no longer
  corroborates a lone level reader. Two independent frames with two agreeing level
  readers can still validate an initial zero baseline; otherwise wait for informative
  EXP. This is the same informative-support distinction used by existing projection.
- **Rename race:** an in-flight worker could retain its pre-rename reference while
  Store saw the new label. Such a stale reference now stops that lane before writing
  or recreating the previous name. Resume with a controlled coordinator restart.

Multi-level floor increases now also require two strong observations of the **selected
name**, in addition to matching, independent level/arithmetic evidence. This closes
the restart case where a new in-memory numeric anchor might otherwise accept an
unreadable-name level jump as a new baseline. Ordinary adjacent-level progress retains
its existing two-frame level validation and may proceed with unreadable names.

Other reviewed invariants:

| Boundary | Result |
| --- | --- |
| Name unreadable, plausible numbers, no ownership conflict | Continue ordinary tracking; no blanket name hold. |
| Known mismatch followed by missing names | Preserve risk through missing frames and restart; repeated returning A resolves it. |
| 60-attempt rotation | Same session and recorded link; confirmation can cross rotation; switch creates a fresh immutable binding. |
| Log flush failure | Whole SQLite switch rolls back; lane stops, other lanes continue. A private file can contain uncommitted intent. |
| SQLite COMMIT failure | A deferred foreign-key failure at COMMIT rolls back character/session/run/receipt together; retry succeeds. |
| Retention/restart | Floors and bounded decision receipts survive raw-evidence deletion. Expired decision retries fail closed if their baseline has expired. |
| Similar EXP across characters | Names drive switching; numerical similarity neither suppresses it nor merges ownership. |
| Old lower-level clip | Held with raw diagnostics; cannot lower floor or contribute public progression. Same-level lower EXP remains indistinguishable from some death/loss cases. |
| Systematically wrong name | Two repeated high-scoring errors can still create a mistaken association. The 16-record/channel cap limits creation, but is not correctness proof. |
| Same name on two channels / guest gameplay | Separate channel-scoped IDs. Visible-feed association is recorded; actual ownership is not proved. |
| Renames | Preserve ID, history and floor. Automatic mode uses exact in-game names, not arbitrary aliases; stop/restart around exceptional operator renames. |
| Schema compatibility | Read-only 3–9 supported; schema-10 migration remains additive and transactional. No schema-11 change. |

Default/feature-disabled databases have no level guards and retain existing behavior.
Once a character has an established floor, disabling automatic mode intentionally does
not remove it. Trusted `Store.ingest` also rejects lower levels and will not advance a
managed character above the floor by itself: diagnostic verification or a validated
manual assertion must advance it first. Do not silently move managed characters to a
legacy writer and expect that writer to implement the new confirmation workflow.

## Overnight/off-stream progression

The subsequent [rolling-window accounting clarification](rolling-window-gaps.md)
allows validated same-character gaps in sufficiently long windows. The earlier
5-minute overnight tests below still exclude an eight-hour interval. Broadcast-session
integration is not a prerequisite for this accounting policy and was not implemented.

Disposable tests establish level 67, then return eight hours later at level 70.
Two fresh selected-name observations and matching informative arithmetic raise the
floor to 70 automatically. The ID/history are unchanged. Tests assert the public card
shows 70 and the new EXP, and pace uses only the two accepted level-70 endpoints;
no level-67-to-70 offline gain is manufactured.

The tests distinguish two situations:

- **Explicit stream/session boundary:** end the old session through Store, then start
  the returning session. The character ID persists; the session ID changes.
- **Capture gap without an observed stream boundary:** preserve the existing session,
  start a fresh run and validate the return. A gap or process restart is not proof that
  the broadcast ended. Existing source/run/gap boundaries exclude the unobserved gain.

A separate brief-restart sequence preserves the session and validates normal 67→68
progress with temporarily unreadable names. Within-stream level-ups do not create new
sessions. If a multi-level jump's name remains unreadable, keep it pending until two
strong selected-name observations return; a single matching name cannot release it.

Live broadcast/session lifecycle detection remains outside this offline milestone.
Before deployment, connect an authoritative broadcast boundary (for example, a verified
new broadcast identifier) to existing session APIs. A timeout, one offline status
response or a coordinator restart should not alone be converted into a new stream.
No Helix/Twitch network request was used for these tests.

## Opt-in local Twitch activation follow-up

The [isolated Twitch trial guide](local-live-character-trial.md) supersedes the
earlier local-video-only activation restriction. The same full-frame two-vote policy,
numeric guards, writer transactions and level floors are reused; there is no cache
or broadcast reset. New path/marker/port/cadence safeguards isolate the main tracker.
Only mocked Twitch-source acquisition was exercised; previous real saved-frame and
CPU measurements below are historical, not live-Twitch performance measurements.

## Repairing a mistakenly established floor

Repeated wrong OCR can still poison a floor. Normal corrections, invalidation alone,
undo, clearing pending state and restarting **do not lower it**. That prevents an old
clip from becoming a convenient reset. The current admin UI cannot repair the guard.

A small exceptional recovery is possible without an administration framework. The
disposable test `test_offline_audited_floor_repair_recipe_is_atomic_and_preserves_history`
is an executable reference, including a failure injected halfway through recovery:

1. Keep the affected writer stopped during recovery. Make a consistent SQLite backup
   using SQLite's backup API; rehearse on that copy. Archive the exact guard row,
   proof/pending evidence, character/session IDs and a SHA256 in a private review bundle.
2. Review/invalidate the erroneous accepted readings using existing `Invalidations`;
   retract any erroneous active manual level assertions too. Do not erase source rows,
   renames, character IDs or earlier legitimate history. If raw evidence has expired,
   inspect retention/display/daily checkpoints as well; the simple recipe does not
   automatically rebuild already frozen incorrect history.
3. In **one Store transaction** on the offline copy, compare the guard against the
   reviewed row, apply the invalidations, finalize the active run, end/start a session
   for the same character, deliberately replace that one guard row and append an
   explicit manual baseline. Supply the exact new session ID at the boundary.
4. The replacement proof records `basis: manual_admin_repair`, the correction event ID,
   superseded level/guard hash and invalidation batch ID. The correction reason also
   retains the hash and batch reference. Preserve the private bundle containing the
   original proof; keep the monotone trigger installed. Normal captures cannot invoke
   this exceptional DELETE/INSERT replacement path.
5. Verify public level/EXP, current and historical pace, excluded readings, receipt
   links, restart and retention on the copy before any separately authorized promotion.

The test proves rollback leaves the old floor/audits untouched, successful replacement
keeps all source attempts/character IDs, the new valid capture resumes, and the repair
receipt survives reopening. The procedure is now supported by the exceptional
[preview/apply repair CLI](level-floor-repair.md), tested only on disposable databases.
It preserves valid interleaved evidence and refuses any compacted/frozen character
history. Expired/frozen bad history still needs additional review; do not promote a
guard-only repair with contradictory checkpoints.

## Offline performance measurements

Windows i7-13700K, processes pinned to four distinct P cores, Tesseract thread limit 1,
three workers, existing single resident RapidOCR. All files/DBs/scripts/results are
ignored under `private/character-name/premerge/`. Tests did not overlap timing phases.

Saved-frame experiment (`benchmark.py`, `benchmark.json`): five fixtures repeated over
15 synthetic lanes, four real name-bearing frames plus a missing-HUD negative. Frozen
input pixels enable comparison; actual full/region Tesseract localization, visual
levels, EXP and name inference still run. Cache seeds are prepared outside the phase;
this measures **warm geometry**. No FFmpeg, SQLite or publisher in this experiment.

| 15 jobs / three workers | Wall | Corrected sampled CPU | Peak tree RSS | Mean localization |
| --- | ---: | ---: | ---: | ---: |
| Full scan, pass 1 | 15.679s | 42.922 CPU-s | 628.87 MiB | 2.509s |
| Cached, 12 region reads + 3 negative full scans | 5.479s | 14.032 CPU-s | 446.82 MiB | .567s |
| Mixed, 9 region reads + 6 full scans | 9.885s | 25.578 CPU-s | 583.54 MiB | 1.316s |
| Full scan, pass 2 | 15.928s | 43.453 CPU-s | 629.18 MiB | 2.535s |

The mixed batch saves about 41% CPU over the mean full-scan batch. It is a cost
experiment, **not an enabled autonomous cache policy**. Cached name reads produce zero
switch-eligible votes; only the fresh full scans vote. New tests also prove cached
votes cannot clear a known conflict or pair with a fresh frame to establish a switch.
Region/full recognition can differ, as the earlier cache evaluation documents.
In this bounded warm-seed comparison all 15 EXP/level result tuples match the first
full pass, all 12 positive names are exact and all three negative jobs abstain in each
phase. This small same-frame parity result does not supersede the earlier moved-HUD
and competing-HUD counterexamples.

All phases used one model/worker command. Name queue waits were <.01ms in these
Tesseract-dominated phases. That does not eliminate contention: the earlier resident
burst experiment measured 108–149ms mean name waits with 3–4 callers, up to 172ms.
Timeout starts after lock acquisition. More workers can raise queue delay and memory;
the new 5–8 worker allowance is not a reason to choose that many on four VPS CPUs.

Full local-video coordinator experiment (`run15.py`, `offline15.json`,
`offline15-summary.json`): **15 lanes**, three original saved videos replicated five
times, two captures/lane at requested 60s, full localization, automatic identities,
three workers and a fresh disposable schema-10 DB. Local HTTP/publisher and SQLite
are included; no viewers, network acquisition or retention-sized database.

- **30/30 frames/attempts committed**, zero skipped deadlines or capture/OCR-process
  failures. Mean start interval **59.435s**, maximum **60.485s**. Mean work **6.884s**:
  capture/close 3.739s, localization 2.557s, neural .063s, visual level .481s,
  names .043s. Initial deadline staggering explains means slightly below 60s.
- **95.002s wall, 94.562 sampled CPU-s**, peak **601.25 MiB**. Short-lived child CPU
  can be undercounted; the frozen-frame figures subtract existing worker lifetime CPU.
- 28 unique-HUD name candidates: streamer_f 10, hefferheffer 10, Mawile 8, all matching
  provisional saved-source labels. One missing HUD and one multiple-HUD frame abstain.
  These are repeated sources, not 15 independently labeled broadcasts.
- **13** channels automatically move from bootstrap placeholders into separate named
  records on capture 2; 13 baselines become current. Two channels with initial negative
  frames remain held after only one usable name frame. Fifteen identity-held attempts
  retain their source numbers privately. No names/history are shared across channels.

The capture run preceded the final multi-level name corroboration check; its bootstrap
transitions have no existing level floor and do not exercise that new check. The final
regression suite does exercise it. Neither this run nor the warm-cache benchmark is a
naturally occurring same-stream character switch or a live VPS trial.

### VPS projection and recommendation

Applying the prior measured workstation→VPS factors (1.9× CPU, 1.6× non-capture wall)
to this full-scan coordinator run projects about **1.50 capture cores** at 15/60s and
**7.8s work/capture**, using the prior 2.75s Twitch capture estimate. Three workers
would be busy about **39s of every 60s each** (~65%). These are projections, not new
VPS measurements. Publisher/viewer load, network tails and realistic retention work
still need headroom. Workstation memory <650 MiB does not establish a VPS peak, but
does not suggest an 8-GB memory bottleneck. Eight workers remain unmeasured.

Recommend an initial controlled trial with **three workers, resident OCR, full scans,
60s cadence**; begin with a few authorized channels before scaling toward 15. There is
no measured need to weaken switch verification just to add a cache. Existing VPS
offline four-worker/60s measurements in `capture-performance.md` are supporting prior
evidence, not a test of this feature.

## Recommended cache strategy (not implemented)

Keep `--automatic-characters --hud-cache-seconds` rejected until the following paired
behavior has tests. The current cache's known competing-HUD blind window remains real.

1. Use cached geometry for ordinary EXP and cheap name reads at each capture. Refresh
   with a full scan at startup, on source/size/layout changes and periodically (start
   evaluation at 300s, stagger channels). Cached same-name evidence is observational
   only; it cannot confirm ownership, a switch or a multi-level floor increase.
2. A different name, existing numerical anomaly, unresolved conflict or pending
   confirmation prioritizes a **fresh full scan of that acquired frame before any
   attribution**. Re-extract fields if geometry changes. Do not repeat a full scan
   already performed on that frame, and recheck freshness after the extra work.
3. Count a vote only if that same frame's full scan is unique and its resulting name
   passes the existing quality checks. Missing/multiple HUDs clear the cache and keep
   suspect readings unavailable. Never let a cached unique region override that result.
4. Force the **next capture** to be a full scan too. Two fresh independent frames can
   then switch at the normal cadence; stale cache seeds never establish the decision.

Cheap checks plus escalation preserve typical 60–120s detection latency. If only a
300s periodic full check discovers a change, worst ordinary delay rises to roughly
60–360s plus work, and unavailable HUDs can delay indefinitely. A newly appearing
competing HUD with an unchanged name in the cached region can remain unseen for the
refresh window; that is a remaining ordinary-EXP attribution risk, not a safe ownership
guarantee. Accept/document that bounded risk explicitly before enabling this policy.

## Regressions and remaining trial prerequisites

After the clean rebase, **158 focused tests passed**. After the safety fixes, broader
`python -m pytest`: **2,453 passed, 120 skipped**, one additional loopback publisher
viewer test excluded by sandbox socket policy. Skips: 118 unavailable private fixtures,
one symlink-permission case, one existing loopback restriction. No failing test is
excluded as a product workaround. TEMP/TMP were set to the workspace's private temp
directory; the default Windows sandbox temp location is not writable.
Final autonomous safety suite: **33 passed**, zero skips. `git diff --check` is clean.

The new disposable sequences cover saved-receipt bypass, zero baselines, overnight
progress with/without an explicit session boundary, brief restart/normal level-up,
unreadable-name multi-level jumps, rename races, cached vote rejection, actual COMMIT
failure and audited repair rollback. Existing coordinator/projection tests cover
switch-back, rotation, retention and feature-disabled behavior.

Before a controlled deployment trial: independently review owner/name labels and
systematic OCR failures; rehearse schema-10 backup/rollback and the exceptional repair
on an appropriate copy; integrate verified stream boundaries; measure the authorized
VPS canary with full scans, publisher load and realistic retention. Keep live automation
disabled until that trial is authorized. No production migration/deployment, live
Twitch connection, UI project or broad OCR optimization was performed here.

Suggested commit: `fix(identity): revalidate level receipts and harden recovery boundaries`.

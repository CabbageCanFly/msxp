# Stationary EXP after a level-up

The automatic capture writer could indefinitely hold a valid new level when EXP
stopped increasing immediately after the level-up. This affects the persistent
level guard, before public API projection; restarting only the API does not fix it.

## Evidence and reproduction

An offline replay of the supplied `samples/level-up-sample.png` through the existing
HUD locator and OCR bridge read `1,437[0.14%]`, with neural level 57 at score
0.99839 using `neutral4`. Tesseract abstained. The screenshot is private and is not
committed. This is one local OCR observation, not a production accuracy measurement.

The pair's arithmetic is ambiguous: nearest-half-up fits level 57, while truncation
fits level 56. The previous accepted example was level 56 near 99.85%. When more
EXP arrives the pair can identify a unique level; a stationary pair stays ambiguous.

`character_automation.level_evidence()` projected each capture independently.
Without a unique arithmetic level or Tesseract agreement, a neural level requires
temporal confirmation, so this one-frame projection always returned pending. The
outer `guard_level()` already requires two distinct supporting captures, but never
received either as qualified evidence. It consequently kept returning
`unresolved_level_change` rather than starting its two-frame confirmation.

A disposable SQLite regression reproduces this using a validated level-56 floor
and repeated level-57 / 1,437 / 0.14% captures with distinct frame hashes. Before
the fix the first new capture was held as `unresolved_level_change`. Afterward it
is held as `level_confirmation_pending`; the second advances the floor to 57 and
the next stationary capture updates the public reading at 0.14%. No gain, character
switch, trusted observation or retrospective promotion is fabricated.

The supplied VPS extract confirms this failure mode: eleven held attempts retain
the validated level-56 floor and report `unresolved_level_change` despite neural
level 57 at scores above 0.96, with full pairs 1,437 / 0.14% or 1,441 / 0.14%.
The next shown attempt, 2,821 / 0.27%, finally reaches `level_confirmation_pending`.
Tesseract abstains in all twelve excerpts. Only these selected fields were
reviewed, not the complete production payloads or frame hashes; no raw logs are
committed. Synthetic regressions cover both stationary values at 15- and 40-second
cadences, including recreating the writer between the confirming captures.

## Narrow change and retained guards

The per-frame qualifier now also admits a pending, validated `neutral4` neural
level with score at least the existing 0.90 threshold, provided the complete
nonzero EXP/% pair is conditionally consistent with that level. This evidence is
labelled `single_neural_arithmetic`; it does not confirm a level on its own.

The existing outer guard still needs two distinct captures within 120 seconds.
The initial frame stays held, and duplicate frames, conflicting readers, weak or
invalid neural evidence, incomplete source crops, ambiguous HUDs, missing full
pairs and arithmetic contradictions cannot advance the floor. Character identity,
missing-requirement/percentage-only policy, monotone floors and trusted accounting
are unchanged. A repeated self-consistent OCR error remains a limitation of this
conditional evidence policy; repetition does not prove correctness.

Deploying this change requires a controlled restart of the capture tracker. Only
the writer's per-frame qualifier changed; the read-only API can keep running and
will refresh from the newly accepted database records. Other API changes deployed
alongside this fix may separately require an API restart.
No schema migration, production data rewrite or historical held-frame backfill is
performed. Nothing here starts capture, connects to Twitch or restarts the VPS.

## Local validation

The full Python run for the fix passed 2,882 tests with 120 skips: 119 unavailable
private fixtures in this isolated worktree and one Windows symlink permission check.
After the VPS extract, all 51 automatic-character tests passed, including the 18
targeted cases covering persistent confirmation across a fresh writer object,
stationary public EXP/level updates, and unchanged zero gained EXP.
The supplied screenshot was separately run through the local OCR pipeline above.
No frontend code changed, and no browser test or live VPS replay was performed.

## Weak level crops after a level-up

A subsequent streamer_d incident was different: the first two level-55 reads had
scores 0.8498 and 0.7927, below the existing 0.90 seed threshold. The level-54 floor
was retained until a later full EXP/% pair uniquely supported 55. The earlier
stationary-level fix was running; it does not bypass weak visual evidence.

The recognizer now makes at most one additional `neutral4` pass on the original
level crop when the trimmed orange badge yields a numeric candidate below 0.90.
It requires a visible margin on all four sides of the orange badge; touching an
edge withholds the retry. This prevents boosting the tested clipped-digit cases,
but a margin is not proof of a complete source image. Nonnumeric, missing-score
and already strong readings do not trigger a retry.

The wider read can replace the weak one only if both give the same numeric level
and the wider score reaches 0.90. It cannot change the initial numeric candidate.
A rejected or failed retry preserves the original level result and independent
EXP result. Successful replacements retain the original raw evidence under
`neural_level.tile_attempt`, validated at both capture bridge boundaries. The
replacement's inference/preprocessing times include both successful passes;
the existing bridge wall time includes unsuccessful retry work as well.

Both crops belong to one capture and count as one frame. EXP/% consistency,
freshness, crop checks, identity attribution, the persistent floor and the second
distinct-frame requirement are unchanged. No schema, API or trusted-accounting
change is needed. Deployment requires restarting `msxp-tracker` to reload its
resident OCR worker; the API can keep running. This does not backfill old holds.

### Offline validation and limits

Using the existing pinned recognizer, five supplied VOD screenshots yielded five
correct level-55 candidates at or above 0.90, compared with two before the retry.
Across all 116 available older frozen fixtures, correct high-score candidates
increased from 108 to 109, with none lost and no new high-score incorrect result
under the existing labels. One older fixture was unavailable. These are familiar
single-reviewer labels, not a new independent accuracy benchmark.

Twenty-five constructed blank, solid-color and partial-crop controls added no
high-score numeric results relative to the baseline. Five partial controls already
produced such results before this change and still do: confidence is not proof of
a complete or correct reading. The first implementation boosted two additional
clipped controls; requiring margins around the orange badge prevented that retry.

Eight actual retries across this replay averaged 20.5 ms of additional recognition
wall time locally (maximum 21.6 ms). This excludes model initialization, is a small
Windows sample, and is not a VPS CPU or end-to-end capture latency measurement.
Existing request timeouts and post-OCR freshness checks still bound eligibility.

The full Python suite passed 2,919 tests, with 119 unavailable private-fixture skips
and one Windows symlink-permission skip. Synthetic regressions cover retry score
boundaries, disagreement, malformed responses, all four crop edges, failures,
idempotent bridge validation and duplicate-frame rejection by the persistent floor.
Screenshots, crops and replay output remain ignored private artifacts. No live
capture, VPS deployment, API restart or production history rewrite was performed.

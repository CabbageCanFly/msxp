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

## TODO (deferred): obscured LV labels and localization timeouts

**Status: deferred at the operator's request.** This edge-case follow-up is future
work, not a completed production fix. The local prototype and test results below
are retained in version control for later review; they have not been deployed. The
capture-concurrency trial has not been run. Earlier fixes described above are
separate from this deferred investigation. Streamer and character names in this
document are placeholders.

Eight supplied screenshots for `streamer_c` / `CharC` in the ignored
`samples/important-level-up-sample-reference/` show the native level 47 badge and
42 EXP / 0.01%. The separate tracker overlay covers the native LV label to its
left. Before this change, the locator found one HP/MP/EXP layout in every image,
but supplied no level region because the LV text anchor was missing. Both level
readers therefore received no crop (`missing_crop` for the neural reader).
The earlier confidence/temporal-confirmation fixes cannot help a missing input.

The pair alone is ambiguous across levels 37–53 under the existing rounding
hypotheses; repeating it does not independently identify level 47. The native
digits must be read instead of inferring identity or level from this pair.

The local prototype considers a level crop only for one undisputed three-label HUD,
using the existing Classic layout's relative geometry. It requires a visible
orange badge inside that crop with margins on all four sides and bounded size
relative to the HP/MP spacing. An absent badge, a crop outside the source frame,
edge-touching or implausibly sized color bounds, multiple HUDs and explicitly
disputed level geometry still withhold the crop. Existing LV-based crops are
unchanged. The fallback records `level_region_source: hp_mp_exp_orange_badge`
without fabricating an LV token or changing EXP geometry.

Both existing readers then read 47 on all eight local screenshots, with neural
scores 0.99964–0.99986. Five strict EXP pairs remain 42 / 0.01%; the three malformed
raw strings remain rejected as EXP candidates. No parser, confidence threshold,
identity policy, level confirmation rule, EXP requirement or accounting rule was
changed. A plausible orange object at the expected position remains a limitation;
color/geometry is crop evidence, not proof of correct digits or character ownership.

An isolated SQLite comparison used an explicitly synthetic, independently seeded
level-46 baseline, then these actual OCR outputs at artificial 20-second timestamps.
The old outputs left the floor at 46. With the recovered crops, the first image
was held for confirmation; the second advanced the floor to 47, and the accepted
reading became 42 EXP / 0.01% without further EXP gains. No trusted observations
were created. These screenshots are all after the reported level-up: this is not
a replay of its real boundary or a measurement of live VPS capture latency.

Eleven synthetic localization cases cover the fallback and its rejection guards;
the focused locator, capture, neural-level and autonomous-character suites passed
233 tests. The full Python suite passed 3,038 tests, with 68 missing-private-crop
skips, one Windows symlink-permission skip and one expected failure.
Private before/after OCR output, crops and disposable databases are in
ignored local replay artifacts, outside Git. Production SSH authentication was unavailable.
The operator supplied checkout version `e43c299` and eight production records from
2026-10-23 09:34–09:39 UTC. The 09:37:02 record reports `missing_crop`, consistent
with the screenshot reproduction. A follow-up extract adds 09:39:46 and explains
the other eight attempts: all report `localization_failed`, one also reports
`local_receipt_age_exceeded`. Seven fail after one Tesseract call at approximately
10.39–10.53 seconds; one fails after two calls at 18.98 seconds and is already stale.
The only completed localization takes 9.35 seconds, then has no level crop and a
malformed EXP pair. Resident OCR queue waits are under 0.0001 seconds. The native
worker has a 10-second per-request limit, so these timings strongly suggest
request timeouts; the old generic exception handler discarded the specific cause.

The operator also reports four CPUs, sustained system load around 7.4–7.6, no
service CPU quota, and several busy Python processes. This supports CPU contention
as a contributor, but load includes uninterruptible I/O and the supplied `ps` CPU
figures are lifetime averages. A subsequent service inspection identifies the busy
process as `msxp-api`, alongside the capture-only tracker using six
capture workers, resident neural OCR and resident Tesseract. Six capture workers
permit four simultaneous native OCR workers; the API and video decoding compete
for the same four CPUs. Concurrency is not itself a core-count guarantee because
capture also waits for network I/O.

A reversible three-capture-worker runtime trial would cap native OCR concurrency
at three. Its benefit remains unmeasured; fewer workers can also miss more capture
slots. It needs an explicit operator restart and must preserve the existing database,
runtime path, capture bounds and retention settings. The supplied exact ExecStart
with only `--workers 6` changed to `--workers 3` was prepared as a private runtime
override named `90-ocr-concurrency-trial.conf`; it was not installed.
Compare failure reasons, stage durations, skipped slots and actual per-channel
cadence before/after. Confirmation still needs two distinct qualifying captures
within 120 seconds, so a lower failure count alone is insufficient. A trial should
be rolled back if effective capture cadence becomes worse. Profiling the API's
CPU cost remains separate; its high process average alone does not establish a bug.
The older local screenshot replay needed 1.90–2.60 seconds for the five Perion
images and 5.90–6.05 seconds for the three crowded Free Market images; this is not
a controlled comparison of Linux/VPS hardware or its running workload.

The local diagnostic prototype preserves five fixed native-worker failure
codes alongside `localization_failed`; the diagnostic sanitizer permits those
same codes. Arbitrary exception text, URLs and paths remain excluded. Eight new
fault-injection cases passed with the capture/view/native-worker/localizer/level-
guard subset (217 tests). The final full Python run passed 3,047 tests, with
68 missing-private-crop skips, one Windows symlink-permission skip and one known
expected failure (the recorded-stream tiny-font 9/8 misread).
This improves diagnosis, not throughput. Timeouts,
freshness limits, scan scales and completeness checks remain unchanged. A failed
attempt still clears pending level confirmation: recovering the crop alone cannot
guarantee two qualifying captures arrive in time under the observed failure rate.
Do not increase timeouts or accept stale readings to force confirmation.

The relevant locator/capture/guard files at `e43c299`
match the local committed baseline; the running process version was not verified.
Nothing was deployed, restarted or backfilled. Loading this locator
change on the VPS would require a controlled restart of the capture tracker.

### Future work and acceptance checks

- Revisit the crop prototype with more independent obscured-label footage,
  conflicting overlays, clipped badges and multiple-HUD negatives. Preserve
  character attribution, arithmetic checks and distinct-frame confirmation.
- Profile the API and OCR workload under representative server load. Confirm the
  specific localization error using the diagnostic prototype; the historical
  timings suggest a timeout but did not retain its exact error code.
- If still warranted, run the reviewed, reversible six-to-three-worker comparison
  with the current production database and service settings. Measure usable
  readings, stage timings, missed slots, actual cadence and public API latency.
  Roll back if capture cadence or API behavior degrades.
- Verify stationary post-level-up readings can confirm the new level through two
  distinct qualifying captures within 120 seconds, including a fresh writer and
  the existing negative cases. Do not relax freshness or confidence to force it.
- Review and explicitly authorize any eventual deployment and tracker restart
  separately. No production history backfill is part of this TODO.

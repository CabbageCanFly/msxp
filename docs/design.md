# Small service design after the feasibility prototype

Remote Streamlink/FFmpeg capture has passed a short authorized trial with zero
streamer setup; see [live-capture.md](live-capture.md). Optional calibrated glyph
matching improves saved live crops to 17/18 correct accepted readings; see
[ocr-reliability.md](ocr-reliability.md). [Consolidated calibration and trust
rules](ocr-consolidation.md) now support starting the local SQLite engine.
The rest of this document remains a service proposal.

This is a proposal. Only local OCR, observation validation and acquisition test
tools exist today. There is no running website, database service or overlay.

## Acquisition and service boundary

For the next consented trial, keep the working periodic remote capture and test
15-second intervals with the optional glyph profile. Official thumbnails and
the OBS experiment remain unverified alternatives, documented in
[acquisition.md](acquisition.md). Public remote playback still requires platform
permission clarification. No acquisition redesign is needed for this OCR milestone.

Once capture is established: a free static site serves registration/configuration
and the read-only overlay. One small Python HTTP process on the existing VPS
accepts authenticated crops, runs a single bounded OCR worker, writes SQLite and
serves recent state/history. Use HTTPS with a conventional reverse proxy and a
systemd service; no Redis, containers, queues or external database are necessary
for 1–5 streamers. The static host and VPS are replaceable. No resources have been
provisioned or priced as guaranteed free.

Bound crop dimensions, request bytes, capture frequency, decode pixel count and
pending work. Drop older pending captures for a streamer instead of building a
backlog. Keep full frames only in acquisition memory. Debug crops require opt-in
and short retention. Uploads require a separate revocable, narrowly scoped capture
credential. Store its hash server-side; never accept character selection from an
unauthenticated public overlay. Twitch client secrets remain server-side. OBS
credentials remain local and must never enter URLs, backend requests or telemetry.

## Persistence

[schema.sql](schema.sql) is an executable schema sketch, not a shipped persistence
layer. Its tables separate:

| Table | Purpose |
| --- | --- |
| streamers | Stable Twitch user ID and current display/login information |
| characters | Streamer-owned explicit character labels, world and EXP ruleset |
| sessions | Time-bounded activity for one selected character |
| observations | Accepted, rejected, ambiguous or unreadable capture attempts |
| tracking_state | Active selection/session, last successful reading, state and ROI configuration |

Use integer EXP and integer hundredths of a percent (`percentage_bp`); the current
OCR API uses float percentages only for convenience. Record UTC receipt time
separately from known capture time. Twitch thumbnails lack a trustworthy precise
capture time, so persist NULL and disclose that uncertainty. Record hashes to
identify repeats; identical pixels do not distinguish inactivity from stale capture.
No full image/blob or OBS password column exists.

Composite foreign keys prevent observations from being assigned to a different
character's session and state from pointing to another streamer's session. Enable
foreign keys on every connection. The future writer must update observation and
state together in a transaction and check the pointed observation's status. Use
WAL, a short busy timeout, one writer, and SQLite's backup API for consistent
backups. Clear state pointers before deleting a character/history; cascading
deletion alone is insufficient for active state. Test restore, retention and
consent withdrawal before public launch.

## Tracking state and rates

The implemented `validate_transition` is a pure, conservative gate. It reports
baseline/accepted/rejected/ambiguous, without mutating the prior observation.
Only pass OCR results whose status is `accepted` into it. A low-confidence
`reading` is a diagnostic candidate and may contain incorrect digits.

For SQLite ingestion, require a calibrated glyph profile and apply the existing
capture safety guard before this gate; see [trust rules](ocr-consolidation.md).
An unverified Tesseract EXP fallback must never update trusted state. No gain-rate
cap is enabled by capture. Persist state only for transition `baseline`/`accepted`,
preserving the previous trusted reading/time for every other outcome.

Proposed service behavior:

| State / event | Action |
| --- | --- |
| unconfigured | Require an explicit character and calibrated acquisition configuration |
| waiting / first good frame | Establish a baseline; show EXP and last-success time, no rate yet |
| tracking / valid same-level frame | Record gain and covered time, then advance accepted state |
| unreadable, low confidence, acquisition error | Pause immediately, preserve last accepted reading, show reason and age |
| gap over 120 seconds, or explicit pause | Break the continuous segment; next usable frame establishes a baseline |
| level change, EXP decrease, conflicting digits | Enter ambiguous state; do not change history or assume a level-up |
| confirmed Twitch offline | Show offline, close/pause the session; API/network failure is not proof of offline |
| explicit character switch | Close the current session, select another character, create a fresh baseline |

Resume after a short read failure only after two consistent fresh readings; start
a new continuous segment rather than silently adding a cross-pause delta. This
two-reading recovery rule is proposed, not implemented by the validator. Do not
lose the prior accepted observation when rejecting a candidate. User correction
should add an auditable event rather than rewrite previous accepted values.

Rates for a selected interval sum accepted deltas over covered consecutive pairs
within continuous segments. Display covered time, wall-clock time and gaps
separately. Hide EXP/hour and ETA until there is sufficient recent covered time;
no rate at zero gain and no interpolation through long gaps. Session EXP should
be labeled “observed EXP” when gaps exist. History graphs show breaks and include
last successful reading time. With thumbnails, rates based on receipt times are
approximate because actual capture times are unknown; disclose this instead of
presenting precise short-interval rates.

## Level-ups and character identity

Level/EXP cannot establish identity. A level increase can be a different character,
bad OCR or a real level-up; a decrease can also be death/EXP loss or a reset.
The current validator flags all such transitions. In a later milestone, require
consistent readings plus explicit identity/level-up confirmation, and use a
verified, versioned Classic World EXP table. For a confirmed A→B level transition,
gain is `(required[A] - previous_exp) + sum(required[A+1:B]) + current_exp`.
If requirements or intervening levels are uncertain, record a new baseline and
leave the gain unknown. Percent alone is not an accurate substitute for the
level's total EXP. Add numeric/percentage cross-checks once the table and rounding
rules are verified. A same-level character switch is undetectable from HUD
numbers alone; explicit selection remains required.

## Website and overlay

Smallest eventual UI: prove Twitch channel ownership, add/select a character,
choose acquisition, calibrate ROIs with a local preview, and copy a read-only OBS
Browser Source URL. Capture configuration belongs in an authenticated private
page/dock, separate from the public display. The overlay polls state every few
seconds (capture remains every 30–60 seconds), showing level/EXP, observed session
gain, interval gain/rate, ETA when available, pause/offline status and last-success
age. Add selectable history intervals/graphs only after tracking semantics work.
Streamers must know if closing the capture page stops capture.

## Resource limits and next milestone

One 1920x1080 RGB frame is about 6.2 MB, but grayscale enlargement of the lower
30% to 3x dimensions adds about 5.6 MB plus OCR subprocess allocations. Searching
the full frame or processing several streamers concurrently increases peaks.
Use calibrated crops and one OCR job at a time on 1 vCPU / 1 GB. Local measurements
are in [results.md](results.md), not a VPS capacity benchmark. At 60 seconds and
five streamers, 0.5 CPU-seconds/job would consume about 4% of one CPU on average;
the actual VPS may be much slower. SQLite volume is only 7,200 attempts/day for
five streamers at one/minute, but indexes and retention still need measurement.

Before hosting, run one 15-minute acquisition trial with known HUD changes,
missing-HUD periods and a scene switch. Save only crops with consent and measure
OCR accuracy, age and resource use. Then implement one local SQLite tracking loop
with explicit character selection and paused segments. Keep Twitch login,
registration, public hosting and graphs out of that next milestone.

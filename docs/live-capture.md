# Remote frame capture milestone

Recognition follow-up: [ocr-reliability.md](ocr-reliability.md) reports offline
replay improving these crops from 5/18 to 17/18 correct accepted readings, with
zero observed wrong accepts. The measurements below remain the original capture
measurements. Subsequent user-run green-bracket trials and the capture safety
gate are recorded in [ocr-consolidation.md](ocr-consolidation.md).

This milestone adds server/developer-side Streamlink + FFmpeg acquisition. The
streamer installs nothing and changes no OBS settings. No website, hosted worker,
account system or deployment is included. Earlier feasibility results remain in
[results.md](results.md); the current measurements are recorded here.

## Install and reproduce

FFmpeg must be on PATH, or set `FFMPEG_CMD` / pass `--ffmpeg` to capture. On a
Linux OCR server, install `ffmpeg` and `tesseract-ocr` using its package manager.
Python dependencies are optional extras so ordinary screenshot OCR remains small:

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev,capture]"
.\.venv\Scripts\python -m exp_tracker.capture --file private/authorized-video.mp4 --mode periodic --count 1 --config configs/stream1.json
.\.venv\Scripts\python -m exp_tracker.capture --channel streamer_a --mode periodic --interval 30 --count 3 --config configs/streamer-live.json
```

The channel trial requires permission to test that content. An authorized trial
on `streamer_a` was confirmed by the project owner in this session. That is not
platform authorization for a public capture service. No credentials are needed
for anonymous public playback when Twitch allows it. Restricted, unavailable,
advertisement or access-denied inputs may yield no useful HUD reading.

Use the config for the actual layout, not merely the channel name. The separate
`streamer-live.json` has a wider EXP crop than the original screenshot fixture:
larger numeric EXP and a two-digit percent occupied more horizontal space during
the trial. Original sample configs and expected answers are preserved. Calibrate
again if the streamer changes resolution/layout; numeric character identity
cannot be inferred from the source.

`--debug-dir artifacts/trial-crops` explicitly saves only configured/discovered
field crops and preprocessing outputs. Full captured frames exist only in RAM.
No screenshot upload occurs. All default benchmark/debug outputs are ignored by
Git. JSON includes OCR candidates; only `status: accepted` and an accepted/baseline
transition can advance the small in-memory observation baseline. There is no
persistence or full tracking state machine yet.

## Connection modes

Both modes use the same selected rendition and keyframe-only decoder by default.

- **periodic:** create Streamlink and FFmpeg for each tick, capture a frame,
  perform OCR, then terminate both. Resolves playback afresh every time and avoids
  paying continuous video bandwidth. Connection overhead and ads can recur.
- **persistent:** keep one connection/decoder and drain its output continuously.
  A single replaceable latest-frame buffer prevents OCR backlog. Later ticks
  consume a recent delivered frame instead of reopening the source. It still
  downloads the full selected rendition between OCR samples.

FFmpeg uses one decoder/PNG encoder thread, skips non-keyframes and emits at
most one PNG/second. Keyframe spacing limits sampling freshness; it does not
reduce network traffic. `--full-decode` disables keyframe skipping for a controlled
CPU comparison. No lower-resolution fallback is automatic: use `--quality 720p60`
or an available named rendition deliberately and verify OCR detail. `best` favors
detail but may select an expensive rendition. A lower frame-rate rendition at
the same native resolution would be preferable if actually offered by Twitch.

The decoder frame buffer has a byte/pixel cap. Streamlink has a 4 MiB ring buffer,
one segment-download thread and bounded HTTP/segment retries/timeouts. Both stderr
pipes are drained into bounded memory. Logs may contain signed playback URLs,
so only safe failure reason codes reach output. Closing, a failure or Ctrl+C
terminates/reaps child processes and joins reader threads.

## Output and failures

Each scheduled attempt emits one JSON object, followed eventually by a summary.
It includes level/current EXP/percent candidates, raw cropped-field OCR,
confidence/status, transition validation, frame hash, capture wait, local delivery
age, OCR duration, process-tree CPU/RSS and compressed-video payload bytes.

`frame_captured_at` is NULL: the acquisition pipeline does not establish when
Twitch/OBS originally captured the pixels. `received_at` and
`local_delivery_age_seconds` describe local decoder delivery only. Low local age
does not prove low broadcast latency. Hash changes establish changed pixels,
not a trustworthy timestamp. HLS live-edge delay, keyframe spacing, decoder
probing and broadcaster delay all contribute to actual age. Do not derive precise
short-interval EXP rates from these receipt times without disclosing uncertainty.

Failure codes distinguish local setup/input errors, network unavailability,
access denial, no playable streams, source end and frame timeout. No playable
stream is labeled `offline_or_unavailable`, because Streamlink alone cannot
reliably distinguish offline from every restriction. Confirm offline separately
with official Helix if required later. An OCR failure preserves the previous
accepted reading. Decreases/level changes remain ambiguous, never automatic
level-ups. Long gaps get a new baseline using the existing validator.

Pipe-buffer follow-up (2026-10-21): the relay forwards available video chunks
without waiting to fill 16 KiB, and stderr readers expose short messages before
the child exits. Synthetic live subprocess tests reproduce both former stalls.
Saved `frame_timeout` records with zero relayed bytes alone cannot distinguish
this buffering issue from an upstream Twitch/network stall; no live recovery
rate is established by those tests. Raw stderr and signed URLs stay private.

The scheduler avoids overlapping jobs and catch-up bursts. If a job overruns its
interval, the next attempt is delayed instead. A failed persistent connection is
closed and retried on a later scheduled tick. CLI exit codes: 1 setup error,
2 no frame processed, 130 interruption, otherwise 0. Exit 0 does not mean any OCR
reading was accepted; inspect the per-observation statuses and summary counters.

## Benchmarks and measurement scope

### Actual results, 2026-10-15

Environment: Windows developer machine, Python 3.14.7, Streamlink 8.6.2,
psutil 7.2.2, FFmpeg 2026-08-17 build, Tesseract 5.4.0. The project owner ran
network trials from a normal terminal because this agent's sandbox denied both
Twitch DNS and loopback HTTP connections. I inspected the resulting JSON and
cropped images on the shared filesystem. No browser, credentials or evasion was
needed for successful playback in those authorized trials.

**Owned local HLS control:** all 12/12 frames were captured and parsed to the
synthetic ground truth (level 37, EXP 123,456, 12.34%). HTTP response-body totals
below include server-side observed prefetch, unlike the client relay counter.

| Mode / interval | Samples | Capture wait | CPU, one-core equivalent | Peak tree RSS | HTTP body MB / wall seconds |
| --- | ---: | --- | ---: | ---: | --- |
| periodic / 30s | 3 | 2.639–2.657s each | 6.11% | 188.45 MiB | 7.27 / 63.16s |
| persistent / 30s | 3 | 2.635s startup, then 0 | 5.50% | 198.45 MiB | 25.00 / 60.49s |
| periodic / 10s | 3 | 2.649–2.661s each | 12.14% | 188.55 MiB | 7.27 / 23.17s |
| persistent / 10s | 3 | 2.670s startup, then 0 | 9.91% | 194.98 MiB | 8.92 / 20.65s |

The first three runs preceded the unrestricted-line OCR refinement and produced
correct but low-confidence candidates. The final run accepted 3/3. Replaying
the stored crops through the final OCR accepted **12/12** with the correct values;
this replay is a separate OCR result, not a retroactive change to capture metrics.
The 30-second mode pair used the same OCR version and is the cleaner CPU
comparison. The 10-second CPU comparison includes the OCR version difference.

**Authorized live Twitch trial, `streamer_a`, native 1920x1080, rendition `best`:**
all **18/18 scheduled captures succeeded**. Small runs at different times are
not statistically controlled comparisons of network conditions or game activity.

| Mode / interval | Capture wait | CPU, one-core equivalent | Peak tree RSS | Relayed video MB / wall seconds | Accepted OCR |
| --- | --- | ---: | ---: | --- | ---: |
| periodic / 30s | 1.651–1.758s each | 9.24% | 200.68 MiB | 11.50 / 62.41s | 1/3 |
| persistent / 30s | 1.571s startup, then 0 | 10.83% | 201.11 MiB | 55.96 / 60.61s | 1/3 |
| periodic / 15s | 1.410–1.546s each | 11.61% | 202.88 MiB | 11.37 / 32.17s | 0/3 |
| persistent / 15s | 1.585s startup, then 0 | 11.64% | 202.88 MiB | 26.80 / 30.61s | 2/3 |
| periodic / 10s | 1.445–1.474s each | 16.16% | 201.47 MiB | 11.37 / 22.14s | 1/3 |
| persistent / 10s | 1.581s startup, then 0 | 15.58% | 201.57 MiB | 21.05 / 20.65s | 0/3 |

Accepted complete live readings, manually checked against the saved game-HUD
crops (all level 60):

| Current EXP | Percentage | OCR score |
| ---: | ---: | ---: |
| 391,726 | 32.37% | 0.46 |
| 391,866 | 32.39% | 0.57 |
| 396,695 | 32.78% | 0.72 |
| 397,396 | 32.84% | 0.52 |
| 398,806 | 32.96% | 0.72 |

Of 18 live frames, 5 were accepted, 7 were low confidence and 6 were unreadable.
All 5 accepted readings matched visual review; this small trial does not establish
a production error rate. A rejected candidate read 398,936 where the crop showed
395,936, demonstrating why candidate presence is not acceptance. Tiny brackets
were often read as a digit `1`, and strict parsing intentionally rejected those
strings. Experiments with more aggressive resizing also produced plausible wrong
digits, so those variants and punctuation-guessing were not added.

OCR took roughly 0.5–0.8 seconds per calibrated frame. Persistent local delivery
age reached 4.25 seconds despite zero acquisition wait at later ticks. Actual
broadcast age remains unknown; a visible synchronized clock test is still needed.
The initial narrower crop trial captured another 3/3 frames but clipped percentages
and accepted none; it is excluded from the wider-crop table.

**Decoder CPU experiment:** on the owned 1920x1080/30fps local file, persistent
sampling every 10 seconds, 3 samples in ~20.7 seconds:

| Decoder | Sampled CPU | Peak RSS | First-frame wait | OCR |
| --- | ---: | ---: | ---: | --- |
| keyframes only | 5.81% | 126.96 MiB | 3.525s | 3/3 accepted, correct |
| full decode | 13.83% | 138.45 MiB | 0.065s | 3/3 accepted, correct |

Keyframe-only decoding reduced CPU in this file test but delayed its first output.
Keep it as the default for 30-second updates; test full decoding if a real source
has very long keyframe spacing. This file comparison excludes Streamlink and
networking and is not a Twitch bandwidth comparison.

The exact local file comparison can be reproduced after the fixture builder:

```powershell
ffmpeg -hide_banner -loglevel error -y -stream_loop -1 -i artifacts/local-hls-benchmark/source.mp4 -t 25 -c copy artifacts/local-hls-benchmark/source25.mp4
.\.venv\Scripts\python -m exp_tracker.capture --file artifacts/local-hls-benchmark/source25.mp4 --mode persistent --interval 10 --count 3 --config artifacts/local-hls-benchmark/config.json
.\.venv\Scripts\python -m exp_tracker.capture --file artifacts/local-hls-benchmark/source25.mp4 --mode persistent --interval 10 --count 3 --config artifacts/local-hls-benchmark/config.json --full-decode
```

### Recommendation and 1–5 channel envelope

Use **periodic capture at 30 seconds** initially. In the live 30-second comparison
it used about one fifth of the persistent trial's relayed bytes with similar CPU
and peak memory, and its ~1.7-second acquisition wait fits comfortably. Persistent
mode is implemented for sources where reopen reliability becomes a problem, but
it does not create a low-bandwidth feed on its own. No lower rendition has passed
an OCR accuracy trial; earlier 720p tests lost digits.

10–15 second **capture** worked in this short trial. It raises periodic connection
overhead/bandwidth and does not solve OCR. Reliable usable readings every 30
seconds are **not yet demonstrated**: the live acceptance rate was only 5/18.
Recognition reliability is now the primary development blocker, not frame access.

Estimates below extrapolate the Windows 30-second trial; they are **not Linux VPS
benchmarks**. At ~3.83 MB/attempt, periodic capture averages ~1.02 Mbps of relayed
video per channel in steady operation: ~11 GB/day/channel at 24/7 use or ~1.84 GB
for a four-hour stream. Five channels are ~5.1 Mbps, ~55 GB/day, or ~9.2 GB per
four-hour day, before uncounted transfer overhead/prefetch. The persistent trial
averaged ~7.39 Mbps/channel; five similar feeds would approach 37 Mbps and ~399
GB/day if kept connected continuously. These short-window rates can be biased
by startup prefetch. Check actual provider traffic quotas before sustained use.

One process tree peaked around **200 MiB**. Five concurrent independent trees
could approach **1 GiB before OS/services**, leaving no comfortable RAM margin.
Five copies of the measured periodic CPU average would be ~46% of one core, but
CPU bursts, sampling undercounts and a slower VPS make that only a rough envelope.
A future multi-channel worker should stagger periodic jobs and allow only one
decode/OCR job at a time. Such coordination is not implemented here. Benchmark
the actual VPS before claiming five-channel capacity. One channel is the sensible
first Linux trial.

### Reproduction and caveats

Reproduce the owned synthetic 1920x1080/30fps H.264 source (~3 Mbps target, 2-second
GOP), real-time HLS server and both acquisition modes:

```powershell
.\.venv\Scripts\python tools/benchmark_capture.py --intervals 30,15,10 --count 3 --directory artifacts/local-hls-benchmark
# Authorized live source, same acquisition code and native rendition:
.\.venv\Scripts\python tools/benchmark_capture.py --channel streamer_a --config configs/streamer-live.json --intervals 30,15,10 --count 3 --directory artifacts/live-benchmark
```

The synthetic fixture is original generated content. It tests plumbing, not
general MapleStory accuracy. A separate local H.264 clip made from the supplied
private screenshot tests actual game glyph compression without publishing it.
No test downloads media or needs Twitch credentials. Optional real FFmpeg tests
create their own tiny video; they skip explicitly when FFmpeg is absent.

Each run saves observations and `summary.jsonl`. CPU is sampled user+system time
for the capture Python process and all observed descendants, including Streamlink,
FFmpeg and Tesseract. RSS is their sampled aggregate working set. Sampling every
250 ms can miss short-lived subprocess CPU and peak memory. CPU measurement also
includes monitor overhead; Windows process enumeration is relatively expensive.
Early exploratory data used 50 ms sampling and is not directly comparable.
The synthetic source generator/HTTP server are outside the measured process tree.

`video_payload_bytes` counts MPEG-TS bytes relayed into FFmpeg, not true NIC bytes:
HTTP/TLS overhead, manifests, API calls and Streamlink-prefetched data can be
excluded. For the owned HLS control, `server_http_body_bytes` independently counts
served manifest/segment bodies, including prefetch served before disconnect.
It still excludes HTTP headers and transport overhead. These are measured payload
figures, not a promise about VPS transfer billing.

Three samples at 30 seconds span about 60 seconds plus startup/processing, not
90 seconds. Report both measured run-average rate and bytes/attempt divided by
the intended steady interval for periodic-mode planning. Longer soak tests are
needed before capacity claims. All current measurements are Windows developer
machine measurements; the small Linux VPS has not been benchmarked.

Re-run OCR on a saved trial's field crops without connecting to any source or
modifying the original measurements:

```powershell
.\.venv\Scripts\python tools/replay_capture_crops.py artifacts/local-hls-benchmark/periodic-30.jsonl artifacts/local-hls-benchmark/periodic-30-crops
```

## Validation and next milestone

Final checks: **106 Python tests passed, zero skipped**, including real FFmpeg
decode/cleanup, bounded PNG parsing, stale-frame/sequence rejection, failure
classification, CLI failure records, scheduling argument checks and all prior
sample/validation/schema tests. `pip check`, Python compilation and `git diff
--check` also passed. The original screenshot values/statuses remain unchanged.
Use `python -m pytest --basetemp=artifacts/pytest-tmp` in the installed environment.

Offline tests never contact Twitch. FFmpeg tests generate original content and
skip explicitly when the external binary is unavailable. A few capture CLI tests
also require the optional psutil dependency. Live offline-channel/ad/interruption
scenarios were not exercised; synthetic failure tests cover the safe handling
paths, which is not equivalent to live reliability validation. Linux execution,
long-running reconnect behavior and simultaneous channels remain unverified.

The smallest useful next milestone is **reliable live-HUD recognition on consented
private crops**, before a hosted tracker or more frequent capture. Label the saved
live crops, split development and evaluation examples, improve ROI calibration
and field segmentation, and measure false accepts as well as accepted coverage.
Do not lower confidence thresholds or guess punctuation to inflate coverage.
Keep the 30-second periodic capture fixed while comparing recognizers. Then run
one longer authorized trial with a visible clock, missing-HUD periods and scene
changes, and benchmark one channel on the actual Linux VPS. Only after those
gates should a bounded multi-channel worker and SQLite session persistence follow.

Suggested next-session prompt:

> Continue from docs/live-capture.md. Improve recognition of the captured live
> MapleStory HUD using private crops under artifacts/live-benchmark. Preserve the
> working Streamlink/FFmpeg pipeline and original screenshot regressions. Build a
> private ground-truth evaluation set, improve field segmentation/calibration,
> and report accepted coverage and false accepts on separate evaluation crops.
> Never publish crops, hardcode readings, or guess missing digits/punctuation.
> Keep capture at 30 seconds; no hosting, deployment or OBS changes. Once offline
> accuracy improves, help run a longer authorized live trial and a single-channel
> Linux resource check.

## Platform boundary

[Streamlink's Twitch integration](https://streamlink.github.io/cli.html#twitch)
uses unofficial playback integration. Our commands disable browser launching,
default user configuration, plugin sideloading and plugin credential caching.
No OAuth/cookie scraping, client-integrity workaround, ad skipping, proxy evasion
or access-control bypass is implemented. If anonymous access fails, it remains
a reported failure. Technical playback success does not establish service rights.

The [Twitch terms](https://www.twitch.tv/p/terms-of-service) restrict unauthorized
automated extraction/downloading, and the
[Developer Agreement](https://legal.twitch.com/en/legal/developer-agreement/)
limits use of undocumented interfaces absent permission. Streamer permission
does not remove those platform conditions. Obtain platform clarification before
public deployment or sustained third-party collection, and define consent,
retention and deletion rules for derived EXP history. No public deployment is
authorized by this prototype.

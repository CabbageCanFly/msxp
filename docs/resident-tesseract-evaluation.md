# Resident Tesseract (native C API) evaluation

> **Archived research.** The engine and its tests are in main as the opt-in `--resident-tesseract` flag; see
> [staggered capture and resident Tesseract](performance-integration.md). `tools/benchmark_resident_tesseract.py`
> was not kept, so §2 and §10 record how the figures were measured; they are not runnable steps.

> The implementation/status statements, limits and proposed commands below describe
> the original experiment, not the current tracker. The linked integration guide
> includes the later Ubuntu parity results. Historical benchmark commands depend on
> tools and branches that are no longer retained; do not use this as a VPS runbook.

The original research ran on `research/resident-tesseract` from `main` (`b894081`),
before integration. It left the default OCR path unchanged and touched no VPS,
Twitch stream, production database or private recording.

**Every measurement here is Windows workstation data:** i7-13700K, Windows 11, Tesseract
5.4.0.20240606, `eng.traineddata` SHA-256 `7d4322bd…70b2` (the 4 MB fast model). None of
it is an Ubuntu or VPS measurement.

## Results first

| | pytesseract CLI | Resident C API, in-process | Resident C API, isolated worker |
|---|---:|---:|---:|
| Frames with identical OCR (80) | — | **80/80** | **80/80** |
| Calls with identical TSV (535: 160 full-frame, 375 level) | — | **535/535** | **535/535** |
| Differences on the reverse-order repeat (A → B → A) | — | 0 | 0 |
| CPU per frame, `locate()` + level OCR, all processes | 2.575 s | 1.881 s (**−27 %**) | 1.905 s (**−26 %**) |
| Full-frame passes (2×, 3×): wall per recording frame | 2.322 s | — | 1.964 s (**−15 %**) |
| Level OCR: wall per recording frame | 0.452 s | — | 0.016 s (**−96 %**) |
| Fixed cost per call (blank 40×20 image) | 0.086 s wall, 0.077 CPU-s | 0.003 s | 0.015 s |
| Throughput, 4 processes on 4 P-cores | 1.24 frames/s | 1.76 (+42 %) | 1.70 (**+37 %**) |

**The saving is removed overhead, not faster recognition.** It comes from per-call
process start, model load, PNG encode and PNG decode:

| Overhead per frame | CPU-s |
|---|---:|
| ≈6.7 calls × 0.071 CPU-s of CLI fixed cost | ≈0.48 |
| PIL encoding pytesseract's temporary PNG | ≈0.12 |
| Tesseract decoding the large PNGs | the rest |

Recognition work itself is unchanged, which is consistent with identical output. The
isolated worker adds ≈0.024 CPU-s per frame of pipe transfer over in-process.

**Recommendation:** worth advancing, as an isolated worker pool and never in-process.
It is gated on an Ubuntu parity and cost run (§10): the VPS uses Tesseract 5.5.0 and the
Ubuntu-packaged model, and Linux process start is cheaper than Windows'.

## 1. Approach

`tools/resident_tesseract.py` calls the installed libtesseract C API through `ctypes`,
so it adds no Python dependency. Nothing in the capture path imports it. The
benchmark replaces exactly one function, `pytesseract.image_to_data`, and only inside
its own process. That is the single call that every recognition OCR path makes:
`adaptive_hud.scan()` at 2× and 3×, `level_reading()` and the `_read_field()` fallback.
So `locate()` and `level_reading()` run **unmodified** with either engine.

How the native path matches today's pytesseract call
(`tesseract IMG OUT -l eng -c tessedit_create_tsv=1 --psm N [-c tessedit_char_whitelist=…]`):

| Aspect | pytesseract CLI | Native engine |
|---|---|---|
| Library, data, version | `tesseract` on PATH or `TESSERACT_CMD` | Same installation. `tessdata` comes from that CLI's `--list-langs`; the library sits beside the CLI (Windows), comes from `find_library('tesseract')` (Linux) or from `MSXP_LIBTESSERACT`. `TessVersion()` must equal the CLI's `--version`, or it refuses to start. The `eng.traineddata` SHA-256 is recorded with every run. |
| Language, engine mode | `-l eng`, default OEM | `TessBaseAPIInit3(datapath, "eng")`, default OEM |
| Pixels | The PIL `L` image saved as an 8-bit PNG, read by Leptonica | The same `L` image's bytes through `TessBaseAPISetImage(…, 1 byte/pixel)`, which copies them into a Leptonica Pix. Any other mode is refused, never converted. |
| Page segmentation, whitelist | `--psm N`, optional `-c tessedit_char_whitelist=…` | Set on **every** request; an absent whitelist is sent as empty, so it can't leak from the previous call |
| Output | TSV file parsed by `pytesseract.file_to_dict` | `TessBaseAPIGetTsvText(0)` behind the same header line, parsed by the **same** `file_to_dict` |
| Config scope | Any | Only the exact strings `recognition._ocr` builds. Anything else (`--oem`, another language, STRING output, reordered options) raises instead of being approximated. |
| State between calls | A new process each call | `TessBaseAPIClear` and `TessBaseAPIClearAdaptiveClassifier` after every call |

Memory ownership:

- The pixel buffer is a Python `bytes` object that lives for the whole call, and
  Tesseract copies it.
- TSV text is copied out, then freed with `TessDeleteText` in a `finally` block.
- `close()` calls `TessBaseAPIEnd` and then `TessBaseAPIDelete`.

## 2. Parity method and results

`tools/benchmark_resident_tesseract.py` runs `locate()` and then `level_reading()` on every
located panel's level crop, three times per frame: baseline, in-process and worker. It
rotates which engine goes first. For every call it records:

- the config string;
- the image size;
- the SHA-256 of the exact pixels;
- the **full** TSV dictionary: every column of every row, including structural rows and
  `-1` confidences.

A frame counts as identical only if all of these match:

- every call's input;
- every call's entire dictionary: text, geometry, confidence and block/line/word numbering;
- the located candidates as whole dicts: count, regions, anchors, anchor corrections and
  `level_ambiguous`;
- the level readings: value and every attempt.

Any difference is listed with call index, config, differing rows and examples, and the tool
exits 1. Nothing is normalized.

A second pass runs over all frames in reverse order on the **same** native engines and must
reproduce the first pass. That checks for state leaks across scenes and characters, and
across the whitelist switching on and off between level and full-frame calls.

Corpus, decoded in memory with nothing written, pinned to P-cores 0, 2, 4 and 6:

- **56 recording frames:**
  - `sample-stream.mp4` every 120 s;
  - `sample-stream2.mp4` every 300 s;
  - `sample-stream3.mp4` every 180 s.

  The three recordings show different characters, so the frame order also switches
  characters.
- **12 HUD-localization challenge frames:** relocated, resized 0.5 / 0.75 / 1.25, two
  panels, hidden HUD with an overlay, blank, and embedded in a larger stream.
- **5 sample screenshots.**
- **7 in-memory composites:**
  - side-by-side half-size games;
  - two stacked full games (two HUDs);
  - a duplicated HUD strip (two HUDs);
  - LV label covered;
  - EXP label covered;
  - 1280×720 and 2560×1440 rescales.

**Outcome: 0 mismatches and 0 repeat mismatches.** Layout decisions were 63 frames with one
HUD, 11 with none (blank, hidden, covered EXP label, half-size games) and 6 with two;
58 level readings. Character-switch scenes exist only as frames from the different
recordings, so they are covered by the repeat pass's order changes.

`tests/test_resident_tesseract.py` also checks, against real Tesseract:

- in-process and worker dictionaries equal pytesseract's for psm 11, then psm 7 with a digit
  whitelist, then psm 11 again, so the whitelist does not leak;
- the worker reports the same model hash and version;
- a mismatch between library and CLI versions is refused.

## 3. Performance (workstation)

All runs are pinned to the same four P-cores. Unpinned Windows figures are misleading (§7).

| Per frame, mean of 80 | Wall | Python CPU | Tesseract CPU | Total CPU |
|---|---:|---:|---:|---:|
| CLI | 2.735 s | 0.317 s | 2.258 s (children) | 2.575 s |
| In-process | 1.978 s | 1.881 s (includes Tesseract) | — | 1.881 s |
| Worker | 1.990 s | 0.196 s | 1.709 s (worker) | 1.905 s |

| Subset | Frames | CLI CPU | Worker CPU |
|---|---:|---:|---:|
| Recordings | 56 | 2.774 s | 2.059 s (−26 %) |
| Challenge frames | 12 | 1.678 s | 1.164 s (−31 %) |
| Screenshots | 5 | 2.344 s | 1.772 s (−24 %) |
| Composites | 7 | 2.683 s | 2.042 s (−24 %) |

Concurrent throughput: N copies, 12 recording frames each, all pinned to the 4 P-cores.

| Processes | CLI frames/s | In-process | Worker |
|---:|---:|---:|---:|
| 1 | 0.332 | 0.453 (+36 %) | 0.451 (+36 %) |
| 2 | 0.671 | 0.904 (+35 %) | 0.868 (+29 %) |
| 4 | 1.238 | 1.759 (+42 %) | 1.701 (+37 %) |
| 6 (oversubscribed) | 1.184 | 1.558 (+32 %) | 1.568 (+32 %) |

The gain holds under contention because it removes CPU work, not waiting.

**Benefit by call type:**

- **Full-frame passes** save ≈15 %: process start, model load and the PNG round trip on 8.3
  and 18.7 MP images.
- **Small level crops** save ≈96 %: they were almost entirely start-up cost.

**VPS projection (estimate only).** Applying these ratios to the VPS 4-worker means
(localization 4.47 s, level 0.81 s) gives ≈3.8 s and ≈0.03 s. The OCR stage would fall
from ≈5.4 s to ≈4.0 s (−25 %). Linux creates processes more cheaply than Windows, so
the full-frame part may save less there. Measure it (§10).

## 4. Initialization and memory

| | CLI | Native |
|---|---|---|
| Engine initialization | Paid on every call (inside the 0.071 CPU-s fixed cost) | `TessBaseAPIInit3`: 0.052–0.056 s, once |
| Worker spawn → ready → first tiny reply | — | 0.19–0.22 s (5 runs) |
| Memory | Each Tesseract child peaks at ≈104 MiB, transiently, one per concurrent call | Worker: 51 MiB after init, 74 MiB steady, 140 MiB peak during 3× passes. In-process engine adds 18.6 MiB at init. |
| Growth over 200 requests (50 full-frame 3×, 150 level) | — | RSS 73.6 → 74.2 MiB: flat |

Windows worker figures include the ≈9 MiB venv launcher process (§7).

## 5. Failure handling (measured on the real worker)

- **Timeout:** a 3× full-frame request with a 0.05 s limit raised
  `tesseract_worker_request_timeout`, and the process was killed. The next request restarted
  it and returned output identical to the reference.
- **Crash:** the worker process tree was killed 0.2 s into a full-frame call, raising
  `tesseract_worker_failed`. The next request restarted it, again with identical output.
- **Fake-worker tests** cover:
  - reuse of one process (same PID);
  - hang → timeout → new PID;
  - exit → failure → restart;
  - an oversized reply length → failure, never an unbounded read;
  - a wrong image mode or size refused before anything is sent.
- **Error class:** both errors are `RuntimeError`, the same class pytesseract raises for its
  own timeout. They therefore fall into `analyze()`'s existing `localization_failed` and
  `visual_level_failed` handling. That path is not exercised end-to-end, because nothing is
  integrated.

## 6. Proposed production architecture (not implemented)

Use **one libtesseract engine per isolated worker process, in a bounded pool of K workers.**

- **Size:** K ≤ the OCR concurrency budget, 3 on the VPS. That matches the ≈3 effective
  cores in `docs/throughput-architecture-research.md` on `research/throughput-architecture`.
- **Use:** each attempt thread borrows an idle worker for one call and returns it.
  Per-lane ordering is unchanged, because each attempt still calls synchronously.
- **Isolation:** a native crash or hang can only kill a worker. The coordinator, the single
  SQLite writer and character attribution never load libtesseract.
- **In-process ctypes is rejected**, although it was 1 % faster: a segfault would end the
  coordinator, and a hung native call cannot be interrupted.
- **Bounds:**
  - request pixels ≤ 20 M (`scan()` tops out at 18.7 MP);
  - whitelist ≤ 256 bytes;
  - reply ≤ 8 MiB;
  - the existing 10 s timeout per pass;
  - stderr discarded;
  - optionally, as defence in depth, recycle a worker after N requests or above an RSS
    ceiling (no growth was seen).
- **Queueing:** waits for a free worker are bounded by K and the number of capture workers.
  Record each wait separately (`tesseract_queue_wait_seconds`) and let it count against
  `max_age`, as `fresh()` already does.
- **Settings:** set PSM and the whitelist on every request; clear results and the adaptive
  classifier after it, as the prototype does.
- **Cost:** ≈0.2 s per worker start or restart (Windows); K × ≈75–140 MiB resident.
- **Fail closed:**
  - refuse to start on a library/CLI version mismatch;
  - record the model hash in run headers;
  - never fall back silently to the CLI mid-run, because that changes provenance.

| | `ResidentNeural` | Proposed Tesseract pool |
|---|---|---|
| Processes | 1 per command, shared by every lane | K, each owning one engine |
| Request cost | ≈25–60 ms, a small PNG | Up to 1–2 s, up to 18.7 MB of raw pixels |
| Serialization | One lock | A pool: one long request does not block the other K−1 |
| Timeout | Starts after the lock, so queue wait is not bounded by it | The same per-call timeout, plus a separately measured queue wait |
| Failure | Kill, restart on the next request | The same; a restart costs ≈0.2 s instead of ≈1 s |

## 7. Windows versus Linux

**Hybrid cores (Windows, measured):**

- Unpinned, on a 10-frame smoke corpus, the native paths used **more** CPU than the CLI
  (3.43 vs 2.81 CPU-s per frame). This reproduced in two further runs.
- Pinned to one P-core, or to one E-core, native was faster in both cases.
- A standalone unpinned 3× call was also faster (0.82 s against the CLI's 1.10 s), with no
  extra threads. No OpenMP runtime ships with this build.
- The likely explanation: Windows schedules the long-lived OCR process on E-cores more
  often than fresh `tesseract.exe` processes.

Benchmark with `--cpus`. The VPS's vCPUs are uniform, but the Windows capture workstation
would need pinning, or this same check, before any use there.

Other platform notes:

- **Windows venv:** `python.exe` is a launcher with a child interpreter, so the benchmark
  accounts the worker's CPU and memory over its whole process tree.
- **Library discovery:**
  - Windows: `libtesseract*.dll` next to the CLI;
  - Linux: `ctypes.util.find_library('tesseract')`, which finds `libtesseract.so.5`;
  - `MSXP_LIBTESSERACT` overrides both;
  - `tessdata` always comes from the CLI's `--list-langs`, so nothing assumes Ubuntu's
    model equals Windows'.
- **POSIX child accounting:** baseline child CPU comes from `RUSAGE_CHILDREN`. Its
  `ru_maxrss` also covers the FFmpeg frame decoders, so a baseline child peak is reported
  only if it rises above that.
- **Untested:** Linux; Tesseract 5.5.0; the Ubuntu `eng.traineddata`; and whether the C
  API's TSV in 5.5 matches that version's CLI.

## 8. Is further implementation justified?

**Yes, conditionally.** On Windows:

- zero output differences across 535 calls, both scales, multi-HUD, obscured and rescaled
  scenes;
- 26 % less CPU per frame;
- +37 % throughput at 4 processes;
- flat memory;
- recovery from both a timeout and a crash.

It changes no threshold, parser, trust rule or attribution. Before any integration:

1. The Ubuntu run below must show **0 mismatches** and at least 10 % less CPU per frame.
2. Then build an opt-in pool (`--resident-tesseract K`, off by default) behind the existing
   coordinator, with recorded queue waits. Re-run the sustained 30 s VPS benchmark against
   the same configuration without it.

## 9. Files

- `tools/resident_tesseract.py`: the native engine, a strict pytesseract-compatible adapter,
  and the worker and client prototype.
- `tools/benchmark_resident_tesseract.py`: parity, cost, memory and throughput. Output is
  private and never overwritten; any mismatch exits 1.
- `tests/test_resident_tesseract.py`: adapter strictness, worker isolation with a fake
  worker, and real-Tesseract parity and no-leak tests. These are marked `ocr` and skip
  without libtesseract.

## 10. Ubuntu offline benchmark (operator-run; not run by Claude)

These commands **never stop, start or change a production unit**. They only check that
`msxp-tracker.service`, `msxp-backup.timer` and `msxp-backup.service` are inactive, and they
refuse to run otherwise. Taking production down, and bringing it back, belongs to the
normal controlled procedure and happens outside this benchmark.

The only input is the existing local recording `/opt/msxp/app/private/stress15/hud-long.mp4`,
read as `msxp`. Each run executes in a transient unit with `PrivateNetwork=yes`, so there is
no live video or network access, and it can write only under `/opt/msxp/bench/private`.

**1. Bring the commit over.** After this branch is committed, bundle it on Windows and copy
the bundle to `/root/` on the VPS:

```sh
git bundle create msxp-resident-tesseract.bundle research/resident-tesseract
```

**2. On the VPS, in one root shell (`sudo -i`), check out the commit and record the environment:**

```sh
cd /opt/msxp/bench
git fetch /root/msxp-resident-tesseract.bundle research/resident-tesseract
git checkout --detach FETCH_HEAD && git log -1 --oneline     # Record this hash.
tesseract --version 2>&1 | head -3; tesseract --list-langs 2>&1 | head -1
ldconfig -p | grep libtesseract        # Must list libtesseract.so.5. Do NOT install anything.
sha256sum /usr/share/tesseract-ocr/*/tessdata/eng.traineddata
nproc; lscpu | grep -E 'Model name|Thread|Core|Hypervisor'
command -v ffprobe || echo 'ffprobe missing: report it; do not install anything'
```

**3. Paste the helpers into the same shell.** `rtrun` runs in a subshell, so it never changes
your shell's options. It repeats the production check itself and writes each run to a new
`private/bench/rt/NAME-UTCSTAMP/` directory; creating that directory fails rather than reuse
one.

A run passes only if both of these hold:

- the `systemd-run | tee` pipeline succeeds, which `pipefail` reports even through `tee`;
- the run's own `result.json` verifies. The benchmark creates that file empty at start and
  writes the JSON only when it finishes. For parity runs, the check requires no mismatches,
  no repeat-pass mismatches, and every frame identical for both engines.

The journal and the unit output are kept beside the result either way.

```sh
cd /opt/msxp/bench
PY=/opt/msxp/app/.venv/bin/python                 # Installed app venv (Pillow, pytesseract, psutil), used read-only.
VIDEO=/opt/msxp/app/private/stress15/hud-long.mp4 # Existing local offline recording; no live video or network.

production_idle() {  # Read-only: never stops, starts or changes a production unit.
  busy=0
  for unit in msxp-tracker.service msxp-backup.timer msxp-backup.service; do
    if systemctl is-active --quiet "$unit"; then echo "ABORT: $unit is active" >&2; busy=1; fi
  done
  [ "$busy" -eq 0 ] && echo 'production units inactive'
}

rtrun() (  # rtrun NAME BENCHMARK-ARGS...: one sandboxed run into a NEW private/bench/rt/NAME-UTCSTAMP/
  set -euo pipefail -o noclobber
  name=$1; shift
  case $name in ''|*[!A-Za-z0-9-]*) echo "NAME must be letters, digits and dashes" >&2; exit 1;; esac
  [ "$(pwd -P)" = /opt/msxp/bench ] || { echo "run from /opt/msxp/bench" >&2; exit 1; }
  production_idle
  out=private/bench/rt/$name-$(date -u +%Y%m%dT%H%M%SZ)
  sudo -u msxp mkdir -p private/bench/rt
  sudo -u msxp mkdir "$out"           # Fails rather than reuse an existing directory.
  echo "output: $out"
  status=0
  systemd-run --unit="msxp-bench-rt-${out##*/}" --wait --collect \
      -p User=msxp -p Group=msxp -p WorkingDirectory=/opt/msxp/bench \
      -p ProtectSystem=strict -p ReadWritePaths=/opt/msxp/bench/private -p PrivateTmp=yes -p PrivateNetwork=yes \
      -p RuntimeMaxSec=3600 -p MemoryAccounting=yes \
      -E HOME=/opt/msxp -E PYTHONDONTWRITEBYTECODE=1 -E PYTHONUNBUFFERED=1 -E OMP_THREAD_LIMIT=1 \
      "$PY" tools/benchmark_resident_tesseract.py "$@" --output "$out/result.json" 2>&1 \
    | tee "$out/unit" || status=$?    # pipefail: systemd-run's status survives tee.
  journalctl -u "msxp-bench-rt-${out##*/}.service" -o cat --no-pager > "$out/log" || true
  # Judge the run by its own result file, not by systemd wording: the benchmark claims the
  # file (empty) at start and writes the JSON only at the very end.
  sudo -u msxp "$PY" -I - "$out/result.json" <<'EOF' || status=1
import json, sys
try:
    result = json.load(open(sys.argv[1], encoding='utf-8'))
except (OSError, ValueError):
    sys.exit('NO RESULT: the benchmark did not finish; read the log')
if 'throughput' in result:
    engines = result['throughput']
    if set(engines) != {'baseline', 'inprocess', 'worker'}:
        sys.exit('INCOMPLETE THROUGHPUT RESULT')
    print('frames/s:', {name: row['frames_per_second'] for name, row in engines.items()})
else:
    s = result['summary']
    print(json.dumps({key: s[key] for key in ('frames', 'calls', 'identical_frames', 'cpu_seconds_per_frame')}))
    print('environment:', json.dumps({key: s['environment'][key] for key in ('cli_version', 'library', 'model_sha256')}))
    if s['mismatches'] or s['repeat_mismatches'] or any(v != s['frames'] for v in s['identical_frames'].values()):
        sys.exit(f"PARITY FAILED: {len(s['mismatches'])} mismatches, {len(s['repeat_mismatches'])} repeat mismatches")
    print('PARITY OK')
EOF
  [ "$status" -eq 0 ] || { echo "$name: FAILED (status $status); evidence kept in $out" >&2; exit 1; }
  echo "$name: OK; evidence in $out"
)
```

**4. Preflight (read-only), then the runs.** Stop at the first failure:

```sh
production_idle || exit 1
sudo -u msxp head -c 1 "$VIDEO" > /dev/null && echo "video readable by msxp: $VIDEO"
DUR=$(sudo -u msxp ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO"); echo "duration ${DUR}s"
FRAMES=$("$PY" -c "import sys;d=float(sys.argv[2]);print(' '.join(f'{sys.argv[1]}@{d*(i+.5)/56:.1f}' for i in range(56)))" "$VIDEO" "$DUR")
FEW=$(printf '%s\n' $FRAMES | awk 'NR%5==1' | tr '\n' ' ')   # 12 of the 56 frames, for throughput.

rtrun parity $FRAMES --composites &&   # About 25 min: 56 frames + composites; parity and per-call cost.
rtrun tp1 $FEW --processes 1 &&
rtrun tp2 $FEW --processes 2 &&
rtrun tp4 $FEW --processes 4 &&
echo 'ALL RESIDENT-TESSERACT RUNS PASSED'
```

**5. Paste back** the terminal output: each run's `output:` line, the parity summary and
`environment` lines, the throughput frames/s lines, and step 2. Each run's directory holds
the complete `result.json`, `unit` and `log`, all private under the bench checkout. To
remove a run later, delete only the directories its `output:` lines named, for example
`rm -r -- private/bench/rt/parity-20261022T101500Z`. Never delete `private/bench/rt` itself,
because it may hold other benchmark evidence.

**Acceptance:**

- `parity` prints `PARITY OK` (no mismatches, no repeat mismatches, every frame identical
  for both engines);
- `cpu_seconds_per_frame.worker` is at least 10 % below `baseline`;
- `tp4` worker frames/s is above baseline.

All 56 frames come from one recording, which gives less scene variety than the Windows
corpus, which also had the private challenge frames. The composites add multi-HUD and
obscured scenes.

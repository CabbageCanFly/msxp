# Final real-video level-up validation

2026-10-19, `feat/exp-level-inference`. Offline only; no Twitch connection,
live database writes or coordinator changes. This follow-up supersedes the earlier
question-mark presentation and synthetic-only wrap findings in
[the inference evaluation](exp-derived-level-evaluation.md).

## Real evidence and method

`samples/sample-stream4.mp4`: 180.01 seconds, 1920 × 1080, 138,971,670 bytes.
A visual overview identified a usable native EXP reset between the requested
119- and 120-second frames. The native level region is covered by the separate
left EXP Tracker overlay; that overlay remains stale and is not OCR evidence.
The right webcam does not cover the native EXP field.

Reused `evaluate_adaptive_hud.frame_at`, `shadow_capture.prepare/analyze/neural_line`,
`Diagnostics`, `Store`, and the existing public player projection. No OCR,
grammar, localization, confidence or inference policy was adjusted. The 49
sample offsets are the union of `range(0,180,5)`, `range(110,126)` and `{179}`.
They are purposive, correlated samples, not an accuracy estimate for a live
sampling schedule. Processing took 189.92 seconds.

The JSONL explicitly marks offline replay. Requested video offsets are mapped
onto an arbitrary `2026-01-01T00:00:00Z` origin to preserve elapsed intervals;
these are not broadcast timestamps. Exact decoder PTS was not independently
verified. Full-frame PNG hashes were checked against every recorded attempt.
Local receipt age measures offline processing age, not Twitch freshness.

## Results

48/49 frames have exactly one HUD candidate. All 44 accepted strict EXP pairs
match visual inspection of their saved crops. Four malformed pairs are rejected;
the remaining frame has no game HUD. There are no false accepted readings in
this selected set. Missing native level crops stay explicitly unavailable.

| Video offset | Native EXP / percentage | Existing inference / new public label |
| --- | --- | --- |
| 0 s | 353,822 / 99.13% | No established level yet |
| 10 s | 354,036 / 99.19% | EXP-derived 42 established from three samples; `Lv. 42` |
| 119 s | 356,906 / 99.99% | EXP-derived 42; `Lv. 42` |
| 120 s | 0 / 0.00% | OCR `010.00%]` rejected; retained 42 |
| 121 s | 10 / 0.00% | Possible 42→43; public `Lv. 43`, evidence remains possible |
| 122–123 s | 38 / 0.01%, 54 / 0.01% | Still possible; public `Lv. 43` |
| 124 s | 80 / 0.02% | Provisional 43; `Lv. 43` |
| 125 s | 98 / 0.03% | Provisional 43 continues |
| 130 s | 134 / 0.03% | Provisional 43 continues |
| 145 s | Game feed black; stale separate overlay still visible | Zero candidates; last public level retained |
| 150–179 s | 134 / 0.03% | Reacquired HUD; provisional 43 continues |

Other rejected raw strings: 70 s `355,537[99.61%1`, 114 s
`356,786[99.96%1`, 118 s `356,876199.99%]`. None is repaired or supplied manually.
The 120-second frame also shows the level-up animation and increased HP/MP
maxima. At 150 seconds the game's party list visibly shows `TriciaBirdy`, level
43. This is independent manual corroboration, not input to inference or automatic
identity recognition. Old level 42 is established arithmetically from native EXP.

The existing accounting projection contains 40 intervals: 29 at level 42 using
displayed percentage endpoints, 11 at level 43 using observed EXP endpoints.
No included interval overlaps the uncertain 119–124-second transition. The first
new-level counted interval is 80→98; subsequent progress reaches 134. No threshold
completion or initial 0→80 gain is invented. Trusted `observations` remains empty.

The real clip proves establishment, wrap detection, provisional next-level
tracking, recovery after a HUD gap, and exclusion of uncertain boundary EXP.
It does **not** prove automatic corroboration: progression stops at 0.03%, where
EXP/percentage arithmetic remains ambiguous. Corroboration, contradictory wraps,
reversion and other adversarial transitions remain covered synthetically.

## Presentation and isolated preview

The shared public formatter shows the proposed next level during the possible
phase, and omits question marks for provisional levels. Homepage level sorting
uses the same presented value. Announcements and chart labels omit question
marks. Hover provenance, Advanced, inference evidence, percentage quarantine,
and accounting boundaries are unchanged. In the possible phase the API still
retains level 42 and the last accepted percentage while verifying the reset;
only the public level label shows 43, deliberately.

The existing `product_updates_fixture.py` has a small `--replay-log` mode. It
accepts a completed private local-video JSONL with at most 60 attempts / 4 MiB,
creates a fresh private database, and appends only the chosen causal prefix.
The local review clock freezes at that prefix, not the present day. There are
no capture workers or HTTP writes. The fixture binds loopback and restores its
clock on exit. Its terminal accepts offsets, `next`, or `all`, forward only.

Run from PowerShell, using a **new** output directory on each launch:

```powershell
Set-Location H:\Desktop\codex\msclassic-level-inference
& ..\msclassic-twitch-exp-tracker\.venv\Scripts\python.exe tools/product_updates_fixture.py `
  --directory private/levelup-final/preview-user-01 --port 8788 `
  --replay-log private/levelup-final/capture.jsonl
```

Open http://127.0.0.1:8788/stream/video_review for history, http://127.0.0.1:8788/
for the homepage, http://127.0.0.1:8788/live/overlay/video_review for OBS, and
http://127.0.0.1:8788/dashboard/video_review for Advanced. In the server terminal,
enter `10`, `119`, `121`, `124`, `130`, `179`, each followed by Enter. Pages poll
automatically. Select **Level %** to inspect the wrap and missing boundaries.
To rewind, stop with Ctrl+C and relaunch with another new directory. Saved-video
pages can say capture stopped; this preview never represents a running capture.

## Artifacts and checks

All generated evidence is ignored under `private/levelup-final/`: native frames,
`capture/` EXP crops, `capture.jsonl`, `prefix-results.json`,
`observations-compact.csv`, `rolling-history.json`, visual contact sheets,
`replay.sqlite3`, and isolated preview databases. `browser-{10,121,124,179}/`
contains 28 localhost browser screenshots and verification reports;
`browser-stages.json` records the four causal public payloads.

- Full Python suite: **1,631 passed, 102 skipped**. Skips: 100 absent private
  fixtures, one Windows symlink permission, one sandbox loopback restriction.
- All six frontend test files: **85 passed**, including shared level labels,
  hover provenance, announcement/chart labels and unmodified underlying values.
- New preview tests: **8 passed** (included above), covering causal prefixes,
  empty trusted observations, clock restoration, input bounds, local-source
  restriction and refusal of external/existing output directories.
- Existing headless browser checks passed at all four checkpoints, covering the
  homepage, character history and transparent OBS overlay. Browser/server ran
  together outside the sandbox because its Chrome and loopback restrictions
  prevented that combination inside it; no remote capture was involved.

Recommendation: **ready to merge**, with provisional status and the existing
table/retention limitations preserved. This clip adds real wrap evidence; it
does not establish live freshness, universal OCR accuracy, or arithmetic
corroboration at very low percentages. No merge or push was performed.

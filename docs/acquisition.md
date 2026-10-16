# Acquisition feasibility

This is the Phase 0/1 research snapshot. The subsequent remote-capture experiment
is documented in [live-capture.md](live-capture.md); its implementation and newer
measurements supersede the “not implemented” entries below for that experiment.

Research checked 2026-10-15. **No Twitch or OBS live capture was verified.**
Offline screenshot OCR is verified; the probes below are reproducible experiments.
The reference application's URLs could not be inspected successfully using the
research tool, so nothing here assumes how that service acquires images.

## Recommendation and decision gate

Try official Twitch thumbnails first because they need no streamer software or
OBS changes. Accept several-minute latency only if a measured thumbnail retains
enough HUD detail. For fresh 30–60 second readings, investigate a browser page
connecting locally to OBS WebSocket and uploading only calibrated HUD crops.
That route uses built-in OBS functionality but needs more than pasting an overlay
URL: enable authenticated WebSocket, select a game source, and calibrate the crop.
Browser/CEF compatibility remains a decision gate. Do not promise a URL-only
fresh-capture product until one of these paths passes a real streamer trial.

## Comparison

| Approach | Streamer setup | Freshness / OCR detail | Cost and reliability | Current status |
| --- | --- | --- | --- | --- |
| Helix stream thumbnail | Channel entry; developer registers app and keeps app token server-side | Up to five-minute-old frame; requesting a large image may not recover native detail | Small HTTP transfers, no video decoder; CDN caching, scene changes and compression can prevent useful readings | Official API documented; offline probe tests pass; no live measurements |
| Decode live stream remotely | Few OBS changes if an authorized playback source exists; creator permission alone does not establish platform permission | Potentially source-resolution images near live edge; segment latency and ads remain | Video bandwidth, decoder startup, reconnects and worker RAM; no documented general Helix live-frame endpoint found | Not implemented or live-tested; platform authorization unresolved |
| Browser to local OBS WebSocket | OBS 28+; enable password authentication; select source and crop in a browser dock/page | Local source pixels without Twitch encoding; request every 30–60 seconds if stable | Screenshot encoding and browser work on streamer's PC; crop OCR on VPS; reconnect/hidden source behavior must be tested | OBS API documented; protocol mock tests pass; real browser/OBS capture untested |

### Official Twitch thumbnails

[`Get Streams`](https://dev.twitch.tv/docs/api/reference/#get-streams) accepts app
or user access tokens and provides a thumbnail URL with requested dimensions.
The documented image is a frame from the last five minutes, not a new frame per
request. It provides no precise image capture timestamp. A cache-busting query
can avoid a cached response but cannot force new capture. API success and CDN
response timestamps must not become claims of frame freshness. An empty stream
list for a previously resolved user means offline.

Developer setup: register a Twitch application and obtain an app access token
using the documented [client credentials flow](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#client-credentials-grant-flow).
This prototype expects a token supplied in environment variables; it does not
implement token renewal. No broadcaster login is needed for this particular
public stream lookup. A future site must prove channel ownership separately.
Respect [rate-limit headers](https://dev.twitch.tv/docs/api/guide/#twitch-rate-limits);
the probe reports HTTP errors and exits rather than retrying aggressively.

For 1–5 streamers, polling each minute is only 1–5 API lookups/minute, plus image
fetches; a future worker can batch stream lookups. At an **assumed** 200 KB/image,
five channels each minute use about 1.44 GB/day of inbound image traffic. Measure
actual sizes and VPS transfer accounting. CPU is mostly short OCR jobs. RAM can
stay bounded with one worker and small crops. Thumbnail quality at 1920x1080 is
unverified: a large JPEG could still contain upscaled or compressed tiny glyphs.

Run from the installed virtual environment (use its Python executable):

```powershell
# Set these locally; do not paste their values into chat, Git or an overlay URL.
$env:TWITCH_CLIENT_ID = '<your application client ID>'
$env:TWITCH_ACCESS_TOKEN = '<your app access token>'
.\.venv\Scripts\python -m exp_tracker.twitch_probe telfer1 --count 15 --interval 60 --width 1920 --height 1080 --config configs/stream1.json
```

Use a live channel you control or have consent to test. The existing config is
only suitable if its layout matches; otherwise omit `--config` to measure images
without OCR, or calibrate fresh normalized ROIs. The probe resolves the channel,
checks online status and emits JSON lines with byte size, dimensions, image/HUD
hashes, CDN cache headers and optional OCR. It never writes images. A changing
hash establishes changed pixels, not when the frame was captured. Unchanged HUD
pixels can also mean genuinely unchanged EXP. Compare with a visible clock and
known EXP changes over at least 15 minutes. Never relabel repeats as new gains.

### Periodic frame extraction

FFmpeg can decode an authorized video input and emit occasional PNGs; its
[`fps` filter](https://ffmpeg.org/ffmpeg-filters.html#fps) selects output frequency.
Selecting one frame/minute generally does **not** avoid receiving/decoding the
intervening video. Reopening the source per sample may reduce time connected,
but introduces connection cost, live-edge delay and segment/keyframe waits.

An illustrative calculation: continuous 3 Mbps input is about 32.4 GB/day/channel,
or 162 GB/day for five channels. Decoder CPU/RAM are not benchmarked; five live
decoders plus OCR are a poor initial assumption on a 1 vCPU / 1 GB VPS. Lower
renditions save bandwidth but discard exactly the HUD detail needed for OCR.
A headless playback browser adds substantial overhead and cross-origin canvas
restrictions; embedding the Twitch player does not grant raw frame access.

The [Twitch Developer Agreement](https://legal.twitch.com/en/legal/developer-agreement/)
limits access to documented developer interfaces absent permission and includes
data consent/deletion and content storage conditions. The
[Terms of Service](https://www.twitch.tv/p/terms-of-service) restrict automated
extraction and downloading outside authorized uses. Public availability and
streamer consent do not themselves authorize undocumented playback-token or
playlist extraction. Obtain platform clarification for the intended method
before production use. This is an engineering constraint, not a legal clearance.

No scraping tool or Twitch playlist resolver was added. To reproduce only the
decoder experiment on a local video you own, install FFmpeg on your development
machine and run (not executed in this session):

```powershell
New-Item -ItemType Directory -Force artifacts/frames | Out-Null
ffmpeg -hide_banner -i private/authorized-recording.mp4 -an -vf "fps=1/60" -frames:v 3 artifacts/frames/frame-%03d.png
```

For a permitted live input, benchmark startup latency, reconnect behavior,
resident RAM, CPU time and received bytes for a 15-minute trial. Do not put
playback credentials in committed scripts or logs. Delete temporary frames.

### OBS without an extra installed helper

OBS documents [WebSocket built in since OBS 28](https://obsproject.com/kb/remote-control-guide).
[`GetSourceScreenshot`](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md#getsourcescreenshot)
returns a base64 image from an input or scene. Omitting requested dimensions uses
the source resolution; width/height parameters scale rather than crop. There is
no crop rectangle parameter. The client must crop in memory, or the streamer
must deliberately configure a separate cropped source. Capture the game input
to avoid overlays and recursive captures of the acquisition page itself.

OBS's [Browser Source integration](https://github.com/obsproject/obs-browser#control-obs)
documents status and controls but no direct screenshot bridge. A Browser Source
URL alone should not be assumed to grant capture access. A local WebSocket
connection is a separate authenticated operation with broad OBS control rights.
Keep the server private/firewalled; no public port forwarding. The backend must
never receive the OBS password, and public overlay URLs must never contain it.

The proposed zero-download client is a hosted browser page/dock that asks for
the password locally, connects to `ws://127.0.0.1:4455`, captures the selected game
input and crops before upload. This is an **untested proposal**. HTTPS-to-loopback
connections vary across browser/CEF versions and
[local network access controls](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Local_network_access).
Do not disable browser security or authentication to make this work. A normal
browser page may work while a Browser Source does not, or vice versa.

Executable local developer harness:

```powershell
.\.venv\Scripts\python -m http.server 8765 --bind 127.0.0.1 --directory tools
```

1. In OBS 28+, enable Tools → WebSocket Server Settings and password authentication.
2. Open `http://127.0.0.1:8765/obs-probe.html` in a browser or custom browser dock.
   Serving only `tools/` avoids exposing the project or private files.
3. Enter the password, exact game input name, and normalized HUD crop. Credentials
   are held only for the in-memory challenge; no localStorage, cookies or URL secrets.
4. Capture once. The page displays only the crop, timing, source dimensions,
   active/showing status and crop hash. It does not upload anything. Download is
   explicit. Save any crops under ignored `artifacts/` or `private/`.
5. Capture again after 30–60 seconds with known EXP changes; verify the game HUD,
   compare values, and test inactive scenes, minimized OBS, disconnect/reconnect,
   a wrong password and source rename. Do not infer Twitch live status from the
   source being available.
6. A successful localhost test does not prove hosted HTTPS/CEF compatibility.
   Test that separately with a reviewed capture page before recommending this
   setup to streamers. The developer's Python HTTP server is just a test fixture,
   not a required streamer-side helper in the proposed product.

At 30–60 second intervals this avoids continuous video decoding on the VPS.
Screenshot readback/PNG encoding, base64 allocation and cropping still cost
streamer CPU/GPU/RAM. Full pixels briefly exist locally; only crops should leave
the PC in a future service. Benchmark OBS frame time and browser memory. OBS
authentication is not screenshot-only, so trust in the page's code is necessary;
use no third-party scripts and keep capture controls separate from public overlays.

## Outstanding evidence

- Twitch live thumbnail dimensions, real refresh cadence and HUD OCR accuracy.
- Whether derived historical EXP storage needs additional platform permission;
  implement consent, deletion and minimum retention regardless.
- Actual OBS version/OS/CEF behavior and safe HTTPS-to-loopback operation.
- Capture freshness when a game input is inactive, frozen or obscured.
- Measured VPS peak memory/CPU and streamer's OBS frame-time cost.
- Authorized remote live playback path, if still needed after the first two trials.

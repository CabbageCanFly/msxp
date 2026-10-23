# MSXP: MapleStory Classic EXP tracker

MSXP watches MapleStory Classic streams on Twitch, reads the EXP bar straight from the video,
and turns it into a live leaderboard: EXP per hour, time to the next level, 24-hour history
and a stream overlay for OBS. It is free, open source (MIT) and runs on your own computer
or a small server. **See it live: [msxp.pages.dev](https://msxp.pages.dev)**

Nobody installs anything on the streamer's side: MSXP only watches the public stream.

![MSXP leaderboard showing player levels, EXP progress and recent EXP per hour](docs/images/leaderboard.png)

*Leaderboard with player levels, EXP progress and recent EXP/hour.*

---

## Try it in 5 minutes

You need **[Python 3.11 or newer](https://www.python.org/downloads/)** (on Windows, tick
"Add python.exe to PATH" in the installer) and **[Git](https://git-scm.com/downloads)**.

```sh
git clone https://github.com/CabbageCanFly/msxp.git
cd msxp
```

| Windows (PowerShell) | macOS / Linux |
| --- | --- |
| `.\msxp install` | `./msxp install` |
| `.\msxp demo` | `./msxp demo` |

`install` sets everything up and tells you if anything is still missing. `demo` opens your
browser on a leaderboard with made-up players.

**Ctrl+C** is your best friend for stopping things in the terminal.

> Below, commands are written as `msxp ...`. Type `.\msxp ...` on Windows or `./msxp ...` on
> macOS/Linux, from the project folder.

## Track real streams

1. **Check your setup:** `msxp doctor`. Fix anything marked `[!!]`; it prints the exact command.
   Capturing needs **Tesseract** and **FFmpeg** besides Python.
2. **Create your tracker:** `msxp setup` (once).
3. **Add a streamer:** `msxp admin` opens the admin page. Choose **Add streamer**, type their
   Twitch name, tick **I have permission to capture this stream** and **Enable tracking**, then
   **Confirm settings**.
4. **Start tracking:** `msxp tracker`. Keep it running; your leaderboard is at
   <http://127.0.0.1:8765/>. Characters are recognized from the name shown in game, and readings
   appear while the streamer is live and playing MapleStory Classic.
5. **Add the overlay to OBS:** open the streamer's page on your leaderboard, pick a style under
   the overlay builder, click **Copy URL**, and follow **How do I add this to OBS?** right there.

Want the leaderboard to show who is live? Add free Twitch app keys to `.env` (next section).

![Player profile showing recent pace, next-level estimates and EXP history](docs/images/player-profile.png)

*Player profile with recent pace, next-level estimates and EXP history.*

![Stream overlay builder showing settings, preview and Copy URL button](docs/images/overlay-builder.png)

*Overlay settings, preview and URL for an OBS Browser Source.*

## Commands

| Command | What it does |
| --- | --- |
| `msxp install` | Installs the Python packages and the OCR engine, then checks your setup |
| `msxp doctor` | Shows what is installed, missing or misconfigured, with the fix (alias `diag`) |
| `msxp demo` | The website with fictional players; nothing else needed |
| `msxp setup` | Creates your tracker database |
| `msxp admin` | Add streamers, confirm permission, start or pause tracking |
| `msxp tracker` | Captures the streams and serves your leaderboard |
| `msxp api` | Only the website, from an existing database, without capturing |
| `msxp dashboard` | Operator view: every capture's details per streamer, read-only (`msxp tracker` includes it at `/dev/streams`) |
| `msxp health` | Missed captures in the last hour, and why |
| `msxp cleanup` | Keeps only the last 24 hours of raw readings (`--apply` to actually delete) |
| `msxp test` | Runs the test suite |
| `msxp where` | Where your settings, database, logs and backups are |
| `msxp logs` | Shows the log (on a server: `tracker`, `api` or `cleanup`) |
| `msxp server ...` | Runs any command on your server over SSH (see [Put it online](#put-it-online)) |
| `msxp help` | This list, plus where your settings live |

Every command prints the tool it runs underneath, and passes any extra options through
(for example `msxp tracker --check` only checks, without capturing).

## Settings and secrets

Everything personal lives in **`.env`** in the project folder. `msxp install` creates it from
[`.env.example`](.env.example). Git ignores it, so it is never committed.

| Setting | Default | Meaning |
| --- | --- | --- |
| `MSXP_DATABASE` | `private/msxp/tracker.sqlite3` | Your tracker database |
| `MSXP_PORT` | `8765` | Your leaderboard website |
| `MSXP_ADMIN_PORT` | `8766` | The admin page (only reachable from your computer) |
| `MSXP_DASHBOARD_PORT` | `8767` | The operator dashboard (only reachable from your computer) |
| `MSXP_WORKERS` | `2` | Streams captured at the same time |
| `MSXP_SERVER` | none | Your server's SSH login, for `msxp server` (e.g. `root@203.0.113.7`) |
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | none | Optional. Shows who is live. Create a free app at [dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps) |

Your data stays in the ignored `private/` folder. Keys never appear on the website or in overlay links.

## Put it online

The live site runs the tracker on a small Ubuntu server, around the clock, and the website on
Cloudflare Pages. To set one up, start with [`deploy/install-ubuntu.sh`](deploy/install-ubuntu.sh)
and the [server guide](docs/vps-deployment.md). On the server, the project lives in `/opt/msxp/app`,
runs as the `msxp` user, and keeps its settings in `/etc/msxp/` (msxp reads them there too).

**Manage it from your own computer.** Put your server's SSH login in your local `.env`
(`MSXP_SERVER=root@203.0.113.7`), then:

| From your computer | What it does |
| --- | --- |
| `msxp server admin` | Opens the server's admin page in your browser through a private SSH tunnel; Ctrl+C closes it |
| `msxp server logs` | Follows the server's logs (`msxp server logs api` for just the website) |
| `msxp server health` | Missed captures on the server in the last hour |
| `msxp server where` | Where everything lives on the server |
| `msxp server dashboard` | Opens the server's operator dashboard the same way; Ctrl+C closes it |
| `msxp server doctor` | Checks the server's setup |

The admin page and dashboard are never exposed to the internet: they only listen on the server
itself, and the tunnel brings them to your computer. The dashboard adds some CPU load while it is open. **Updating the server** after you push changes:
`ssh root@your-server "cd /opt/msxp/app && git pull --ff-only && systemctl restart msxp-api msxp-tracker"`.
The [docs index](docs/README.md) lists the deeper server guides.

## When something is off

- **`msxp` is not recognized:** run it from the project folder as `.\msxp` (Windows) or `./msxp`.
- **Tesseract or FFmpeg not found right after installing:** open a new terminal so it sees them.
- **"Port ... is in use":** it is probably already running. Or pick another port in `.env`.
- **A streamer shows no EXP:** they must be live *in the MapleStory Classic category* with the
  game's EXP bar visible. `msxp health` shows what each capture saw.
- **"Loading EXP…" right after a restart:** the website rebuilds every page; give it a few minutes.

## How it works

Every 20 seconds per stream: grab one video frame with Streamlink and FFmpeg, find the game's
status bar, read level and EXP with Tesseract and RapidOCR, and accept the reading only when the
numbers pass its checks. Readings go into SQLite, and a read-only web server turns them into the
leaderboard, history charts and overlays. When a reading is uncertain, MSXP rejects it and keeps
the last good one rather than guessing. The [docs index](docs/README.md) covers the design, accuracy tests and operations;
the previous, longer README is [here](docs/legacy-readme.md).

## Credits and license

MIT licensed ([LICENSE](LICENSE)). A non-commercial fan project, **not affiliated with Nexon**.

The Sleepywood and Kerning City backgrounds (`src/exp_tracker/web/sleepywood*.webp`, `kerning*.webp`)
and the monster sprites in `src/exp_tracker/web/mobs/` are MapleStory artwork © Nexon, rendered from
game data by [maplestory.io](https://maplestory.io) (GMS v55 and v83); the Slime is the animated WebP
from [meowdb.com](https://meowdb.com/msclassic/es/monsters/7). They only decorate the website.
Details: [website background sources](docs/website-background.md).

# Optional Twitch Turbo playback authentication

[Twitch Turbo](https://help.twitch.tv/s/article/twitch-turbo-guide?language=en_US)
provides ad-free viewing, with exceptions such as channel sponsorships.
[Streamlink documents browser-token authentication](https://streamlink.github.io/cli/plugins/twitch.html#authentication)
as a way Turbo may prevent embedded ads. This is not a guarantee of uninterrupted
capture; ordinary networking, expired authentication and unreadable HUDs still apply.

This authenticates playback as your account. Keep the existing application
credentials for `--twitch-status` unchanged: they do not carry your Turbo benefits.
No new dependencies or tracker command-line flags are required.

## 1. Get your own browser token

Activate Turbo on the account you intend to use and sign in at `https://www.twitch.tv`.
Open browser developer tools (F12), then the Console. Run this expression from
Streamlink's documentation:

```javascript
document.cookie.split("; ").find(item=>item.startsWith("auth-token="))?.split("=")[1]
```

Copy the result without surrounding quotes. If it is undefined, check your login
and that the console belongs to the Twitch page. This token grants broad account
access: never send it to another person, put it in a command, or include it in Git,
screenshots or shared logs. Streamlink documents password changes or Twitch's
**Sign Out Everywhere** as ways to revoke it; logging out alone is insufficient.

## 2. Configure local Windows capture

Open your existing Git-ignored repository-root `.env`:

```powershell
notepad .env
```

Add this line alongside your existing client ID and client secret. Paste only the
token, without `OAuth`, `Authorization=` or header text:

```dotenv
TWITCH_PLAYBACK_TOKEN=abcdefghijklmnopqrstuvwxyz1234
```

The value above is a dummy example. Keep the file private. No extra path or capture
flag is needed. Run this offline check; it prints only whether a token is present:

```powershell
.\.venv\Scripts\python -c "from exp_tracker.streamlink_playback import playback_token; print('Playback token configured:', bool(playback_token()))"
```

Then run your normal authorized capture command in that terminal. Stop the existing
coordinator before starting its replacement; do not run two writers on one history.
New Streamlink processes load the token; existing connections do not acquire it.
An environment variable overrides the same `.env` key, including an explicit empty
value that disables playback authentication. Keep your app credentials unchanged.

For a bounded comparison independent of the database, this standalone Streamlink
command writes at most 20 seconds of playback into ignored private storage. Pick a
currently live channel whose capture is authorized. It does not start a coordinator:

```powershell
New-Item -ItemType Directory -Force private/streamlink | Out-Null; .\.venv\Scripts\python -m exp_tracker.streamlink_playback --no-config --no-plugin-cache --no-plugin-sideloading --webbrowser false --loglevel error --http-timeout 10 --stream-timeout 15 --stream-segment-timeout 10 --stream-segment-attempts 2 --stream-segment-threads 1 --stream-segmented-duration 20 --output private/streamlink/turbo-trial.ts https://www.twitch.tv/streamer_g worst
```

Do not add `--force`; use a new output filename for another trial. If it stalls,
stop with Ctrl+C after 60 seconds. The requested media duration is not a wall-clock
timeout. Receiving video is a useful check but does not prove every future ad is
prevented. Compare actual capture failures over several normal capture cycles.
Avoid debug/trace logs when sharing results; credentials or signed URLs may appear.

## 3. Configure VPS capture when ready

These are operator instructions only; no installation or restart is automatic.
After updating the reviewed code, open the existing secrets file already read by
the tracker service:

```bash
sudoedit /etc/msxp/msxp.env
```

Add your browser token next to the existing application credentials:

```dotenv
TWITCH_PLAYBACK_TOKEN=abcdefghijklmnopqrstuvwxyz1234
```

Keep the file's existing `root:msxp` ownership and `0640` permissions. Systemd loads
this value into the service environment; no new persistent config path is needed.
From `/opt/msxp/app`, this read-only check verifies presence without printing it or
opening a connection (the service's startup preflight also validates token syntax):

```bash
sudo -u msxp env PYTHONPATH=src .venv/bin/python -c "from exp_tracker.twitch_auth import credentials; print('Playback token configured:', bool(credentials('/etc/msxp/msxp.env', keys=('TWITCH_PLAYBACK_TOKEN',))['TWITCH_PLAYBACK_TOKEN']))"
```

At a planned restart, run `sudo systemctl restart msxp-tracker`, then follow
`sudo journalctl -u msxp-tracker -f`. Editing the environment file does not require
`daemon-reload`. With split services, only capture needs this setting/restart.
This does not migrate, replace or modify the tracking database.

## Behavior and rollback

Only Twitch playback uses `TWITCH_PLAYBACK_TOKEN`. Without a value, capture remains
anonymous. Invalid token syntax or a malformed credentials file fails before
starting capture. The existing bounded `.env` reader is reused, with only the
playback key selected; unrelated status credentials do not affect playback.

The launcher creates an OS-private temporary directory/file containing only
`twitch-api-header=Authorization=OAuth TOKEN`, calls Streamlink in that same
process, and removes the file when Streamlink exits, including handled errors.
This is an internal temporary file, not another operator-maintained location.
A forced process kill or crash can leave a private temporary file until temp
cleanup; the VPS service already uses `PrivateTmp=yes`. Normal process arguments,
capture records and public responses contain no token. `--no-config` still blocks
automatic global/plugin configs. No generic HTTP authorization header is added.

To disable, set this in the existing secrets file, then restart capture:

```dotenv
TWITCH_PLAYBACK_TOKEN=
```

Clear any overriding process environment variable too. Revoke the token separately
if no longer needed. The earlier uncommitted `MSXP_STREAMLINK_CONFIG` option has
been replaced; remove that setting if you tried it. A rejected/expired token is
not automatically renewed or silently retried anonymously; replace it manually
and restart capture. Turbo does not change OCR or EXP acceptance rules.

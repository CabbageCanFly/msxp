# Automatic Twitch status authentication

Keep your existing repository-root `.env` (UTF-8):

```dotenv
TWITCH_CLIENT_ID=your_application_client_id
TWITCH_CLIENT_SECRET=your_application_client_secret
```

That is sufficient; no manually generated access token is needed. `.env` remains
Git-ignored and is never rewritten. `.env.example` contains placeholders only.
No new dependency, account, redirect URI or user sign-in is required by this change.

## Run it

Restart the existing server/coordinator to load the new code. Keep the current
private config, explicit character assignments and capture authorization.

```powershell
# Read-only verification: OAuth + Helix only; no Streamlink, video or thumbnails.
.\.venv\Scripts\python -m exp_tracker.twitch_probe --status-only telfer1 shiphtur

# Read-only website over the existing DB; this starts no capture.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --diagnostic-dashboard --twitch-status

# Preflight your existing multi-stream config; no Twitch connections.
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --check --twitch-status

# Later, for an explicitly permitted capture, use your existing authorized config:
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --continuous --twitch-status
```

The status-only command prints sanitized status JSON. Exit 0 means all requested
logins have known live/offline results; exit 1 means at least one remains unknown.
It does not authenticate streamer or character identity. A standalone invocation
has a separate short-lived in-memory token cache; do not loop this command to
replace the running server's cached checks.

Without `--twitch-status`, normal capture does not load `.env` or contact OAuth.
The single-stream `tools/local_alpha.py` flag works the same way. The old optional
thumbnail experiment remains separate; `--status-only` never downloads an image.

## Credentials and precedence

Each process environment variable overrides the same key in `.env`, including an
explicit empty value. A client secret selects managed app authentication even if
`TWITCH_ACCESS_TOKEN` is also configured. Without a secret, an existing manual
token still works, with validation; it cannot be automatically replaced.

If stale environment variables override your correct file, clear those variables
in that PowerShell process before restarting. To deliberately use legacy manual
authentication despite a secret in the file, explicitly set
`$env:TWITCH_CLIENT_SECRET = ''`. Do not print or share credential values.

The small loader supports blank/comment lines, `KEY=value`, optional `export`,
single/double quotes and trailing comments. It reads only the three Twitch keys,
with a 16 KiB file limit. It does not execute shell text, expand variables, modify
`os.environ`, or support multiline values. Runtime credential edits require a
controlled restart after credentials have been loaded. Tokens are never saved to
the file, SQLite, JSONL, URLs or public HTTP responses.

## Lifecycle and failure handling

[Twitch's Client Credentials Grant](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#client-credentials-grant-flow)
obtains app tokens with a form-encoded POST. The secret is in the HTTPS request
body, never query parameters. App tokens are reacquired; no refresh token is used.

The manager keeps the token and monotonic expiry in memory, renewing on demand
up to 60 seconds early (10% for shorter lifetimes). Before first Helix use, token
validation must succeed and return the configured Client ID. Following
[Twitch's validation guidance](https://dev.twitch.tv/docs/authentication/validate-tokens/),
the running server validates hourly after that first OAuth session starts, even
when its browser is idle. The one server-owned timer stops on server close. An
unused opt-in server has not started an OAuth session and requests no token yet.

A Helix 401 permits one replacement and one retry of that same page, once per
status refresh. Another 401 invalidates the token and backs off five minutes.
Rejected credentials also wait five minutes; transient authentication failures
wait at least 60 seconds. OAuth 429 respects bounded 60–900s Retry-After. An hourly
validation failure is retained as a safe reason and obeys the same backoff.
Concurrent callers share acquisition/validation instead of minting tokens each.

Authentication traffic has 3s transport timeouts, 16 KiB responses and no redirects.
Only fixed Twitch HTTPS endpoints are used. Status cache/pagination remain
separate: 60s Helix cache, at most three pages plus one 401 retry, repeated-cursor
protection, and no offline result unless the relevant pages were completed.
Previously verified live results can survive an interrupted pagination refresh
for their original 60s freshness; unresolved channels remain unknown.

Network work occurs on HTTP status/maintenance threads, not the sequential
capture worker. A slow authentication refresh can delay its HTTP response; it
does not change acquisition scheduling or hold SQLite capture-write transactions.
No trusted tracking data or captured evidence is changed.

Useful safe reasons include `missing_credentials`, `invalid_credentials_file`,
`credentials_rejected`, `invalid_token_validation`, `auth_rate_limited` and
`auth_unavailable`. They never include request bodies, headers or server error
bodies. Missing/invalid authentication means **unknown**, never offline. Correct
the local setup and restart rather than repeatedly launching verification commands.

## Validation

Deterministic tests cover acquisition/cache/expiry, startup/hourly validation and
rescheduling, concurrent acquisition and stale 401s, single retry and backoff,
legacy tokens, file precedence/limits, malformed responses, network/rate failures,
partial pagination safety, server timer shutdown and SQLite writes while auth waits.
Existing pagination regression tests remain green.

```powershell
.\.venv\Scripts\python -m pytest tests/test_twitch_auth.py tests/test_twitch_probe.py tests/test_hud_resilience.py -q --basetemp private/twitch-auth/focused-new
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/twitch-auth/full-new
```

Full suite: **1,381 passed, zero skips**, in 95.34s; **70 Node tests passed**.
`git diff --check` passed. An earlier restricted focused
run passed 157 with one existing loopback-policy skip; the full run used normal
localhost permissions. The read-only real check at **2026-10-18 08:40:38 UTC**
succeeded with managed app credentials: Telfer1 live, Shiphtur offline. The entire
command took 0.81s on this workstation; this is one observation, not a latency
guarantee. Expiry, revocation and 401/429 behavior used mocks, not forced live faults.

Changed implementation: `src/exp_tracker/twitch_auth.py`, `twitch_probe.py`,
`server.py`; `.env.example`; focused tests in `tests/test_twitch_auth.py`,
`test_twitch_probe.py`, `test_hud_resilience.py`; isolated browser fixture in
`tools/product_updates_fixture.py`; README, this guide and the status guide.
The real `.env` was not modified or printed. No new Twitch capture, model change,
schema migration, commit or push was performed.

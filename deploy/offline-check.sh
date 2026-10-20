#!/bin/sh
# Offline end-to-end check of the public API surface, before enabling anything:
# a synthetic database, the tracker (--public-only, CORS) on 127.0.0.1:18765 and
# deploy/Caddyfile served on http://127.0.0.1:18080. No TLS, Twitch or live data.
# Usage, from the checkout: sh deploy/offline-check.sh   (PY=… CADDY=… to override)
set -eu
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
CADDY=${CADDY:-caddy}
ORIGIN=https://msxp.pages.dev
BASE=http://127.0.0.1:18080
tmp=$(mktemp -d)
tracker=; proxy=
trap 'kill $tracker $proxy 2>/dev/null || true; rm -rf "$tmp"' EXIT
failed=0

PYTHONPATH=src "$PY" tools/demo_tracking.py "$tmp/demo.sqlite3" >/dev/null
PYTHONPATH=src "$PY" -m exp_tracker.server --db "$tmp/demo.sqlite3" --port 18765 --public-only \
    --cors-origin "$ORIGIN" >"$tmp/tracker.log" 2>&1 &
tracker=$!
# The production Caddyfile, served over plain HTTP on a spare port without the admin API.
sed -e 's#^API_HOSTNAME {#http://127.0.0.1:18080 {#' -e 's#127\.0\.0\.1:8765#127.0.0.1:18765#' \
    -e '0,/^{$/s//{\n\tadmin off/' deploy/Caddyfile >"$tmp/Caddyfile"
XDG_DATA_HOME=$tmp XDG_CONFIG_HOME=$tmp "$CADDY" run --adapter caddyfile --config "$tmp/Caddyfile" >"$tmp/caddy.log" 2>&1 &
proxy=$!

for _ in $(seq 60); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/players")" = 200 ] && break
    sleep 0.5
done

# check NAME EXPECTED_STATUS EXPECTED_ORIGIN_HEADER(yes|no) URL [curl args]
check() {
    name=$1 want=$2 cors=$3 url=$4; shift 4
    headers=$(curl -s -o "$tmp/body" -D - "$@" "$url" | tr -d '\r')
    status=$(printf '%s\n' "$headers" | head -1 | cut -d' ' -f2)
    allowed=$(printf '%s\n' "$headers" | grep -i '^access-control-allow-origin:' | cut -d' ' -f2 || true)
    ok=yes
    [ "$status" = "$want" ] || ok=no
    if [ "$cors" = yes ]; then [ "$allowed" = "$ORIGIN" ] || ok=no; else [ -z "$allowed" ] || ok=no; fi
    [ "$ok" = yes ] && echo "PASS $name ($status)" || { echo "FAIL $name: status $status, ACAO '$allowed'"; failed=1; }
}
check 'homepage API, allowed origin' 200 yes "$BASE/api/players" -H "Origin: $ORIGIN"
check 'unknown channel error keeps CORS' 404 yes "$BASE/api/players/nobody" -H "Origin: $ORIGIN"
check 'invalid channel error keeps CORS' 400 yes "$BASE/api/players/bad!" -H "Origin: $ORIGIN"
check 'other origin is not allowed' 200 no "$BASE/api/players" -H 'Origin: https://evil.example'
for path in / /stream/demo /live/overlay/demo /static/product.js /dev/api/streams /dashboard/demo \
        /api/streams/demo/state /dev/shadow /admin; do
    check "proxy refuses $path" 404 no "$BASE$path" -H "Origin: $ORIGIN"
done
check 'proxy refuses POST' 404 no "$BASE/api/players" -X POST -H "Origin: $ORIGIN"
check 'tracker itself refuses developer routes' 404 yes http://127.0.0.1:18765/dev/api/streams -H "Origin: $ORIGIN"
encoding=$(curl -s -o /dev/null -D - -H 'Accept-Encoding: gzip' "$BASE/api/players" | tr -d '\r' | grep -i '^content-encoding:' | cut -d' ' -f2 || true)
[ "$encoding" = gzip ] && echo 'PASS responses are compressed (gzip)' || { echo "FAIL compression: '$encoding'"; failed=1; }

[ "$failed" = 0 ] && echo 'Offline check passed.' || { echo 'Offline check FAILED; logs:'; tail -5 "$tmp/tracker.log" "$tmp/caddy.log"; }
exit "$failed"

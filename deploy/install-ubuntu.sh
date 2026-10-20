#!/bin/sh
# Prepare an Ubuntu 24.04 VPS for the EXP tracker backend. Installs and validates only:
# it enables and starts nothing, creates no database and never contacts Twitch.
# Usage (root, from a checkout at /opt/msxp/app): sh deploy/install-ubuntu.sh api.example.org
set -eu

APP=/opt/msxp/app
HOST=${1:-}
[ "$(id -u)" = 0 ] || { echo 'Run as root.' >&2; exit 1; }
[ -n "$HOST" ] || { echo 'Usage: install-ubuntu.sh API_HOSTNAME' >&2; exit 1; }
echo "$HOST" | grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$' || { echo 'API_HOSTNAME must be a DNS name.' >&2; exit 1; }
[ "$(cd "$(dirname "$0")/.." && pwd)" = "$APP" ] || { echo "The checkout must be at $APP (units use that path)." >&2; exit 1; }
cd "$APP"

apt-get update
apt-get install -y python3 python3-venv tesseract-ocr ffmpeg sqlite3 caddy

id msxp >/dev/null 2>&1 || useradd --system --home-dir /opt/msxp --shell /usr/sbin/nologin msxp
# Code stays root-owned and read-only to the service; only private/ is writable.
find "$APP" -path "$APP/private" -prune -o -exec chown root:root {} +  # Rerun-safe: never touches data.
install -d -o msxp -g msxp -m 0750 "$APP/private" "$APP/private/vps" "$APP/private/backups"

[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[capture,dev]'

# Isolated neural OCR worker, pinned as in docs/rapidocr-benchmark.md; shadow_capture uses bin/python.
[ -x private/rapidocr/.venv/bin/python ] || python3 -m venv private/rapidocr/.venv
private/rapidocr/.venv/bin/python -m pip install --only-binary=:all: --index-url https://pypi.org/simple \
    rapidocr==3.10.0 onnxruntime==1.31.0 psutil==7.2.2 Pillow==12.3.0
chown -R msxp:msxp private

[ -e private/vps/config.json ] || install -o msxp -g msxp -m 0640 deploy/config.example.json private/vps/config.json
install -d -o root -g msxp -m 0750 /etc/msxp
[ -e /etc/msxp/msxp.env ] || install -o root -g msxp -m 0640 deploy/msxp.env.example /etc/msxp/msxp.env

install -m 0644 deploy/msxp-tracker.service deploy/msxp-backup.service deploy/msxp-backup.timer /etc/systemd/system/
[ -e /etc/caddy/Caddyfile.dist ] || cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.dist
sed "s/API_HOSTNAME/$HOST/" deploy/Caddyfile > /etc/caddy/Caddyfile
caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
systemctl daemon-reload

echo 'Installed. Nothing was enabled or started. Continue with docs/vps-deployment.md:'
echo '  1. offline validation   2. edit /etc/msxp/msxp.env and private/vps/config.json'
echo '  3. database migration    4. enable msxp-tracker, msxp-backup.timer and reload caddy'

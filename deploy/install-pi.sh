#!/bin/sh
# Prepare a Raspberry Pi OS machine for the photo frame.
# Run on the Pi, from a checkout of this repository. Review before executing.

set -eu

APP_ROOT="${APP_ROOT:-/opt/photo-frame}"
DATA_DIR="${DATA_DIR:-/var/lib/photo-frame}"
USER_NAME="${USER_NAME:-photoframe}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root on the Pi, for example: sudo sh deploy/install-pi.sh" >&2
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip avahi-daemon network-manager curl chromium

if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$USER_NAME"
fi

mkdir -p "$APP_ROOT" "$DATA_DIR/cache" "$DATA_DIR/tmp"
if [ "$PWD" != "$APP_ROOT" ]; then
  cp -a src pyproject.toml README.md "$APP_ROOT"/
fi

python3 -m venv "$APP_ROOT/.venv"
"$APP_ROOT/.venv/bin/pip" install --upgrade pip
"$APP_ROOT/.venv/bin/pip" install "$APP_ROOT"

chown -R "$USER_NAME:$USER_NAME" "$DATA_DIR"
chmod 700 "$DATA_DIR"

install -m 0644 deploy/photo-frame.service /etc/systemd/system/photo-frame.service
install -m 0755 deploy/kiosk.sh /usr/local/bin/photo-frame-kiosk

hostnamectl set-hostname frame || true
if ! grep -q "frame.local" /etc/avahi/avahi-daemon.conf 2>/dev/null; then
  echo "Avahi is installed. Confirm the host publishes frame.local."
fi

systemctl daemon-reload
systemctl enable --now photo-frame.service
systemctl enable --now avahi-daemon.service

echo "Application service enabled. Point the desktop session at /usr/local/bin/photo-frame-kiosk."
echo "Administration: http://frame.local:8080/admin"

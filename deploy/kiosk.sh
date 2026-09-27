#!/bin/sh
# Launch Chromium in kiosk mode against the local presentation view.
# Installed by deploy/install-pi.sh into the graphical session.

set -eu

URL="${1:-http://127.0.0.1:8080/}"
export DISPLAY="${DISPLAY:-:0}"

# Wait until the application answers before opening the browser.
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS "http://127.0.0.1:8080/api/health" >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

if command -v chromium >/dev/null 2>&1; then
  BROWSER=chromium
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER=chromium-browser
else
  echo "Chromium is not installed" >&2
  exit 1
fi

exec "$BROWSER" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --autoplay-policy=no-user-gesture-required \
  --check-for-update-interval=31536000 \
  "$URL"

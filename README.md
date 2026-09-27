# Photo Frame

A one-off appliance that mirrors a single Immich album and presents it as a photo frame. Playback always uses the local cache. Immich remains the source of truth.

This is the v1 implementation of the architecture blueprint: Python, FastAPI, SQLite, a browser presentation view, and a browser admin UI. Hardware-specific pieces (kiosk session, NetworkManager, mDNS) are included as deployment scripts and are exercised on the Pi, not in local tests.

## What works locally

- SQLite schema from the blueprint, with a single migration marker.
- Immich client for server version, album list, album assets, and original download (`x-api-key`).
- Incremental sync with a cheap change hint, plus daily-style full reconciliation.
- Atomic downloads. A failed sync does not delete cached media.
- Reconciliation removes local files only after a successful remote read shows they left the album.
- Selection modes: Now, Newest, Random, Balanced. The 48-hour rule uses `first_seen_at`, not capture date.
- Full-screen presentation page with fade, date overlay, silent video autoplay, and tap-to-enable audio.
- Admin page for Immich settings, connection test, album pick, display settings, manual sync, and Wi-Fi via NetworkManager when `nmcli` exists.
- API key stored in SQLite. It is never rendered back into the admin UI or status JSON.

## What still needs the Pi

- Chromium kiosk autostart (`deploy/kiosk.sh`).
- Avahi hostname `frame.local`.
- First-boot access point. The admin page can ask NetworkManager to join a known network, but creating a temporary setup AP is left to NetworkManager connection profiles on the device.
- HDMI, touch, and codec validation.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/photo-frame
```

Process flags are CLI-only. Everything else is a SQLite setting with a default, editable from the admin page.

```text
photo-frame --host 0.0.0.0 --port 8080 --data-dir ./data --hostname frame --log-level INFO
```

Open `http://127.0.0.1:8080/` for the frame and `http://127.0.0.1:8080/admin` to configure Immich.

To preview the slideshow before Immich is reachable:

```bash
.venv/bin/python -m photo_frame.demo
```

On the admin page:

1. Save the Immich URL.
2. Paste an API key from a dedicated Immich user. Leave the field blank later; the stored key is kept in SQLite and never shown back.
3. Test connection, pick the album, save.
4. Run **Sync now**. Playback starts as soon as files land in the cache.

The API key needs permission to read the album and download originals on your Immich version. Read-only is enough.

## Tests

```bash
.venv/bin/pytest
```

## Raspberry Pi

Review `deploy/install-pi.sh` before running it. It creates a `photoframe` user, a virtualenv under `/opt/photo-frame`, a systemd unit, and installs Avahi, NetworkManager, and Chromium. Point the graphical session at `/usr/local/bin/photo-frame-kiosk`.

Remote maintenance is ordinary SSH. There is no custom updater.

## Layout

```
src/photo_frame/app.py          HTTP coordinator
src/photo_frame/config/         CLI runtime, logging, SQLite settings
src/photo_frame/services/       cache, Immich, selection, sync, network
src/photo_frame/helpers/        models, database, time
src/photo_frame/web/            presentation and admin UI
deploy/                         systemd unit, kiosk script, Pi installer
tests/                          selection, sync, cache, settings, HTTP smoke
```

## Immich endpoints used

- `GET /api/server/version`
- `GET /api/albums`
- `GET /api/albums/{id}`
- `GET /api/assets/{id}/original`

Authentication header: `x-api-key`. Confirm these against the OpenAPI document served by the Immich version you run. See https://api.immich.app/.

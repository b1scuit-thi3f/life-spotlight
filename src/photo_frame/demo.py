"""Seed a local cache with generated photos so the frame can be previewed without Immich."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from photo_frame.config import runtime_from_args
from photo_frame.helpers.db import Database
from photo_frame.helpers.timeutil import to_iso, utc_now


def main(argv: list[str] | None = None) -> None:
    settings = runtime_from_args(argv)
    settings.ensure_dirs()
    db = Database(settings.database_path)
    now = utc_now()
    samples = [
        ("demo-harbour", "Harbour", 40, 90, 140, 2),
        ("demo-field", "Field", 90, 110, 70, 30),
        ("demo-evening", "Evening", 150, 80, 50, 1),
    ]
    for index, (immich_id, _title, red, green, blue, hours_ago) in enumerate(samples, start=1):
        path = settings.cache_dir / f"{immich_id}.png"
        path.write_bytes(_png(red, green, blue, label=index))
        existing = db.execute("SELECT id FROM media WHERE immich_id = ?", (immich_id,)).fetchone()
        if existing:
            continue
        seen = to_iso(now.replace(microsecond=0))
        # The third sample is inside the 48-hour window.
        from datetime import timedelta

        first_seen = to_iso(now - timedelta(hours=hours_ago))
        captured = to_iso(now - timedelta(days=400 * index))
        db.execute(
            """
            INSERT INTO media (
                immich_id, media_type, filename, mime_type, local_path,
                captured_at, first_seen_at, width, height, file_size_bytes, is_present
            ) VALUES (?, 'photo', ?, 'image/png', ?, ?, ?, 640, 360, ?, 1)
            """,
            (
                immich_id,
                f"{immich_id}.png",
                str(path),
                captured,
                first_seen,
                path.stat().st_size,
            ),
        )
    db.close()
    print(f"Seeded demo photos in {settings.cache_dir}")
    print("Start the frame with: photo-frame")
    print("Open http://127.0.0.1:8080/")


def _png(red: int, green: int, blue: int, *, label: int) -> bytes:
    width, height = 640, 360
    row = b"\x00" + bytes([red, green, blue]) * width
    # A pale band so the three slides are distinguishable even if colour is ignored.
    band = b"\x00" + bytes([min(red + 60, 255), min(green + 60, 255), min(blue + 40, 255)]) * width
    raw = b"".join(band if (y // 24) % 2 == label % 2 else row for y in range(height))
    compressed = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        ]
    )


if __name__ == "__main__":
    main()

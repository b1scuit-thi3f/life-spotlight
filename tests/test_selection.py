from __future__ import annotations

import random
from datetime import timedelta

from photo_frame.helpers.models import MediaRecord
from photo_frame.helpers.timeutil import to_iso, utc_now
from photo_frame.services.selection import SelectionEngine


def media(
    media_id: int,
    *,
    first_seen_hours_ago: float = 100,
    captured_at: str | None = None,
    last_displayed_at: str | None = None,
    display_count: int = 0,
    media_type: str = "photo",
    is_present: int = 1,
) -> MediaRecord:
    now = utc_now()
    return MediaRecord(
        id=media_id,
        immich_id=f"asset-{media_id}",
        media_type=media_type,
        filename=f"{media_id}.jpg",
        mime_type="image/jpeg",
        local_path=f"/cache/{media_id}.jpg",
        captured_at=captured_at,
        immich_created_at=captured_at,
        immich_updated_at=captured_at,
        first_seen_at=to_iso(now - timedelta(hours=first_seen_hours_ago)),
        last_displayed_at=last_displayed_at,
        display_count=display_count,
        width=1000,
        height=800,
        duration_seconds=None,
        file_size_bytes=1000,
        checksum=None,
        is_present=is_present,
    )


def test_new_photo_is_classified_by_first_seen_not_capture_date():
    engine = SelectionEngine(new_window_hours=48)
    old_capture = media(1, first_seen_hours_ago=1, captured_at="2001-01-01T00:00:00+00:00")
    assert engine.is_new(old_capture) is True
    recent_capture = media(2, first_seen_hours_ago=72, captured_at=to_iso(utc_now()))
    assert engine.is_new(recent_capture) is False


def test_now_mode_prefers_newly_discovered_media():
    engine = SelectionEngine(new_window_hours=48, rng=random.Random(1))
    old = [media(index, first_seen_hours_ago=200, display_count=0) for index in range(1, 8)]
    fresh = media(99, first_seen_hours_ago=2, captured_at="1999-05-01T00:00:00+00:00")
    picks = [
        engine.choose(old + [fresh], "now").media.id
        for _ in range(20)
    ]
    assert picks.count(99) >= 15


def test_absent_media_is_never_selected():
    engine = SelectionEngine(rng=random.Random(2))
    gone = media(1, is_present=0)
    kept = media(2)
    selection = engine.choose([gone, kept], "random")
    assert selection is not None
    assert selection.media.id == 2


def test_random_mode_avoids_immediate_repetition():
    engine = SelectionEngine(rng=random.Random(3))
    items = [media(index) for index in range(1, 10)]
    first = engine.choose(items, "random")
    second = engine.choose(items, "random", exclude_ids=[first.media.id])
    assert second.media.id != first.media.id


def test_does_not_repeat_when_the_whole_collection_was_just_shown():
    engine = SelectionEngine(rng=random.Random(4))
    items = [media(index) for index in range(1, 4)]
    shown = [3, 1, 2]
    for mode in ("now", "newest", "random", "balanced"):
        nxt = engine.choose(items, mode, exclude_ids=shown)
        assert nxt.media.id != shown[-1]


def test_single_asset_may_repeat():
    engine = SelectionEngine()
    only = media(7)
    nxt = engine.choose([only], "balanced", exclude_ids=[7])
    assert nxt.media.id == 7


def test_newest_orders_by_capture_not_first_seen():
    engine = SelectionEngine()
    older = media(1, first_seen_hours_ago=1, captured_at="2010-01-01T00:00:00+00:00")
    newer = media(2, first_seen_hours_ago=80, captured_at="2024-06-01T00:00:00+00:00")
    selection = engine.choose([older, newer], "newest")
    assert selection.media.id == 2


def test_empty_collection_returns_none():
    engine = SelectionEngine()
    assert engine.choose([], "balanced") is None

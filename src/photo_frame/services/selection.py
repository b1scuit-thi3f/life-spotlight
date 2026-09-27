"""Choose the next eligible local asset. The UI does not embed these rules."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime

from photo_frame.helpers.models import MediaRecord, PresentationMode
from photo_frame.helpers.timeutil import parse_iso, utc_now, within_hours


@dataclass(slots=True)
class Selection:
    media: MediaRecord
    is_new: bool
    reason: str


class SelectionEngine:
    def __init__(self, *, new_window_hours: int = 48, rng: random.Random | None = None) -> None:
        self.new_window_hours = new_window_hours
        self.rng = rng or random.Random()

    def choose(
        self,
        media: list[MediaRecord],
        mode: PresentationMode | str,
        *,
        exclude_ids: list[int] | None = None,
        now: datetime | None = None,
    ) -> Selection | None:
        now = now or utc_now()
        eligible = [item for item in media if item.is_present]
        if not eligible:
            return None
        excluded = set(exclude_ids or [])
        # Never play the same asset twice in a row when another asset exists.
        # Broader exclusion is a preference and is dropped before that hard rule.
        without_recent = [item for item in eligible if item.id not in excluded]
        if without_recent:
            pool = without_recent
        elif excluded and len(eligible) > 1:
            last_id = exclude_ids[-1]
            pool = [item for item in eligible if item.id != last_id] or eligible
        else:
            pool = eligible
        mode = mode if mode in {"now", "newest", "random", "balanced"} else "balanced"
        if mode == "newest":
            chosen = self._newest(pool)
            reason = "newest capture/import"
        elif mode == "random":
            chosen = self._weighted(pool, now, recency_weight=0.15, history_weight=1.4, new_boost=1.3)
            reason = "random with anti-repetition"
        elif mode == "now":
            new_items = [item for item in pool if self.is_new(item, now)]
            chosen = self._weighted(
                new_items or pool,
                now,
                recency_weight=0.4,
                history_weight=0.8,
                new_boost=6.0,
            )
            reason = "new-media priority" if new_items else "no new media; falling back"
        else:
            chosen = self._weighted(pool, now, recency_weight=0.7, history_weight=1.0, new_boost=3.0)
            reason = "balanced"
        return Selection(media=chosen, is_new=self.is_new(chosen, now), reason=reason)

    def is_new(self, item: MediaRecord, now: datetime | None = None) -> bool:
        return within_hours(parse_iso(item.first_seen_at), self.new_window_hours, now)

    def _newest(self, pool: list[MediaRecord]) -> MediaRecord:
        def sort_key(item: MediaRecord) -> str:
            return item.captured_at or item.immich_created_at or item.first_seen_at or ""

        ordered = sorted(pool, key=sort_key, reverse=True)
        # Still skip the most recently displayed item when there is a choice.
        if len(ordered) > 1 and ordered[0].last_displayed_at:
            later = [item for item in ordered if item.last_displayed_at != ordered[0].last_displayed_at]
            if later:
                return later[0]
        return ordered[0]

    def _weighted(
        self,
        pool: list[MediaRecord],
        now: datetime,
        *,
        recency_weight: float,
        history_weight: float,
        new_boost: float,
    ) -> MediaRecord:
        weights: list[float] = []
        for item in pool:
            weight = 1.0
            if self.is_new(item, now):
                weight *= new_boost
            seen = parse_iso(item.first_seen_at)
            if seen is not None and recency_weight:
                age_hours = max((now - seen).total_seconds() / 3600.0, 0.0)
                weight *= 1.0 + recency_weight * (1.0 / (1.0 + age_hours / 24.0))
            displayed = parse_iso(item.last_displayed_at)
            if displayed is None:
                weight *= 1.0 + history_weight
            else:
                hours_since = max((now - displayed).total_seconds() / 3600.0, 0.0)
                weight *= 0.25 + history_weight * min(hours_since / 12.0, 3.0)
            weight /= 1.0 + (item.display_count * 0.15 * history_weight)
            weights.append(max(weight, 0.01))
        return self.rng.choices(pool, weights=weights, k=1)[0]

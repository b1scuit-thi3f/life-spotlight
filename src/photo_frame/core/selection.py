"""Choose the next eligible local asset. The UI does not embed these rules."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from photo_frame.core.time import parseIso, utcNow
from photo_frame.models.display import PresentationMode
from photo_frame.models.media import MediaRecord, Selection


class SelectionEngine:
    def __init__(self, *, newWindowHours: int = 48, rng: random.Random | None = None) -> None:
        self.newWindowHours = newWindowHours
        self.rng = rng or random.Random()

    def choose(
        self,
        media: list[MediaRecord],
        mode: PresentationMode | str,
        *,
        excludeIds: list[int] | None = None,
        now: datetime | None = None,
    ) -> Selection | None:
        now = now or utcNow()
        eligible = [item for item in media if item.isPresent]
        if not eligible:
            return None
        excluded = set(excludeIds or [])
        # Never play the same asset twice in a row when another asset exists.
        # Broader exclusion is a preference and is dropped before that hard rule.
        withoutRecent = [item for item in eligible if item.id not in excluded]
        if withoutRecent:
            pool = withoutRecent
        elif excluded and len(eligible) > 1:
            lastId = excludeIds[-1]
            pool = [item for item in eligible if item.id != lastId] or eligible
        else:
            pool = eligible
        mode = mode if mode in {"now", "newest", "random", "balanced"} else "balanced"
        if mode == "newest":
            chosen = self.newest(pool)
            reason = "newest capture/import"
        elif mode == "random":
            chosen = self.weighted(pool, now, recencyWeight=0.15, historyWeight=1.4, newBoost=1.3)
            reason = "random with anti-repetition"
        elif mode == "now":
            newItems = [item for item in pool if self.isNew(item, now)]
            chosen = self.weighted(
                newItems or pool,
                now,
                recencyWeight=0.4,
                historyWeight=0.8,
                newBoost=6.0,
            )
            reason = "new-media priority" if newItems else "no new media; falling back"
        else:
            chosen = self.weighted(pool, now, recencyWeight=0.7, historyWeight=1.0, newBoost=3.0)
            reason = "balanced"
        return Selection(media=chosen, isNew=self.isNew(chosen, now), reason=reason)

    def isNew(self, item: MediaRecord, now: datetime | None = None) -> bool:
        seen = parseIso(item.firstSeenAt)
        if seen is None:
            return False
        now = now or utcNow()
        return now - seen <= timedelta(hours=self.newWindowHours)

    def newest(self, pool: list[MediaRecord]) -> MediaRecord:
        ordered = sorted(
            pool,
            key=lambda item: item.capturedAt or item.immichCreatedAt or item.firstSeenAt or "",
            reverse=True,
        )
        if len(ordered) > 1 and ordered[0].lastDisplayedAt:
            later = [item for item in ordered if item.lastDisplayedAt != ordered[0].lastDisplayedAt]
            if later:
                return later[0]
        return ordered[0]

    def weighted(
        self,
        pool: list[MediaRecord],
        now: datetime,
        *,
        recencyWeight: float,
        historyWeight: float,
        newBoost: float,
    ) -> MediaRecord:
        weights: list[float] = []
        for item in pool:
            weight = 1.0
            if self.isNew(item, now):
                weight *= newBoost
            seen = parseIso(item.firstSeenAt)
            if seen is not None and recencyWeight:
                ageHours = max((now - seen).total_seconds() / 3600.0, 0.0)
                weight *= 1.0 + recencyWeight * (1.0 / (1.0 + ageHours / 24.0))
            displayed = parseIso(item.lastDisplayedAt)
            if displayed is None:
                weight *= 1.0 + historyWeight
            else:
                hoursSince = max((now - displayed).total_seconds() / 3600.0, 0.0)
                weight *= 0.25 + historyWeight * min(hoursSince / 12.0, 3.0)
            weight /= 1.0 + (item.displayCount * 0.15 * historyWeight)
            weights.append(max(weight, 0.01))
        return self.rng.choices(pool, weights=weights, k=1)[0]

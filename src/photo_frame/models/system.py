"""Storage and sync-interval settings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SystemUpdate(BaseModel):
    cacheCeilingBytes: int | None = Field(default=None, ge=100_000_000, le=2_000_000_000_000)
    reservedBytes: int | None = Field(default=None, ge=0, le=100_000_000_000)
    syncIncrementalMinutes: int | None = Field(default=None, ge=5, le=1440)
    syncReconcileHours: int | None = Field(default=None, ge=1, le=336)
    httpTimeoutSeconds: int | None = Field(default=None, ge=5, le=600)
    downloadTimeoutSeconds: int | None = Field(default=None, ge=30, le=3600)


class SystemState(BaseModel):
    cacheCeilingBytes: int
    reservedBytes: int
    syncIncrementalMinutes: int
    syncReconcileHours: int
    httpTimeoutSeconds: float
    downloadTimeoutSeconds: float

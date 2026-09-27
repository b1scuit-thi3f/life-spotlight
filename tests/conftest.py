from __future__ import annotations

from pathlib import Path

import pytest

from photo_frame.config import RuntimeConfig
from photo_frame.helpers.db import Database
from photo_frame.services.repository import MediaRepository


@pytest.fixture
def settings(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(data_dir=tmp_path / "data")


@pytest.fixture
def db(settings: RuntimeConfig) -> Database:
    settings.ensure_dirs()
    database = Database(settings.database_path)
    yield database
    database.close()


@pytest.fixture
def repository(db: Database) -> MediaRepository:
    return MediaRepository(db)

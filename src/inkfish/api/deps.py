"""inkfish.api.deps — FastAPI dependency-injection factories.

All factories use @lru_cache so repeated calls within one process
return the same object.  Tests can bust the cache via cache_clear() and
override via FastAPI's app.dependency_overrides.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from inkfish.config import Settings, SimConfig, load_config
from inkfish.storage.db import create_db_engine, init_db, make_session_factory
from inkfish.storage.repository import Repository
from inkfish.storage.snapshot import SnapshotManager

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings (loaded once per process)."""
    settings, _ = load_config()
    return settings


@lru_cache(maxsize=1)
def get_sim_config() -> SimConfig:
    """Return the singleton SimConfig (loaded once per process)."""
    _, sim_cfg = load_config()
    return sim_cfg


@lru_cache(maxsize=1)
def _engine_and_factory() -> tuple[object, object]:
    """Create (and cache) the SQLAlchemy engine + session factory.

    Calling this multiple times within one process returns the same pair.
    Tests should call _engine_and_factory.cache_clear() before each test
    when they set INKFISH_DB_URL to a different value.
    """
    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    logger.info("DB engine initialised: %s", settings.db_url)
    return engine, sf


def get_repository() -> Repository:
    """FastAPI-injectable factory: returns a Repository backed by the shared engine."""
    _, sf = _engine_and_factory()
    return Repository(sf)  # type: ignore[arg-type]


def get_snapshot_manager() -> SnapshotManager:
    """FastAPI-injectable factory: returns a SnapshotManager backed by the shared engine."""
    _, sf = _engine_and_factory()
    return SnapshotManager(sf)  # type: ignore[arg-type]

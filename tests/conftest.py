"""Shared pytest fixtures for INKFISH."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from inkfish.storage.db import create_db_engine, init_db


@pytest.fixture
def repo_root() -> Path:
    """Return the absolute path to the repository root."""
    return Path(__file__).parent.parent


@pytest.fixture
def in_memory_engine() -> Generator[Engine, None, None]:
    """Yield a fully-initialised in-memory SQLite engine (function scope).

    Tables are created via ``init_db`` before the test runs and the engine
    is disposed after the test completes — each test gets a clean slate.

    Note: WAL mode is NOT applied to in-memory SQLite (SQLite restriction).
    For WAL tests use the ``tmp_db_engine`` fixture instead.
    """
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def tmp_db_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """Yield a file-backed SQLite engine in a pytest-managed temp directory.

    Uses WAL mode (registered via the ``create_db_engine`` listener).
    The database file is automatically deleted when the test finishes because
    pytest removes the ``tmp_path`` directory on teardown.
    """
    db_file = tmp_path / "test_inkfish.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_db_engine(db_url)
    init_db(engine)
    yield engine
    engine.dispose()

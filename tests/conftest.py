"""Shared test fixtures."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from dmarc_msp.config import Settings
from dmarc_msp.db import Base, init_db


@pytest.fixture
def settings() -> Settings:
    """Return test settings with an in-memory SQLite database."""
    return Settings(
        database={"url": "sqlite:///:memory:"},
        opensearch={"password": "test_password"},
        msp={"domain": "dmarc.test.example.com", "rua_email": "reports@dmarc.test.example.com"},
        dns={"provider": "cloudflare", "zone": "test.example.com"},
    )


@pytest.fixture
def db_session(settings: Settings) -> Session:
    """Create an in-memory database session for testing."""
    session_factory = init_db(settings.database.url)
    session = session_factory()
    yield session
    session.close()

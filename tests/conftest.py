"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from dmarc_msp.config import (
    DatabaseConfig,
    DNSProviderConfig,
    MSPConfig,
    OpenSearchConfig,
    Settings,
)
from dmarc_msp.db import init_db


@pytest.fixture
def settings() -> Settings:
    """Return test settings with an in-memory SQLite database."""
    return Settings(
        database=DatabaseConfig(url="sqlite:///:memory:"),
        opensearch=OpenSearchConfig(password="test_password"),
        msp=MSPConfig(
            domain="dmarc.test.example.com",
            rua_email="reports@dmarc.test.example.com",
        ),
        dns=DNSProviderConfig(provider="cloudflare", zone="test.example.com"),
    )


@pytest.fixture
def db_session(settings: Settings) -> Generator[Session]:
    """Create an in-memory database session for testing."""
    session_factory = init_db(settings.database.url)
    session = session_factory()
    yield session
    session.close()

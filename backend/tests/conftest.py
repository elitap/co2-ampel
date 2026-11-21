from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from co2ampel.config import Config, load_config

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 11, 21, 16, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)


def ts(i: int) -> datetime:
    """i-ter 15-Minuten-Schritt ab T0."""
    return T0 + i * STEP


@pytest.fixture(scope="session")
def cfg() -> Config:
    return load_config()

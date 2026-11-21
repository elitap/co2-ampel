"""Vergleichslogik Electricity Maps (ohne Netz)."""

from __future__ import annotations

import pytest

from co2ampel.emcompare import _em_hourly, _hourly_ours, compare


def test_hourly_matching_and_stats() -> None:
    ours = _hourly_ours({"points": [
        {"t": "2026-11-21T18:00:00Z", "consumption": 100, "quality": "measured"},
        {"t": "2026-11-21T18:15:00Z", "consumption": 120, "quality": "measured"},
        {"t": "2026-11-21T19:00:00Z", "consumption": 200, "quality": "stale"},
        {"t": "2026-11-21T20:00:00Z", "consumption": 300, "quality": "measured"},
        {"t": "2026-11-21T21:00:00Z", "consumption": None, "quality": "unknown"},
    ]})
    em = _em_hourly({"history": [
        {"datetime": "2026-11-21T18:00:00.000Z", "carbonIntensity": 100, "isEstimated": False},
        {"datetime": "2026-11-21T19:00:00.000Z", "carbonIntensity": 220, "isEstimated": False},
        {"datetime": "2026-11-21T20:00:00.000Z", "carbonIntensity": 280, "isEstimated": True},
        {"datetime": "2026-11-21T22:00:00.000Z", "carbonIntensity": 999},
    ]})
    c = compare(ours, em)
    assert c is not None
    assert c["n"] == 3 and c["n_em_estimated"] == 1
    assert c["mean_ours"] == pytest.approx((110 + 200 + 300) / 3)
    assert c["mean_diff"] == pytest.approx((10 - 20 + 20) / 3)


def test_too_few_hours() -> None:
    assert compare({}, {}) is None
    assert _em_hourly({"error": 401}) == {}

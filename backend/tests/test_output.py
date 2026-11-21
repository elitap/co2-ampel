"""Ausgabe: Schema, Ampel, Zusammenführung mit dem Vorstand, Plausibilität."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import jsonschema
import pytest

from co2ampel.config import Config, TrafficLight
from co2ampel.models import Quality, ZoneResult
from co2ampel.output import (
    PlausibilityError,
    Point,
    check_plausibility,
    iso,
    keep_better,
    latest_entry,
    merge_history,
    pick_latest,
    validate,
)

from .conftest import ts


@pytest.mark.parametrize(("value", "level"), [
    (None, "unknown"), (0, "green"), (149.9, "green"), (150, "yellow"), (300, "yellow"),
    (300.1, "red"), (1200, "red"),
])
def test_traffic_light(value: float | None, level: str) -> None:
    assert TrafficLight(150, 300).level(value) == level


def test_latest_entry_and_stale_by_age(cfg: Config) -> None:
    p = Point(ts(0), 123.4, 99.0, Quality.MEASURED)
    e = latest_entry(cfg, "AT", p, ts(4))
    assert e["level"] == "green" and e["quality"] == "measured" and e["name"] == "Österreich"
    assert latest_entry(cfg, "AT", p, ts(0) + timedelta(hours=3, minutes=45))["quality"] == "measured"
    e = latest_entry(cfg, "AT", p, ts(0) + timedelta(hours=4, minutes=15))
    assert e["quality"] == "stale"
    assert latest_entry(cfg, "DK", None, ts(0))["quality"] == "unknown"


def test_merge_history_keeps_better_quality() -> None:
    old = {ts(0): Point(ts(0), 100, 100, Quality.MEASURED), ts(1): Point(ts(1), 100, 100, Quality.STALE)}
    new = {
        ts(0): ZoneResult("A", ts(0), 200, 200, Quality.STALE),  # schlechter -> verworfen
        ts(1): ZoneResult("A", ts(1), 210, 210, Quality.MEASURED),  # besser -> übernommen
        ts(2): ZoneResult("A", ts(2), None, None, Quality.UNKNOWN),  # unbekannt -> nicht gespeichert
    }
    merged = merge_history(old, new, ts(2), 48)
    assert merged[ts(0)].consumption == 100
    assert merged[ts(1)].consumption == 210
    assert ts(2) not in merged
    # Abschneiden nach 48 h
    assert merge_history(old, {}, ts(0) + timedelta(hours=48), 48) == {ts(1): old[ts(1)]}


def test_pick_latest_prefers_measured() -> None:
    pts = {ts(0): Point(ts(0), 1, 1, Quality.MEASURED), ts(4): Point(ts(4), 2, 2, Quality.STALE)}
    p = pick_latest(pts)
    assert p is not None and p.t == ts(0)
    assert pick_latest({}) is None


def _entry(t: int, q: str, v: float | None = 100.0) -> dict[str, Any]:
    return {"zone": "AT", "timestamp": iso(ts(t)) if v is not None else None, "consumption": v, "quality": q}


def test_keep_better_never_worse() -> None:
    assert keep_better(_entry(1, "measured"), _entry(0, "measured"))["timestamp"] == iso(ts(1))
    assert keep_better(_entry(0, "measured"), _entry(1, "measured"))["timestamp"] == iso(ts(1))
    assert keep_better(_entry(1, "stale"), _entry(1, "measured"))["quality"] == "measured"
    assert keep_better(_entry(0, "unknown", None), _entry(0, "measured"))["consumption"] == 100.0
    assert keep_better(_entry(0, "measured"), None)["quality"] == "measured"


def test_plausibility(cfg: Config) -> None:
    ok = [{"zone": "AT", "consumption": 100.0, "production": 90.0}]
    check_plausibility(cfg, ok, ["DK"])
    with pytest.raises(PlausibilityError):
        check_plausibility(cfg, [{"zone": "AT", "consumption": -1.0, "production": 1.0}], [])
    with pytest.raises(PlausibilityError):
        check_plausibility(cfg, [{"zone": "AT", "consumption": 1600.0, "production": 1.0}], [])
    too_many = cfg.zone_codes[: int(len(cfg.zone_codes) * 0.31) + 1]
    with pytest.raises(PlausibilityError):
        check_plausibility(cfg, ok, too_many)


def _latest_doc(cfg: Config) -> dict[str, Any]:
    return {
        "schema_version": 1, "kind": "latest", "generated_at": iso(ts(0)),
        "attribution": [{"source": "x", "license": "CC BY 4.0", "url": "https://energy-charts.info"}],
        "unit": "gCO2eq/kWh", "thresholds": {"green_below": 150, "red_above": 300, "unit": "gCO2eq/kWh"},
        "zones": [latest_entry(cfg, "AT", Point(ts(0), 120.0, 80.0, Quality.MEASURED), ts(0))],
    }


def test_schema_accepts_valid_and_rejects_invalid(cfg: Config) -> None:
    doc = _latest_doc(cfg)
    validate(doc)
    bad = _latest_doc(cfg)
    bad["zones"][0]["consumption"] = 2000
    with pytest.raises(jsonschema.ValidationError):
        validate(bad)
    bad = _latest_doc(cfg)
    bad["zones"][0]["quality"] = "guessed"
    with pytest.raises(jsonschema.ValidationError):
        validate(bad)
    bad = _latest_doc(cfg)
    del bad["attribution"]
    with pytest.raises(jsonschema.ValidationError):
        validate(bad)

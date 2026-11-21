"""Parser mit gespeicherten echten Energy-Charts-Antworten (abgerufen am 2026-11-21)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from co2ampel.config import Config
from co2ampel.sources.energy_charts import ParseError, parse_cbpf, parse_public_power

from .conftest import FIXTURES

EC = FIXTURES / "energy_charts"


def test_public_power_at_15min(cfg: Config) -> None:
    raw = (EC / "public_power_at_2026-11-21.json").read_bytes()
    p = parse_public_power(raw, cfg.mapping_ec)
    assert p.unmapped == []
    # Laststatistiken sind keine Erzeugung
    assert "load" not in p.generation and "residual_load" not in p.generation
    # Wasser: Laufwasser + Speicher werden zu "hydro" summiert
    t = datetime(2026, 11, 20, 23, 0, tzinfo=UTC)  # 00:00 Europe/Vienna
    assert p.generation["hydro"][t] == pytest.approx(1472.0 + 39.2)
    assert p.generation["gas"][t] == pytest.approx(1508.8)
    # Pumpspeicherladen (in der Quelle negativ) wird als positiver Verbrauch geführt
    assert p.charge[t] == pytest.approx(439.2)
    assert p.generation["storage"][t] == pytest.approx(0.0)
    assert len(p.generation["gas"]) == 77
    assert all(v >= 0 for s in p.generation.values() for v in s.values())


def test_public_power_hourly_is_expanded_to_quarter_hours(cfg: Config) -> None:
    raw = (EC / "public_power_ch_2026-11-21.json").read_bytes()
    doc = json.loads(raw)
    assert doc["resolution"] == "PT1H"
    p = parse_public_power(raw, cfg.mapping_ec)
    nuc = p.generation["nuclear"]
    first = min(nuc)
    assert [first + timedelta(minutes=15 * i) in nuc for i in range(4)] == [True] * 4
    assert nuc[first] == nuc[first + timedelta(minutes=45)]
    assert len(nuc) == 4 * sum(1 for r in doc["data"] if r["values"].get("nuclear") is not None)


def test_public_power_with_null_gaps(cfg: Config) -> None:
    raw = (EC / "public_power_it_2026-11-21.json").read_bytes()
    doc = json.loads(raw)
    p = parse_public_power(raw, cfg.mapping_ec)
    # Nullwerte erzeugen keine Einträge
    n_gas = sum(1 for r in doc["data"] if r["values"].get("fossil_gas") is not None)
    assert len(p.generation["gas"]) == n_gas
    assert "oil" not in p.generation or len(p.generation["oil"]) < len(doc["data"])


def test_public_power_de_maps_all_series(cfg: Config) -> None:
    p = parse_public_power((EC / "public_power_de_2026-11-21.json").read_bytes(), cfg.mapping_ec)
    assert p.unmapped == []
    assert {"lignite", "hard_coal", "coal_derived_gas", "gas", "wind_offshore", "solar"} <= set(p.generation)


def test_cbpf_units_and_sign() -> None:
    raw = (EC / "cbpf_at_2026-11-21.json").read_bytes()
    f = parse_cbpf(raw)
    assert "sum" not in f
    t = datetime(2026, 11, 20, 23, 0, tzinfo=UTC)
    assert f["czech_republic"][t] == pytest.approx(1480.0)  # 1.48 GW Import -> 1480 MW
    assert f["hungary"][t] == pytest.approx(-457.0)  # Export
    assert set(f) == {"czech_republic", "germany", "hungary", "italy", "slovenia", "switzerland"}


def test_cbpf_hourly(cfg: Config) -> None:
    f = parse_cbpf((EC / "cbpf_ba_7d.json").read_bytes())
    assert set(f) == {"croatia", "montenegro", "serbia"}
    s = f["serbia"]
    k = min(s)
    assert s[k] == s[k + timedelta(minutes=45)]
    assert all(alias in cfg.alias_map() for alias in f)


def test_unknown_series_are_ignored(cfg: Config) -> None:
    doc = json.loads((EC / "public_power_at_2026-11-21.json").read_bytes())
    doc["series"].append({"id": "fusion", "name": "Fusion"})
    doc["data"][0]["values"]["fusion"] = 5.0
    doc["data"][0]["values"]["solar"] = "kaputt"
    doc["new_top_level_field"] = {"x": 1}
    p = parse_public_power(doc, cfg.mapping_ec)
    assert p.unmapped == ["fusion"]
    assert "fusion" not in p.generation


@pytest.mark.parametrize("payload", [
    b"not json",
    b"[]",
    b'{"schema_version": "1.0", "data": [], "series": []}',
    b'{"schema_version": "2.0"}',
])
def test_malformed_payload_raises(payload: bytes, cfg: Config) -> None:
    with pytest.raises(ParseError):
        parse_public_power(payload, cfg.mapping_ec)


def test_timestamp_without_timezone_is_skipped(cfg: Config) -> None:
    doc = {"schema_version": "2.0", "unit": "MW", "interval_minutes": 15,
           "series": [{"id": "solar"}],
           "data": [{"timestamp": "2026-11-21T12:00:00", "values": {"solar": 1.0}},
                    {"timestamp": "2026-11-21T12:15:00+01:00", "values": {"solar": 2.0}}]}
    p = parse_public_power(doc, cfg.mapping_ec)
    assert list(p.generation["solar"].values()) == [2.0]


def test_trailing_zero_placeholders_are_dropped() -> None:
    from co2ampel.sources.energy_charts import strip_trailing_zeros

    from .conftest import ts

    s = {ts(0): 100.0, ts(1): 0.0, ts(2): 50.0, ts(3): 0.0, ts(4): 0.0}
    assert strip_trailing_zeros(s) == {ts(0): 100.0, ts(1): 0.0, ts(2): 50.0}  # Null in der Mitte bleibt
    idle = {ts(0): 0.0, ts(1): 0.0}
    assert strip_trailing_zeros(idle) == idle  # Leitung außer Betrieb

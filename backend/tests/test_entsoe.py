"""ENTSO-E-Parser mit nach der offiziellen Doku nachgebauten Fixtures; Live-Test nur mit Token."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from co2ampel.http import HttpClient
from co2ampel.sources.entsoe import (
    EntsoeClient,
    EntsoeParseError,
    is_acknowledgement,
    parse_flows,
    parse_generation,
)

from .conftest import FIXTURES, T0, ts

EN = FIXTURES / "entsoe"


def test_a75_generation_and_consumption() -> None:
    doc = parse_generation((EN / "a75_at.xml").read_bytes())
    assert doc.generation["B04"] == {ts(0): 1500, ts(1): 1510, ts(2): 1520, ts(3): 1530}
    # PT60M wird auf vier Viertelstunden aufgeteilt
    assert doc.generation["B11"] == {ts(i): 2400 for i in range(4)}
    # Pumpspeicher: Erzeugung (inBiddingZone) und Verbrauch (outBiddingZone) getrennt
    assert doc.generation["B10"][ts(0)] == 400
    assert doc.consumption["B10"] == {ts(0): 300, ts(1): 200, ts(2): 100, ts(3): 0}


def test_a75_curve_type_a03_forward_fills() -> None:
    doc = parse_generation((EN / "a75_at.xml").read_bytes())
    assert doc.generation["B16"] == {ts(0): 20, ts(1): 20, ts(2): 0, ts(3): 0}


def test_a69_wind_solar_forecast() -> None:
    doc = parse_generation((EN / "a69_at.xml").read_bytes())
    assert doc.generation["B19"][ts(4)] == 800
    assert doc.generation["B16"][ts(7)] == 0


def test_a71_total_forecast_without_psr() -> None:
    doc = parse_generation((EN / "a71_at.xml").read_bytes())
    assert doc.generation[None] == {ts(4 + i): 6000 for i in range(4)}


def test_a11_physical_flow() -> None:
    flows = parse_flows((EN / "a11_de_at.xml").read_bytes())
    s = flows[("10Y1001A1001A83F", "10YAT-APG------L")]
    assert s[ts(0)] == 1200 and s[ts(3)] == 1200 and s[ts(4)] == 900
    assert len(s) == 8


def test_acknowledgement_means_no_data() -> None:
    raw = (EN / "acknowledgement_no_data.xml").read_bytes()
    reason = is_acknowledgement(raw)
    assert reason is not None and "No matching data" in reason
    assert parse_generation(raw).generation == {}
    assert parse_flows(raw) == {}


def test_wrong_document_type_raises() -> None:
    with pytest.raises(EntsoeParseError):
        parse_flows((EN / "a75_at.xml").read_bytes())
    with pytest.raises(EntsoeParseError):
        parse_generation((EN / "a11_de_at.xml").read_bytes())


@pytest.mark.parametrize("xml", [
    b"<not-closed>",
    # Entity-Expansion ("billion laughs") muss abgelehnt werden
    b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
    b"<GL_MarketDocument>&b;</GL_MarketDocument>",
    # externe Entität (XXE)
    b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><GL_MarketDocument>&e;'
    b"</GL_MarketDocument>",
])
def test_unsafe_or_broken_xml_rejected(xml: bytes) -> None:
    with pytest.raises(EntsoeParseError):
        parse_generation(xml)


def test_mapping_covers_all_psr_types(cfg: object) -> None:
    from co2ampel.config import Config

    assert isinstance(cfg, Config)
    expected = {f"B{i:02d}" for i in range(1, 21)} | {"B25"}
    assert expected <= set(cfg.mapping_entsoe)


@pytest.mark.entsoe_live
@pytest.mark.skipif(not os.environ.get("ENTSOE_API_TOKEN"), reason="ENTSOE_API_TOKEN nicht gesetzt")
def test_live_actual_generation_at() -> None:  # pragma: no cover - nur mit Token
    client = EntsoeClient(os.environ["ENTSOE_API_TOKEN"], HttpClient(max_attempts=2),
                          "https://web-api.tp.entsoe.eu/api")
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    body = client.actual_generation("10YAT-APG------L", end - timedelta(hours=2), end)
    assert body is not None
    doc = parse_generation(body)
    assert doc.generation, "A75 für AT sollte Daten liefern"


def test_t0_is_utc() -> None:
    assert T0.tzinfo is UTC

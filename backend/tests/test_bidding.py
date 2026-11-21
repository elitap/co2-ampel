"""Gebotszonen: Konfiguration, Aufteilung, Flusszuordnung, Länder-Aggregat, Ende-zu-Ende mit ENTSO-E."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from co2ampel.bidding import aggregate_countries, apply_split, split_edges
from co2ampel.config import DEFAULT_CONFIG_DIR, Config, load_config
from co2ampel.gapfill import SourceData
from co2ampel.http import Budget, HttpResult
from co2ampel.models import Quality, ZoneResult
from co2ampel.output import validate
from co2ampel.pipeline import PreviousState, run

from .conftest import ts
from .test_pipeline import EC_FILES, ZONES_YAML

NOW = datetime(2026, 11, 21, 19, 0, tzinfo=UTC)


def test_real_bidding_config(cfg: Config) -> None:
    assert {s.country for s in cfg.bidding} == {"NO", "SE", "DK", "IT"}
    eics = [z.entsoe for z in cfg.sub_zones]
    assert len(eics) == len(set(eics))
    assert cfg.zone("NO-NO2").parent == "NO"
    assert cfg.zone("DE").border_eic == "10Y1001A1001A82H"  # Gebotszone DE-LU an Grenzen


def test_split_edges_resolve_unsplit_neighbours(cfg: Config) -> None:
    se = {s.country: s for s in cfg.bidding if s.country == "SE"}
    edges = split_edges(cfg, se)
    assert ("NO", "SE-SE3") in edges  # NO nicht aufgeteilt -> Land
    assert ("SE-SE1", "SE-SE2") in edges
    assert ("DE", "SE-SE4") in edges


def test_apply_split_remaps_single_link_flows(cfg: Config) -> None:
    s1, s2, s3, s4, s5 = ({ts(0): float(v)} for v in (1, 2, 3, 4, 5))
    data = SourceData(
        ec_gen={"DK": {"wind_onshore": {ts(0): 1.0}}, "DE": {"gas": {ts(0): 1.0}}},
        ec_flows={"DE": {"DK": s1, "AT": s5}, "DK": {"DE": s2, "NL": s3, "GB": s4}},
    )
    split = {s.country: s for s in cfg.bidding if s.country == "DK"}
    zones = apply_split(cfg, data, split)
    assert "DK" not in zones and {"DK-DK1", "DK-DK2"} <= set(zones)
    assert "DK" not in data.ec_gen
    assert data.ec_flows["DK-DK1"]["NL"] is s3  # nur DK1 grenzt an NL
    assert data.ec_flows["DK-DK1"]["GB"] is s4  # Viking Link
    assert "DK-DK1" not in data.ec_flows["DE"] and "DK" not in data.ec_flows["DE"]  # DE grenzt an DK1 und DK2
    assert data.ec_flows["DE"]["AT"] is s5  # unbeteiligte Grenzen bleiben


def test_aggregate_country_is_consumption_weighted(cfg: Config) -> None:
    split = {s.country: s for s in cfg.bidding if s.country == "DK"}
    results = {ts(0): {
        # DK1: Verbrauch 100 MW zu 100 g, DK2: 300 MW zu 300 g -> 250 g
        "DK-DK1": ZoneResult("DK-DK1", ts(0), 100.0, 50.0, Quality.MEASURED, generation_mw=100,
                             own_generation_mw=100, emissions=100 * 50.0),
        "DK-DK2": ZoneResult("DK-DK2", ts(0), 300.0, 350.0, Quality.MEASURED, generation_mw=300,
                             own_generation_mw=300, emissions=300 * 350.0),
    }}
    aggregate_countries(results, split)
    dk = results[ts(0)]["DK"]
    assert dk.consumption == pytest.approx(250.0)
    assert dk.production == pytest.approx((5000 + 105000) / 400)
    assert dk.quality is Quality.MEASURED
    del results[ts(0)]["DK-DK2"]
    aggregate_countries(results, split)
    assert results[ts(0)]["DK"].quality is Quality.ESTIMATED


# --------------------------------------------------------------------------- Ende-zu-Ende

NORD, CSUD = "10Y1001A1001A73I", "10Y1001A1001A71M"
BIDDING_YAML = f"""
countries:
  IT:
    zones:
      - {{code: IT-NORD, name_de: Italien Nord, name_en: Italy North, entsoe: {NORD}}}
      - {{code: IT-CSUD, name_de: Italien Mitte-Süd, name_en: Italy Centre-South, entsoe: {CSUD}}}
    internal:
      - [IT-NORD, IT-CSUD]
    external:
      - [IT-NORD, AT]
      - [IT-NORD, CH]
      - [IT-NORD, FR]
"""


def gl_doc(values: Mapping[str, float], start: datetime, n: int) -> bytes:
    series = "".join(
        f"<TimeSeries><inBiddingZone_Domain.mRID>x</inBiddingZone_Domain.mRID>"
        f"<quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name><curveType>A01</curveType>"
        f"<MktPSRType><psrType>{psr}</psrType></MktPSRType><Period><timeInterval>"
        f"<start>{start:%Y-%m-%dT%H:%MZ}</start><end>{start + n * timedelta(minutes=15):%Y-%m-%dT%H:%MZ}</end>"
        f"</timeInterval><resolution>PT15M</resolution>"
        + "".join(f"<Point><position>{i + 1}</position><quantity>{v}</quantity></Point>" for i in range(n))
        + "</Period></TimeSeries>"
        for psr, v in values.items()
    )
    return f'<GL_MarketDocument xmlns="urn:x">{series}</GL_MarketDocument>'.encode()


def pub_doc(src: str, dst: str, value: float, start: datetime, n: int) -> bytes:
    pts = "".join(f"<Point><position>{i + 1}</position><quantity>{value}</quantity></Point>" for i in range(n))
    return (f'<Publication_MarketDocument xmlns="urn:y"><TimeSeries><in_Domain.mRID>{dst}</in_Domain.mRID>'
            f"<out_Domain.mRID>{src}</out_Domain.mRID><curveType>A01</curveType><Period><timeInterval>"
            f"<start>{start:%Y-%m-%dT%H:%MZ}</start><end>{start + n * timedelta(minutes=15):%Y-%m-%dT%H:%MZ}</end>"
            f"</timeInterval><resolution>PT15M</resolution>{pts}</Period></TimeSeries>"
            f"</Publication_MarketDocument>").encode()


ACK = (Path(__file__).parent / "fixtures" / "entsoe" / "acknowledgement_no_data.xml").read_bytes()


class FakeHttp:
    def __init__(self) -> None:
        self.request_count = 0
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: Mapping[str, str] | None = None, budget: Budget | None = None,
            log_url: str | None = None) -> HttpResult | None:
        self.request_count += 1
        p = dict(params or {})
        self.calls.append((url, p))
        if "energy-charts" in url:
            f = EC_FILES.get((url.rsplit("/", 1)[-1], p.get("country", "")))
            return HttpResult(200, f.read_bytes()) if f else HttpResult(404, b"")
        start, n = NOW - timedelta(hours=8), 30  # bis 18:15 -> aktuell genug
        if p.get("documentType") == "A75" and p.get("in_Domain") == NORD:
            return HttpResult(200, gl_doc({"B04": 8000, "B11": 4000}, start, n))  # Gas + Wasser
        if p.get("documentType") == "A75" and p.get("in_Domain") == CSUD:
            return HttpResult(200, gl_doc({"B16": 1000, "B05": 1000}, start, n))  # Solar + Steinkohle
        if p.get("documentType") == "A11" and {p.get("out_Domain"), p.get("in_Domain")} == {NORD, CSUD}:
            v = 500.0 if p.get("out_Domain") == NORD else 0.0  # 500 MW von NORD nach CSUD
            return HttpResult(200, pub_doc(p["out_Domain"], p["in_Domain"], v, start, n))
        return HttpResult(200, ACK)


def make_config(tmp_path: Path) -> Config:
    d = tmp_path / "config"
    d.mkdir()
    for f in ("emission_factors.yaml", "traffic_light.yaml", "settings.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / f, d / f)
    (d / "zones.yaml").write_text(ZONES_YAML % "", encoding="utf-8")
    (d / "bidding_zones.yaml").write_text(BIDDING_YAML, encoding="utf-8")
    return load_config(d)


def test_end_to_end_with_bidding_zones(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    fake = FakeHttp()
    out = tmp_path / "public"
    res = run(cfg, out, PreviousState(), now=NOW, entsoe_token="tok", http_factory=lambda: fake)
    entries = {e["zone"]: e for e in res.latest["zones"]}
    assert {"IT", "IT-NORD", "IT-CSUD"} <= set(entries)
    nord, csud, it = entries["IT-NORD"], entries["IT-CSUD"], entries["IT"]
    # NORD: Gas 8000 (490) + Wasser 4000 (24) plus Importe aus AT/CH/FR -> Produktion exakt
    assert nord["production"] == pytest.approx((8000 * 490 + 4000 * 24) / 12000, abs=0.1)
    # CSUD: Solar 1000 (48) + Kohle 1000 (820) -> 434; Import aus NORD senkt den Verbrauch
    assert csud["production"] == pytest.approx(434.0, abs=0.1)
    assert csud["consumption"] < csud["production"]
    assert min(nord["consumption"], csud["consumption"]) <= it["consumption"] <= max(
        nord["consumption"], csud["consumption"])
    zones = json.loads((out / "zones.json").read_text(encoding="utf-8"))
    assert {"zone": "IT-NORD", "name": "Italien Nord", "name_en": "Italy North", "parent": "IT"} in zones["zones"]
    for z in ("IT", "IT-NORD", "IT-CSUD"):
        validate(json.loads((out / "history" / f"{z}.json").read_text(encoding="utf-8")))
    # IT wird nicht zusätzlich per A75 als Land abgefragt
    a75 = [p.get("in_Domain") for _, p in fake.calls if p.get("documentType") == "A75"]
    assert "10YIT-GRTN-----B" not in a75
    assert not res.missing


def test_without_token_no_bidding_zones(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    res = run(cfg, tmp_path / "public", PreviousState(), now=NOW, http_factory=FakeHttp)
    assert "IT-NORD" not in {e["zone"] for e in res.latest["zones"]}

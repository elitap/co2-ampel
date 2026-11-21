"""APG-Parser (synthetische Antworten im echten Format; echte APG-Daten werden mangels Lizenz nicht
im Repo gespeichert) und Einbindung in den Lauf."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from co2ampel.config import DEFAULT_CONFIG_DIR, Config, load_config
from co2ampel.http import Budget, HttpResult
from co2ampel.pipeline import PreviousState, run
from co2ampel.sources.apg import ApgParseError, day_start_utc, parse_agpt

from .test_pipeline import EC_FILES, ZONES_YAML


def agpt(cols: list[str], rows: list[list[float | None]], missing: tuple[int, int] | None = None) -> dict[str, Any]:
    vrows = []
    for i, r in enumerate(rows):
        cells = [{"V": v, "E": False, "M": missing == (i, j)} for j, v in enumerate(r)]
        vrows.append({"DF": "x", "TF": "x", "V": cells})
    return {"ResponseData": {"Description": "Article 16.1.b", "ValueColumns": [{"InternalName": c} for c in cols],
                             "ValueRows": vrows}}


def test_parse_maps_psr_types_and_skips_charging(cfg: Config) -> None:
    doc = agpt(["B19", "B04", "B10", "B11", "B12"],
               [[100, 1500, -400, 1400, 40], [110, 1490, 300, 1410, 50], [None, None, None, None, None]],
               missing=(1, 0))
    s = parse_agpt(json.dumps(doc).encode(), date(2026, 11, 21), cfg.mapping_entsoe)
    t0 = datetime(2026, 11, 20, 23, 0, tzinfo=UTC)  # 00:00 Wien (Winterzeit)
    t1 = t0 + timedelta(minutes=15)
    assert s["wind_onshore"] == {t0: 100}  # Zeile 1: Wert als fehlend markiert (M)
    assert s["gas"] == {t0: 1500, t1: 1490}
    assert s["hydro"] == {t0: 1440, t1: 1460}  # Laufwasser + Speicher
    assert s["storage"] == {t1: 300}  # negativ = Laden -> keine Erzeugung
    assert t0 + timedelta(minutes=30) not in s["gas"]  # leere Zeile


def test_day_start_handles_dst() -> None:
    assert day_start_utc(date(2026, 7, 1)) == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)
    assert day_start_utc(date(2026, 10, 25)) == datetime(2026, 10, 24, 22, 0, tzinfo=UTC)
    # Tag der Umstellung hat 100 Zeilen; Zeile 12 (nach doppelter Stunde) = 02:00 MEZ = 01:00 UTC
    doc = agpt(["B04"], [[float(i)] for i in range(100)])
    s = parse_agpt(doc, date(2026, 10, 25), {"B04": "gas"})
    assert len(s["gas"]) == 100
    assert s["gas"][datetime(2026, 10, 25, 1, 0, tzinfo=UTC)] == 12.0


@pytest.mark.parametrize("payload", [b"{}", b"nope", b'{"ResponseData": {"ValueColumns": []}}'])
def test_broken_payload(payload: bytes) -> None:
    with pytest.raises(ApgParseError):
        parse_agpt(payload, date(2026, 11, 21), {})


NOW = datetime(2026, 11, 21, 19, 0, tzinfo=UTC)


class FakeHttp:
    def __init__(self) -> None:
        self.request_count = 0
        self.urls: list[str] = []

    def get(self, url: str, params: Mapping[str, str] | None = None, budget: Budget | None = None,
            log_url: str | None = None) -> HttpResult | None:
        self.request_count += 1
        self.urls.append(url)
        p = dict(params or {})
        if "energy-charts" in url:
            if p.get("country") == "at" and url.endswith("public_power"):
                return HttpResult(404, b"")  # AT nur über APG
            f = EC_FILES.get((url.rsplit("/", 1)[-1], p.get("country", "")))
            return HttpResult(200, f.read_bytes()) if f else HttpResult(404, b"")
        if "apg" in url and "/2026-11-21T000000/" in url:
            # 00:00–19:45 Ortszeit = 23:00–18:45 UTC: Gas 1000, Wasser 3000
            return HttpResult(200, json.dumps(agpt(["B04", "B11"], [[1000.0, 3000.0]] * 80)).encode())
        return HttpResult(404, b"")


def test_run_with_apg_enabled(tmp_path: Path) -> None:
    d = tmp_path / "config"
    d.mkdir()
    for f in ("emission_factors.yaml", "traffic_light.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / f, d / f)
    settings = (DEFAULT_CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8")
    (d / "settings.yaml").write_text(settings.replace("  enabled: false", "  enabled: true"), encoding="utf-8")
    (d / "zones.yaml").write_text(ZONES_YAML % "", encoding="utf-8")
    cfg = load_config(d)
    assert cfg.apg_enabled
    fake = FakeHttp()
    res = run(cfg, tmp_path / "public", PreviousState(), now=NOW, http_factory=lambda: fake)
    at = next(e for e in res.latest["zones"] if e["zone"] == "AT")
    assert at["timestamp"] == "2026-11-21T18:45:00Z"  # APG-Rand statt Energy-Charts (18:00)
    assert at["production"] == pytest.approx((1000 * 490 + 3000 * 24) / 4000, abs=0.1)
    assert any("APG" in a["source"] for a in res.latest["attribution"])
    assert sum("apg" in u for u in fake.urls) == 1  # ein Tag im Fenster -> eine Anfrage


def test_apg_disabled_by_default(cfg: Config) -> None:
    assert not cfg.apg_enabled

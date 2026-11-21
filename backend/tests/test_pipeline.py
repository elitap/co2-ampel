"""Ende-zu-Ende-Läufe ohne Netz (Fake-HTTP liefert gespeicherte Antworten)."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from co2ampel.config import DEFAULT_CONFIG_DIR, Config, load_config
from co2ampel.http import Budget, HttpResult
from co2ampel.output import PlausibilityError, validate
from co2ampel.pipeline import PreviousState, load_previous_from_dir, run

from .conftest import FIXTURES

NOW = datetime(2026, 11, 21, 19, 0, tzinfo=UTC)
EC = FIXTURES / "energy_charts"
EN = FIXTURES / "entsoe"
SECRET = "test-token-should-never-be-logged"

EC_FILES = {
    ("public_power", "at"): EC / "public_power_at_2026-11-21.json",
    ("public_power", "ch"): EC / "public_power_ch_2026-11-21.json",
    ("public_power", "de"): EC / "public_power_de_2026-11-21.json",
    ("public_power", "it"): EC / "public_power_it_2026-11-21.json",
    ("cbpf", "at"): EC / "cbpf_at_2026-11-21.json",
    ("cbpf", "ch"): EC / "cbpf_ch_7d.json",
}

ZONES_YAML = """
zones:
  - {code: AT, name_de: Österreich, name_en: Austria, energy_charts: at, alias: austria, entsoe: 10YAT-APG------L}
  - {code: CH, name_de: Schweiz, name_en: Switzerland, energy_charts: ch, alias: switzerland, entsoe: 10YCH-SWISSGRIDZ}
  - {code: DE, name_de: Deutschland, name_en: Germany, energy_charts: de, alias: germany, entsoe: 10Y1001A1001A83F}
  - {code: IT, name_de: Italien, name_en: Italy, energy_charts: it, alias: italy, entsoe: 10YIT-GRTN-----B}
%s
external:
  czech_republic: CZ
  hungary: HU
  slovenia: SI
  france: FR
"""


class FakeHttp:
    def __init__(self, ec_files: Mapping[tuple[str, str], Path], status: int | None = None) -> None:
        self.ec_files = ec_files
        self.status = status
        self.request_count = 0
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: Mapping[str, str] | None = None, budget: Budget | None = None,
            log_url: str | None = None) -> HttpResult | None:
        self.request_count += 1
        p = dict(params or {})
        self.calls.append((url, p))
        if self.status is not None:
            return HttpResult(self.status, b"")
        if "energy-charts" in url:
            endpoint = url.rsplit("/", 1)[-1]
            f = self.ec_files.get((endpoint, p.get("country", "")))
            return HttpResult(200, f.read_bytes()) if f else HttpResult(404, b"no content available")
        if "entsoe" in url:
            doc = p.get("documentType")
            name = {"A75": "a75_at.xml", "A69": "a69_at.xml", "A71": "a71_at.xml"}.get(str(doc))
            if name and p.get("in_Domain") == "10YAT-APG------L":
                return HttpResult(200, (EN / name).read_bytes())
            return HttpResult(200, (EN / "acknowledgement_no_data.xml").read_bytes())
        return HttpResult(404, b"")


def make_config(tmp_path: Path, extra_zones: str = "") -> Config:
    d = tmp_path / "config"
    d.mkdir()
    for f in ("emission_factors.yaml", "traffic_light.yaml", "settings.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / f, d / f)
    (d / "zones.yaml").write_text(ZONES_YAML % extra_zones, encoding="utf-8")
    return load_config(d)


def test_full_run_writes_valid_files(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    out = tmp_path / "public"
    fake = FakeHttp(EC_FILES)
    res = run(cfg, out, PreviousState(), now=NOW, http_factory=lambda: fake)

    assert res.missing == []
    assert not res.entsoe_used
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    validate(latest)
    assert latest["thresholds"] == {"green_below": 150, "red_above": 300, "unit": "gCO2eq/kWh"}
    assert [a["license"] for a in latest["attribution"]] == ["CC BY 4.0"]
    at = next(z for z in latest["zones"] if z["zone"] == "AT")
    assert at["quality"] in ("measured", "estimated", "stale")
    assert 50 < at["consumption"] < 600
    assert at["level"] in ("green", "yellow", "red")
    assert at["timestamp"] == "2026-11-21T18:00:00Z"  # letzter Messwert AT (19:00 Ortszeit)
    for z in ("AT", "CH", "DE", "IT"):
        hist = json.loads((out / "history" / f"{z}.json").read_text(encoding="utf-8"))
        validate(hist)
        assert hist["points"], z
    zones = json.loads((out / "zones.json").read_text(encoding="utf-8"))
    assert [z["zone"] for z in zones["zones"]] == ["AT", "CH", "DE", "IT"]
    validate(json.loads((out / "state" / "cache.json").read_text(encoding="utf-8")))
    # jede Quelle höchstens einmal pro Datentyp und Land
    keys = [(u.rsplit("/", 1)[-1], p["country"]) for u, p in fake.calls]
    assert len(keys) == len(set(keys)) == 8


def test_outage_never_makes_latest_worse(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    out1, out2 = tmp_path / "run1", tmp_path / "run2"
    run(cfg, out1, PreviousState(), now=NOW, http_factory=lambda: FakeHttp(EC_FILES))
    prev = load_previous_from_dir(out1, cfg.zone_codes)
    # Totalausfall: alle Anfragen liefern 503
    run(cfg, out2, prev, now=NOW.replace(minute=15), http_factory=lambda: FakeHttp(EC_FILES, status=503))
    a = json.loads((out1 / "latest.json").read_text(encoding="utf-8"))["zones"]
    b = json.loads((out2 / "latest.json").read_text(encoding="utf-8"))["zones"]
    for e1, e2 in zip(a, b, strict=True):
        assert e2["timestamp"] >= e1["timestamp"]
        assert e2["consumption"] is not None


def test_implausible_result_keeps_old_files(tmp_path: Path) -> None:
    extra = "\n".join(
        f"  - {{code: Z{i}, name_de: Leer{i}, name_en: Empty{i}, energy_charts: z{i}, alias: empty{i}, "
        f"entsoe: 10YXX-{i}}}" for i in range(3))
    cfg = make_config(tmp_path, extra)
    out = tmp_path / "public"
    out.mkdir()
    (out / "latest.json").write_text('{"old": true}', encoding="utf-8")
    with pytest.raises(PlausibilityError):
        run(cfg, out, PreviousState(), now=NOW, http_factory=lambda: FakeHttp(EC_FILES))
    assert json.loads((out / "latest.json").read_text(encoding="utf-8")) == {"old": True}
    assert not (out / "history").exists()


def test_entsoe_fills_gap_and_token_is_not_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    cfg = make_config(tmp_path)
    files = {k: v for k, v in EC_FILES.items() if k != ("public_power", "at")}  # AT fehlt bei Energy-Charts
    fake = FakeHttp(files)
    res = run(cfg, tmp_path / "public", PreviousState(), now=NOW, entsoe_token=SECRET,
              http_factory=lambda: fake)
    assert res.entsoe_used
    latest = res.latest
    assert any("ENTSO-E" in a["source"] for a in latest["attribution"])
    at = next(z for z in latest["zones"] if z["zone"] == "AT")
    assert at["consumption"] is not None
    assert at["timestamp"] == "2026-11-21T16:45:00Z"  # letzter A75-Ist-Wert
    assert at["quality"] in ("measured", "estimated")
    doc_types = {p["documentType"] for u, p in fake.calls if "entsoe" in u and p.get("in_Domain") == "10YAT-APG------L"}
    assert doc_types == {"A75"}  # Ist-Wert aktuell genug -> keine Prognosen abgefragt
    assert SECRET not in caplog.text
    entsoe_calls = [p for u, p in fake.calls if "entsoe" in u]
    assert entsoe_calls and all(p["securityToken"] == SECRET for p in entsoe_calls)
    # Pro Zone und Dokumenttyp höchstens eine Anfrage
    keys = [(p["documentType"], p.get("in_Domain"), p.get("out_Domain")) for p in entsoe_calls]
    assert len(keys) == len(set(keys))


def test_entsoe_forecast_when_actuals_are_old(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    files = {k: v for k, v in EC_FILES.items() if k != ("public_power", "at")}
    fake = FakeHttp(files)
    later = NOW.replace(hour=20)  # A75 endet 16:45 -> älter als 3 h -> A69/A71 werden abgefragt
    res = run(cfg, tmp_path / "public", PreviousState(), now=later, entsoe_token=SECRET,
              http_factory=lambda: fake)
    at = next(z for z in res.latest["zones"] if z["zone"] == "AT")
    assert at["timestamp"] == "2026-11-21T17:45:00Z"  # letzter Schritt aus den A69/A71-Prognosen
    assert at["quality"] in ("forecast", "estimated", "stale")
    doc_types = [p["documentType"] for u, p in fake.calls if "entsoe" in u and p.get("in_Domain") == "10YAT-APG------L"]
    assert sorted(doc_types) == ["A69", "A71", "A75"]


def test_real_config_is_consistent() -> None:
    cfg = load_config()
    assert "AT" in cfg.zone_codes
    assert len(cfg.zone_codes) >= 30

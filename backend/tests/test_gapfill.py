"""Lückenregeln: Primär -> Sekundär -> Prognose -> letzter Wert (<= 3 h) -> unbekannt."""

from __future__ import annotations

from datetime import timedelta

from co2ampel.gapfill import Assembler, SourceData
from co2ampel.models import Quality, Series

from .conftest import ts


def series(start: int, values: list[float]) -> Series:
    return {ts(start + i): v for i, v in enumerate(values)}


def make(data: SourceData, zones: list[str] | None = None) -> Assembler:
    return Assembler(data, zones or ["A"], timedelta(hours=3), min_coverage=0.5, significant_share=0.05)


def test_primary_actual_is_measured() -> None:
    data = SourceData(ec_gen={"A": {"gas": series(0, [100, 110]), "wind": series(0, [50, 60])}},
                      en_gen={"A": {"gas": series(0, [999, 999])}})
    zs = make(data).zone_step("A", ts(1))
    assert zs is not None
    assert zs.generation == {"gas": 110, "wind": 60}  # Energy-Charts hat Vorrang
    assert zs.quality is Quality.MEASURED


def test_secondary_actual_fills_gap() -> None:
    data = SourceData(ec_gen={"A": {"gas": series(0, [100]), "wind": series(0, [50])}},
                      en_gen={"A": {"gas": series(0, [100, 120]), "wind": series(0, [50, 70])}})
    zs = make(data).zone_step("A", ts(1))
    assert zs is not None
    assert zs.generation == {"gas": 120, "wind": 70}
    assert zs.quality is Quality.MEASURED


def test_forecast_before_stale() -> None:
    data = SourceData(ec_gen={"A": {"gas": series(0, [100]), "wind_onshore": series(0, [50])}},
                      en_forecast_ws={"A": {"wind_onshore": series(1, [80])}})
    zs = make(data).zone_step("A", ts(1))
    assert zs is not None
    assert zs.generation["wind_onshore"] == 80  # Prognose
    assert zs.generation["gas"] == 100  # letzter bekannter Wert
    # Wind (Prognose) und Gas (stale) sind beide wesentlich -> schlechteres Flag
    assert zs.quality is Quality.STALE


def test_total_forecast_distributed_on_last_mix() -> None:
    data = SourceData(ec_gen={"A": {"gas": series(0, [300]), "coal": series(0, [100]),
                              "wind_onshore": series(0, [0])}},
                      en_forecast_ws={"A": {"wind_onshore": series(1, [200])}},
                      en_forecast_total={"A": series(1, [1000])})
    zs = make(data).zone_step("A", ts(1))
    assert zs is not None
    # Rest 1000 - 200 (Wind) = 800 im Verhältnis Gas:Kohle = 3:1
    assert zs.generation["wind_onshore"] == 200
    assert zs.generation["gas"] == 600
    assert zs.generation["coal"] == 200
    assert zs.quality is Quality.FORECAST


def test_stale_within_three_hours() -> None:
    data = SourceData(ec_gen={"A": {"gas": series(0, [100]), "wind": series(0, [50])}})
    asm = make(data)
    zs = asm.zone_step("A", ts(12))  # genau 3 h später
    assert zs is not None
    assert zs.quality is Quality.STALE
    assert zs.generation == {"gas": 100, "wind": 50}
    assert asm.zone_step("A", ts(13)) is None  # > 3 h -> unbekannt


def test_partial_tech_gap_small_share_stays_measured() -> None:
    data = SourceData(ec_gen={"A": {"gas": series(0, [1000, 1000]), "geothermal": series(0, [1])}})
    zs = make(data).zone_step("A", ts(1))
    assert zs is not None
    assert zs.generation["geothermal"] == 1  # aufgefüllt (stale), aber < 5 %
    assert zs.quality is Quality.MEASURED


def test_low_coverage_without_stale_is_unknown() -> None:
    data = SourceData(ec_gen={"A": {"gas": series(0, [100]), "wind": series(20, [1]), "coal": series(20, [1])}})
    asm = make(data)
    assert asm.zone_step("A", ts(19)) is None  # nur 1 von 3 Technologien belegt (stale)


def test_unknown_zone_gets_last_known_intensity() -> None:
    data = SourceData(ec_gen={"A": {"gas": series(0, [100])}})
    inp, unknown = make(data, ["A", "B"]).step(ts(0), {"B": 321.0})
    assert unknown == ["B"]
    assert inp.unknown_intensity == {"B": 321.0}
    assert "A" in inp.zones


def test_flows_average_both_sides_and_fallbacks() -> None:
    data = SourceData(
        ec_gen={"A": {"gas": series(0, [1])}, "B": {"gas": series(0, [1])}},
        # A meldet Import 100 aus B (= Fluss B->A 100), B meldet Export 120 nach A (Import -120)
        ec_flows={"A": {"B": series(0, [100])}, "B": {"A": series(0, [-120])}},
        en_flows={("B", "A"): series(1, [77])},
    )
    asm = make(data, ["A", "B"])
    f0 = asm.flow_step(ts(0))
    assert f0[("A", "B")] == (-110.0, Quality.MEASURED)  # Mittel beider Seiten, netto A->B
    f1 = asm.flow_step(ts(1))
    assert f1[("A", "B")] == (-77.0, Quality.MEASURED)  # ENTSO-E A11 als Sekundärquelle
    f2 = asm.flow_step(ts(2))
    assert f2[("A", "B")] == (-110.0, Quality.STALE)  # letzter Wert der Primärquelle
    assert ("A", "B") not in asm.flow_step(ts(20))  # > 3 h -> entfällt


def test_flow_to_external_region() -> None:
    data = SourceData(ec_gen={"A": {"gas": series(0, [1])}}, ec_flows={"A": {"TR": series(0, [-40])}})
    f = make(data).flow_step(ts(0))
    assert f[("A", "TR")] == (40.0, Quality.MEASURED)  # 40 MW Export von A in die Türkei

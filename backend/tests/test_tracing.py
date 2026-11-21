"""Flow-Tracing gegen von Hand berechnete Mini-Netze."""

from __future__ import annotations

import random

import pytest

from co2ampel.models import Quality, StepInput, ZoneStep
from co2ampel.tracing import NoSupplyError, TracingConfig, trace

from .conftest import T0

# Einfache Faktoren, damit sich alles im Kopf nachrechnen lässt.
CFG = TracingConfig(
    factors={"coal": 1000.0, "gas": 500.0, "wind": 0.0, "storage": 0.0},
    storage_techs=frozenset({"storage"}),
    external_intensity={"X": 200.0},
    default_external_intensity=450.0,
)


def zone(q: Quality = Quality.MEASURED, **gen: float) -> ZoneStep:
    return ZoneStep(generation=dict(gen), storage_charge=0.0, quality=q)


def step(zones: dict[str, ZoneStep], flows: dict[tuple[str, str], float],
         unknown: dict[str, float] | None = None) -> StepInput:
    return StepInput(T0, zones, {k: (v, Quality.MEASURED) for k, v in flows.items()}, unknown or {})


def test_isolated_zone_equals_production_mix() -> None:
    # A: 100 MW Kohle + 100 MW Wind -> (100*1000 + 100*0) / 200 = 500
    r = trace(step({"A": zone(coal=100, wind=100)}, {}), CFG)
    assert r["A"].consumption == pytest.approx(500.0)
    assert r["A"].production == pytest.approx(500.0)


def test_two_zones() -> None:
    # A: Kohle 100, exportiert 50 nach B. B: Wind 100.
    # c_A = 1000 (keine Importe)
    # c_B = (100*0 + 50*1000) / (100 + 50) = 333.33
    r = trace(step({"A": zone(coal=100), "B": zone(wind=100)}, {("A", "B"): 50}), CFG)
    assert r["A"].consumption == pytest.approx(1000.0)
    assert r["B"].consumption == pytest.approx(50_000 / 150)
    assert r["B"].production == pytest.approx(0.0)


def test_negative_flow_means_reverse_direction() -> None:
    # gleiches Netz, Fluss als (B, A) mit -50 angegeben
    r = trace(step({"A": zone(coal=100), "B": zone(wind=100)}, {("B", "A"): -50}), CFG)
    assert r["B"].consumption == pytest.approx(50_000 / 150)


def test_transit() -> None:
    # A (Kohle 100) -> B 50 MW; B (Wind 100) -> C 60 MW; C (Gas 40)
    # c_A = 1000
    # c_B = 50*1000 / (100 + 50) = 333.33
    # c_C = (40*500 + 60*c_B) / (40 + 60) = (20000 + 20000) / 100 = 400
    r = trace(step({"A": zone(coal=100), "B": zone(wind=100), "C": zone(gas=40)},
                   {("A", "B"): 50, ("B", "C"): 60}), CFG)
    assert r["A"].consumption == pytest.approx(1000.0)
    assert r["B"].consumption == pytest.approx(1000 / 3)
    assert r["C"].consumption == pytest.approx(400.0)


def test_ring_flow() -> None:
    # Ring A -> B -> C -> A mit je 30 MW; A Kohle 100, B Wind 100, C Gas 100.
    #   130 c_A = 100000 + 30 c_C
    #   130 c_B =      0 + 30 c_A
    #   130 c_C =  50000 + 30 c_B
    # Einsetzen: c_B = 3/13 c_A ; c_C = (50000 + 90/13 c_A) / 130
    #   130 c_A = 100000 + 30*50000/130 + 30*90/(13*130) c_A
    #   c_A (130 - 2700/1690) = 100000 + 1500000/130
    a = (100_000 + 1_500_000 / 130) / (130 - 2700 / 1690)
    b = 3 / 13 * a
    c = (50_000 + 30 * b) / 130
    r = trace(step({"A": zone(coal=100), "B": zone(wind=100), "C": zone(gas=100)},
                   {("A", "B"): 30, ("B", "C"): 30, ("C", "A"): 30}), CFG)
    assert r["A"].consumption == pytest.approx(a)
    assert r["B"].consumption == pytest.approx(b)
    assert r["C"].consumption == pytest.approx(c)
    assert a == pytest.approx(868.66, abs=0.01)


def test_four_zones_with_external_and_storage() -> None:
    # X ist extern (200 g fest) und liefert 100 MW nach A.
    # A: Gas 50 + Speicherentladung 50 -> Speicher hat die Intensität von A und kürzt sich:
    #   c_A (50 + 50 + 100) = 50*500 + 50*c_A + 100*200  =>  c_A * 150 = 45000  => c_A = 300
    # A -> B 80 MW; B: Wind 120  => c_B = 80*300 / 200 = 120
    # B -> C 40 MW; C: Kohle 10, Wind 50 => c_C = (10*1000 + 40*120) / 100 = 148
    # C -> D 20 MW; D: Gas 80 => c_D = (80*500 + 20*148) / 100 = 429.6
    r = trace(step(
        {"A": zone(gas=50, storage=50), "B": zone(wind=120), "C": zone(coal=10, wind=50), "D": zone(gas=80)},
        {("X", "A"): 100, ("A", "B"): 80, ("B", "C"): 40, ("C", "D"): 20}), CFG)
    assert r["A"].consumption == pytest.approx(300.0)
    assert r["A"].production == pytest.approx(500.0)  # Produktion ohne Speicher
    assert r["B"].consumption == pytest.approx(120.0)
    assert r["C"].consumption == pytest.approx(148.0)
    assert r["D"].consumption == pytest.approx(429.6)


def test_unknown_zone_uses_last_known_intensity_and_flags_estimated() -> None:
    # U ist unbekannt (letzter Wert 600) und liefert 50 MW nach A (Wind 50):
    # c_A = 50*600 / 100 = 300
    r = trace(step({"A": zone(wind=50)}, {("U", "A"): 50}, unknown={"U": 600.0}), CFG)
    assert r["A"].consumption == pytest.approx(300.0)
    assert r["A"].quality is Quality.ESTIMATED


def test_unlisted_neighbor_uses_default_external_intensity() -> None:
    r = trace(step({"A": zone(wind=50)}, {("Z", "A"): 50}), CFG)
    assert r["A"].consumption == pytest.approx(450.0 / 2)


def test_quality_propagates_from_significant_stale_import() -> None:
    zs = {"A": zone(coal=100), "B": zone(wind=100)}
    inp = StepInput(T0, zs, {("A", "B"): (50.0, Quality.STALE)}, {})  # 50/150 = 33 % >= 25 %
    assert trace(inp, CFG)["B"].quality is Quality.STALE
    inp = StepInput(T0, zs, {("A", "B"): (20.0, Quality.STALE)}, {})  # 20/120 = 17 % -> unerheblich
    assert trace(inp, CFG)["B"].quality is Quality.MEASURED


def test_zone_without_supply_raises() -> None:
    with pytest.raises(NoSupplyError) as exc:
        trace(step({"A": zone(coal=100), "B": zone(wind=0)}, {("B", "A"): 10}), CFG)
    assert exc.value.zones == ["B"]


def test_unknown_technology_raises() -> None:
    from co2ampel.tracing import TracingError

    with pytest.raises(TracingError):
        trace(step({"A": zone(nuclear_fusion=10)}, {}), CFG)


@pytest.mark.parametrize("seed", range(25))
def test_mass_conservation_random_networks(seed: int) -> None:
    """Emissionen bleiben erhalten:
    Σ_i c_i·(Nettoverbrauch_i) + Σ Exporte ins Ausland·c_i = Σ_i E_i + Σ Importe aus dem Ausland·c_ext
    und jede Intensität liegt in der konvexen Hülle der Faktoren."""
    rnd = random.Random(seed)
    n = rnd.randint(2, 7)
    names = [f"Z{i}" for i in range(n)]
    zones = {z: zone(coal=rnd.uniform(0, 300), gas=rnd.uniform(0, 300), wind=rnd.uniform(1, 300),
                     storage=rnd.uniform(0, 50)) for z in names}
    flows: dict[tuple[str, str], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            if rnd.random() < 0.6:
                flows[(names[i], names[j])] = rnd.uniform(-150, 150)
    flows[("X", names[0])] = rnd.uniform(0, 100)  # Import von extern
    flows[(names[-1], "Y")] = rnd.uniform(0, 100)  # Export ins Ausland (default 450)
    r = trace(step(zones, flows), CFG)

    lhs = 0.0
    rhs = sum(mw * CFG.factors[k] for z in zones.values() for k, mw in z.generation.items() if k != "storage")
    for z in names:
        inflow = sum(v for (a, b), v in flows.items() if b == z and v > 0) + \
            sum(-v for (a, b), v in flows.items() if a == z and v < 0)
        outflow = sum(v for (a, b), v in flows.items() if a == z and v > 0) + \
            sum(-v for (a, b), v in flows.items() if b == z and v < 0)
        gen = sum(mw for k, mw in zones[z].generation.items() if k != "storage")
        net_use = gen + inflow - outflow  # Speicherentladung kürzt sich heraus
        c = r[z].consumption
        assert c is not None
        assert 0.0 - 1e-9 <= c <= 1000.0 + 1e-9
        lhs += c * net_use
    lhs += sum(v * (r[a].consumption or 0) for (a, b), v in flows.items() if b == "Y")
    rhs += sum(v * 200.0 for (a, b), v in flows.items() if a == "X")
    assert lhs == pytest.approx(rhs, rel=1e-9)

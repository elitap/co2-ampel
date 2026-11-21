"""Flow-Tracing (proportional sharing) über Netto-Grenzflüsse.

Für jede bekannte Zone i gilt (siehe docs/DECISIONS.md, Abschnitt Methodik):

    c_i · (G_i + Σ_j F_ji) = Σ_k G_ik · e_k + Σ_j F_ji · c_j

mit F_ji = positiver Nettoimport aus j nach i. Speicherentladung (Pumpspeicher, Batterie)
geht mit der Intensität der eigenen Zone ein (c_i) und kürzt sich deshalb auf beiden
Seiten heraus; Speicherladen ist Verbrauch und taucht im Gleichungssystem nicht auf.
Nachbarn ohne Daten (unbekannte Zonen) und Regionen außerhalb des Datenbereichs sind
externe Quellen mit fester Intensität.

Das ganze verbundene Netz wird pro Zeitschritt als ein lineares System A·c = b gelöst.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from .models import Quality, StepInput, ZoneResult

log = logging.getLogger(__name__)

MAX_CONDITION = 1e12
EPS_MW = 1e-6
# Importe aus unbekannten Zonen prägen das Flag ab 5 % der Versorgung (-> estimated),
# lückengefüllte (stale) Flüsse erst ab 25 % (sonst wäre wegen unterschiedlicher Veröffentlichungs-
# verzögerungen fast jede Zone 'stale').
SIGNIFICANT_SHARE = 0.05
SIGNIFICANT_FLOW_SHARE = 0.25


class TracingError(RuntimeError):
    """Das Gleichungssystem ist singulär, schlecht konditioniert oder das Ergebnis unplausibel."""


class NoSupplyError(TracingError):
    """Zonen ohne Erzeugung und ohne Importe (Zeile der Matrix wäre null)."""

    def __init__(self, zones: list[str]) -> None:
        super().__init__(f"Zonen ohne Erzeugung und ohne Importe: {', '.join(zones)}")
        self.zones = zones


@dataclass(frozen=True)
class TracingConfig:
    factors: Mapping[str, float]
    storage_techs: frozenset[str]
    external_intensity: Mapping[str, float]
    default_external_intensity: float


def _factor(cfg: TracingConfig, tech: str) -> float:
    try:
        return cfg.factors[tech]
    except KeyError as exc:  # Konfigurationsfehler: muss vorher abgefangen werden
        raise TracingError(f"Kein Emissionsfaktor für Technologie '{tech}'") from exc


def trace(step: StepInput, cfg: TracingConfig) -> dict[str, ZoneResult]:
    """Berechnet Verbrauchs- und Produktionsintensität aller bekannten Zonen eines Zeitschritts."""
    known = sorted(step.zones)
    idx = {z: n for n, z in enumerate(known)}
    n = len(known)
    if n == 0:
        return {}

    fixed: dict[str, float] = {}

    def fixed_intensity(zone: str) -> float:
        if zone in step.unknown_intensity:
            return step.unknown_intensity[zone]
        return cfg.external_intensity.get(zone, cfg.default_external_intensity)

    own_gen = np.zeros(n)  # Erzeugung ohne Speicherentladung
    emissions = np.zeros(n)  # Σ G_ik e_k ohne Speicherentladung
    storage_out = np.zeros(n)
    for z in known:
        i = idx[z]
        for tech, mw in step.zones[z].generation.items():
            if mw <= 0:
                continue
            if tech in cfg.storage_techs:
                storage_out[i] += mw
            else:
                own_gen[i] += mw
                emissions[i] += mw * _factor(cfg, tech)

    inflow = np.zeros(n)
    outflow = np.zeros(n)
    a_offdiag = np.zeros((n, n))  # a_offdiag[i, j] = F_ji (bekannt -> bekannt)
    rhs_fixed = np.zeros(n)  # Σ F_ji c_j für feste Quellen
    import_quality: dict[str, list[tuple[float, Quality]]] = {z: [] for z in known}
    import_unknown: dict[str, float] = dict.fromkeys(known, 0.0)

    for (a, b), (value, q) in step.flows.items():
        if abs(value) <= EPS_MW:
            continue
        src, dst, f = (a, b, value) if value > 0 else (b, a, -value)
        if dst in idx:
            j = idx[dst]
            inflow[j] += f
            import_quality[dst].append((f, q))
            if src in idx:
                a_offdiag[j, idx[src]] += f
            else:
                c_src = fixed_intensity(src)
                fixed[src] = c_src
                rhs_fixed[j] += f * c_src
                if src in step.unknown_intensity:
                    import_unknown[dst] += f
        if src in idx:
            outflow[idx[src]] += f

    diag = own_gen + inflow
    no_supply = [known[i] for i in range(n) if diag[i] <= EPS_MW]
    if no_supply:
        raise NoSupplyError(no_supply)

    a_mat = np.diag(diag) - a_offdiag
    b_vec = emissions + rhs_fixed
    cond = float(np.linalg.cond(a_mat))
    if not np.isfinite(cond) or cond > MAX_CONDITION:
        raise TracingError(f"Gleichungssystem schlecht konditioniert (cond={cond:.3g})")
    c = np.linalg.solve(a_mat, b_vec)

    # Plausibilität: c_i ist eine konvexe Kombination aus Emissionsfaktoren und festen Quellen.
    bounds = [_factor(cfg, t) for z in known for t in step.zones[z].generation if t not in cfg.storage_techs]
    bounds += list(fixed.values())
    lo, hi = (min(bounds), max(bounds)) if bounds else (0.0, 0.0)
    tol = 1e-6 * max(1.0, hi)
    if not np.all(np.isfinite(c)) or np.any(c < lo - tol) or np.any(c > hi + tol):
        raise TracingError(f"Lösung außerhalb der konvexen Hülle [{lo}, {hi}]: {c}")
    residual = float(np.max(np.abs(a_mat @ c - b_vec)))
    if residual > 1e-6 * max(1.0, float(np.max(np.abs(b_vec)))):
        raise TracingError(f"Residuum zu groß: {residual}")

    results: dict[str, ZoneResult] = {}
    for z in known:
        i = idx[z]
        zs = step.zones[z]
        supply = own_gen[i] + storage_out[i] + inflow[i]
        q = zs.quality
        by_quality: dict[Quality, float] = {}
        for f, fq in import_quality[z]:
            by_quality[fq] = by_quality.get(fq, 0.0) + f
        for fq, f in by_quality.items():
            if supply > 0 and f / supply >= SIGNIFICANT_FLOW_SHARE:
                q = Quality.worst(q, fq)
        if supply > 0 and import_unknown[z] / supply >= SIGNIFICANT_SHARE:
            q = Quality.worst(q, Quality.ESTIMATED)
        production = float(emissions[i] / own_gen[i]) if own_gen[i] > EPS_MW else None
        results[z] = ZoneResult(
            zone=z,
            timestamp=step.timestamp,
            consumption=float(max(0.0, c[i])),
            production=production,
            quality=q,
            generation_mw=float(own_gen[i] + storage_out[i]),
            import_mw=float(inflow[i]),
            export_mw=float(outflow[i]),
        )
    return results

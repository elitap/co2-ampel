"""Gemeinsame Datentypen."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Quality(StrEnum):
    """Qualitätsflag eines Werts. Reihenfolge = aufsteigend schlechter."""

    MEASURED = "measured"
    FORECAST = "forecast"
    STALE = "stale"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"

    @property
    def rank(self) -> int:
        return _RANK[self]

    @staticmethod
    def worst(*qs: Quality) -> Quality:
        return max(qs, key=lambda q: q.rank) if qs else Quality.MEASURED


_RANK = {
    Quality.MEASURED: 0,
    Quality.FORECAST: 1,
    Quality.STALE: 2,
    Quality.ESTIMATED: 3,
    Quality.UNKNOWN: 4,
}

# Zeitreihe: UTC-Zeitstempel (Intervallbeginn) -> Wert
Series = dict[datetime, float]


@dataclass
class ZoneRaw:
    """Rohdaten einer Zone aus einer Quelle (nur Messwerte bzw. Prognosen).

    generation: Technologie (kanonischer Name) -> Zeitreihe in MW (>= 0)
    storage_charge: Pumpspeicher-/Batterieladen in MW (>= 0, zählt als Verbrauch)
    """

    generation: dict[str, Series] = field(default_factory=dict)
    storage_charge: Series = field(default_factory=dict)


@dataclass
class FlowRaw:
    """Physikalischer Fluss zwischen zwei Zonen: Wert > 0 = Fluss von a nach b (MW)."""

    a: str
    b: str
    values: Series = field(default_factory=dict)


@dataclass
class ZoneStep:
    """Aufbereitete Eingangsdaten einer Zone in einem Zeitschritt."""

    generation: dict[str, float]  # Technologie -> MW (inkl. Speicherentladung)
    storage_charge: float
    quality: Quality


@dataclass
class StepInput:
    """Alle Eingangsdaten eines Zeitschritts für das Flow-Tracing."""

    timestamp: datetime
    zones: dict[str, ZoneStep]  # nur bekannte Zonen
    flows: dict[tuple[str, str], tuple[float, Quality]]  # (a, b) -> Netto-Fluss a->b in MW
    unknown_intensity: dict[str, float]  # unbekannte Zonen -> angesetzte Intensität ihrer Exporte


@dataclass
class ZoneResult:
    zone: str
    timestamp: datetime
    consumption: float | None
    production: float | None
    quality: Quality
    generation_mw: float = 0.0
    import_mw: float = 0.0
    export_mw: float = 0.0
    own_generation_mw: float = 0.0  # ohne Speicherentladung
    emissions: float = 0.0  # Σ G_ik·e_k (MW·g/kWh = kg/h) ohne Speicherentladung

    @property
    def net_use_mw(self) -> float:
        """Nettoverbrauch der Zone (inkl. Speicherladen): Erzeugung + Importe - Exporte."""
        return self.generation_mw + self.import_mw - self.export_mw

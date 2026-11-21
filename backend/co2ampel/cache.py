"""Rohdaten-Cache für Energy-Charts (wird mit der Pages-Version veröffentlicht und im nächsten Lauf gelesen).

Hintergrund: Die Energy-Charts API erlaubt nur ca. 2 Anfragen/min je Endpunkt. Ein Lauf fragt deshalb
innerhalb eines Zeitbudgets die am längsten nicht aktualisierten Länder ab; die übrigen kommen aus
diesem Cache.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .models import Series
from .output import iso, parse_iso

log = logging.getLogger(__name__)

ENDPOINTS = ("public_power", "cbpf")


@dataclass
class CacheEntry:
    fetched_at: datetime
    status: str  # ok | not_found
    series: dict[str, Series] = field(default_factory=dict)


@dataclass
class EcCache:
    entries: dict[str, dict[str, CacheEntry]] = field(default_factory=lambda: {e: {} for e in ENDPOINTS})

    def get(self, endpoint: str, country: str) -> CacheEntry | None:
        return self.entries.setdefault(endpoint, {}).get(country)

    def put(self, endpoint: str, country: str, entry: CacheEntry) -> None:
        self.entries.setdefault(endpoint, {})[country] = entry

    def prune(self, oldest: datetime) -> None:
        for ep in self.entries.values():
            for entry in ep.values():
                entry.series = {
                    k: {t: v for t, v in s.items() if t >= oldest} for k, s in entry.series.items()
                }
                entry.series = {k: s for k, s in entry.series.items() if s}

    # ------------------------------------------------------------------ Serialisierung

    def to_json(self, step: timedelta) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for ep, countries in self.entries.items():
            out[ep] = {}
            for c, e in sorted(countries.items()):
                out[ep][c] = {
                    "fetched_at": iso(e.fetched_at),
                    "status": e.status,
                    "series": {k: _pack(s, step) for k, s in sorted(e.series.items()) if s},
                }
        return out

    @classmethod
    def from_json(cls, doc: Mapping[str, Any] | None, step: timedelta) -> EcCache:
        cache = cls()
        if not doc:
            return cache
        for ep in ENDPOINTS:
            for c, e in (doc.get(ep) or {}).items():
                try:
                    cache.put(ep, str(c), CacheEntry(
                        fetched_at=parse_iso(e["fetched_at"]),
                        status=str(e.get("status", "ok")),
                        series={str(k): _unpack(s, step) for k, s in (e.get("series") or {}).items()},
                    ))
                except (KeyError, ValueError, TypeError) as exc:
                    log.warning("Cache-Eintrag %s/%s verworfen: %s", ep, c, exc)
        return cache


def _pack(s: Series, step: timedelta) -> dict[str, Any]:
    keys = sorted(s)
    start = keys[0]
    n = int((keys[-1] - start) / step) + 1
    values: list[float | None] = [None] * n
    for t, v in s.items():
        values[int((t - start) / step)] = round(v, 2)
    return {"start": iso(start), "values": values}


def _unpack(d: Mapping[str, Any], step: timedelta) -> Series:
    start = parse_iso(str(d["start"]))
    out: Series = {}
    for i, v in enumerate(d["values"]):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[start + i * step] = float(v)
    return out

"""APG Transparenzplattform (Austrian Power Grid): Erzeugung je Produktionstyp (AGPT) für AT.

Endpunkt: /api/v1/AGPT/Data/English/PT15M/<von>/<bis> mit Grenzen um Mitternacht Ortszeit
(Europe/Vienna) und genau einem Tag Spanne. Spalten sind ENTSO-E-PSR-Typen (B01 …); B10
(Pumpspeicher) ist netto: negativ = Laden. Verzug ca. 1 h (Energy-Charts: 2–4 h).

Standardmäßig AUS (settings.yaml: apg.enabled). APG nennt keine Lizenz für die Weiterverwendung;
aktivieren erst nach schriftlicher Zustimmung von APG (siehe docs/DECISIONS.md, Abschnitt APG).
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..http import Budget, HttpClient
from ..models import Series

log = logging.getLogger(__name__)

ATTRIBUTION = "Austrian Power Grid AG (APG), transparency.apg.at"
VIENNA = ZoneInfo("Europe/Vienna")
STEP = timedelta(minutes=15)


class ApgParseError(ValueError):
    pass


def day_start_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=VIENNA).astimezone(UTC)


def parse_agpt(payload: bytes | Mapping[str, Any], day: date, mapping: Mapping[str, str | None]
               ) -> dict[str, Series]:
    """Kanonische Technologie -> Erzeugung (MW). Zeitstempel = lokaler Tagesbeginn + i·15 min
    (robust gegen Zeitumstellung: der Tag hat dann 92 bzw. 100 Zeilen)."""
    try:
        doc = json.loads(payload) if isinstance(payload, (bytes, bytearray)) else payload
        rd = doc["ResponseData"]
        cols = [str(c.get("InternalName", "")) for c in rd["ValueColumns"]]
        rows = rd["ValueRows"]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ApgParseError(f"AGPT-Antwort unerwartet: {exc}") from exc
    if not isinstance(rows, list):
        raise ApgParseError("ValueRows fehlt")
    start = day_start_utc(day)
    out: dict[str, Series] = {}
    for i, row in enumerate(rows):
        values = row.get("V") if isinstance(row, Mapping) else None
        if not isinstance(values, list) or len(values) != len(cols):
            continue
        t = start + i * STEP
        sums: dict[str, float] = {}
        for psr, cell in zip(cols, values, strict=True):
            v = cell.get("V") if isinstance(cell, Mapping) else None
            if (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    or (isinstance(cell, Mapping) and cell.get("M"))):
                continue
            canon = mapping.get(psr)
            if canon is None or canon == "charge" or v < 0:  # negativ (B10) = Pumpspeicherladen
                continue
            sums[canon] = sums.get(canon, 0.0) + float(v)
        for canon, mw in sums.items():
            out.setdefault(canon, {})[t] = mw
    return out


class ApgClient:
    def __init__(self, http: HttpClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    def fetch_day(self, day: date, budget: Budget | None = None) -> bytes | None:
        nxt = day + timedelta(days=1)
        url = (f"{self.base_url}/api/v1/AGPT/Data/English/PT15M/"
               f"{day:%Y-%m-%d}T000000/{nxt:%Y-%m-%d}T000000")
        res = self.http.get(url, budget=budget)
        if res is None or res.status != 200:
            log.warning("APG AGPT %s: %s", day, None if res is None else f"HTTP {res.status}")
            return None
        return res.body


def fetch_generation(client: ApgClient, now: datetime, window: timedelta,
                     mapping: Mapping[str, str | None]) -> dict[str, Series]:
    """Alle lokalen Tage abrufen, die das Fenster berührt (meist 1, um Mitternacht 2 Anfragen)."""
    first = (now - window).astimezone(VIENNA).date()
    last = now.astimezone(VIENNA).date()
    out: dict[str, Series] = {}
    day = first
    while day <= last:
        body = client.fetch_day(day)
        if body:
            try:
                for k, s in parse_agpt(body, day, mapping).items():
                    out.setdefault(k, {}).update(s)
            except ApgParseError as exc:
                log.error("APG %s: %s", day, exc)
        day += timedelta(days=1)
    return out

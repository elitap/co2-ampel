"""Energy-Charts API (api.energy-charts.info, CC BY 4.0): Parser und Abruf.

Genutzt werden die v2-Endpunkte ``public_power`` (Erzeugung je Technologie, MW) und ``cbpf``
(physikalische Grenzflüsse, GW, positiv = Import). Beide liefern Daten je Land.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..config import CHARGE
from ..http import Budget, HttpClient
from ..models import Series

log = logging.getLogger(__name__)

ATTRIBUTION = "Energy-Charts (Fraunhofer ISE), energy-charts.info, CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
UNIT_TO_MW = {"MW": 1.0, "GW": 1000.0, "kW": 0.001}


class ParseError(ValueError):
    pass


@dataclass
class ParsedPower:
    generation: dict[str, Series]  # kanonische Technologie -> MW
    charge: Series  # Speicherladen, MW >= 0
    unmapped: list[str]


def parse_timestamp(value: str) -> datetime:
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        raise ParseError(f"Zeitstempel ohne Zeitzone: {value}")
    return ts.astimezone(UTC)


def _envelope(payload: bytes | Mapping[str, Any], endpoint: str) -> Mapping[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        try:
            data = json.loads(payload)
        except ValueError as exc:
            raise ParseError(f"{endpoint}: kein gültiges JSON") from exc
    else:
        data = payload
    if not isinstance(data, Mapping):
        raise ParseError(f"{endpoint}: Objekt erwartet")
    if not str(data.get("schema_version", "")).startswith("2"):
        raise ParseError(f"{endpoint}: unbekannte schema_version {data.get('schema_version')!r}")
    if not isinstance(data.get("data"), list) or not isinstance(data.get("series"), list):
        raise ParseError(f"{endpoint}: Felder 'data'/'series' fehlen")
    return data


def _interval(data: Mapping[str, Any]) -> timedelta:
    minutes = data.get("interval_minutes")
    if isinstance(minutes, (int, float)) and 1 <= minutes <= 1440:
        return timedelta(minutes=float(minutes))
    res = str(data.get("resolution", "PT15M"))
    table = {"PT15M": 15, "PT30M": 30, "PT1H": 60, "PT60M": 60}
    return timedelta(minutes=table.get(res, 15))


def _series_scale(data: Mapping[str, Any]) -> dict[str, float | None]:
    """Umrechnungsfaktor nach MW je Serie (None = keine Leistungseinheit, ignorieren)."""
    default_unit = str(data.get("unit", "MW"))
    out: dict[str, float | None] = {}
    for s in data["series"]:
        if not isinstance(s, Mapping) or "id" not in s:
            continue
        unit = str(s.get("unit", default_unit))
        out[str(s["id"])] = UNIT_TO_MW.get(unit)
    return out


def _rows(data: Mapping[str, Any]) -> list[tuple[datetime, Mapping[str, Any]]]:
    rows: list[tuple[datetime, Mapping[str, Any]]] = []
    for row in data["data"]:
        if not isinstance(row, Mapping) or not isinstance(row.get("values"), Mapping):
            continue
        try:
            ts = parse_timestamp(str(row["timestamp"]))
        except (KeyError, ValueError):
            log.warning("Zeile mit ungültigem Zeitstempel ignoriert: %r", row.get("timestamp"))
            continue
        rows.append((ts, row["values"]))
    return rows


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) and abs(f) < 1e7 else None  # NaN/absurde Werte verwerfen


def _expand(ts: datetime, interval: timedelta, step: timedelta) -> list[datetime]:
    """Ein Intervall (z. B. 1 h) auf die Modellschritte (15 min) aufteilen."""
    n = max(1, int(interval / step))
    return [ts + i * step for i in range(n)]


def parse_public_power(
    payload: bytes | Mapping[str, Any],
    mapping: Mapping[str, str | None],
    step: timedelta = timedelta(minutes=15),
) -> ParsedPower:
    data = _envelope(payload, "public_power")
    scale = _series_scale(data)
    interval = _interval(data)
    unmapped = sorted(sid for sid in scale if sid not in mapping)
    if unmapped:
        log.warning("public_power %s: unbekannte Serien ignoriert: %s", data.get("country"), unmapped)
    gen: dict[str, Series] = {}
    charge: Series = {}
    for ts, values in _rows(data):
        sums: dict[str, float] = {}
        for sid, raw in values.items():
            canon = mapping.get(str(sid))
            factor = scale.get(str(sid))
            v = _num(raw)
            if canon is None or factor is None or v is None:
                continue
            mw = abs(v) * factor if canon == CHARGE else max(0.0, v * factor)
            sums[canon] = sums.get(canon, 0.0) + mw
        for t in _expand(ts, interval, step):
            for canon, mw in sums.items():
                if canon == CHARGE:
                    charge[t] = mw
                else:
                    gen.setdefault(canon, {})[t] = mw
    return ParsedPower(generation=gen, charge=charge, unmapped=unmapped)


def parse_cbpf(payload: bytes | Mapping[str, Any], step: timedelta = timedelta(minutes=15)) -> dict[str, Series]:
    """Nachbar-ID -> Import in MW (positiv = Import in das abgefragte Land)."""
    data = _envelope(payload, "cbpf")
    scale = _series_scale(data)
    interval = _interval(data)
    attrs = data.get("attributes")
    conv = attrs.get("sign_convention", "") if isinstance(attrs, Mapping) else ""
    sign = -1.0 if "positive = export" in str(conv) else 1.0
    out: dict[str, Series] = {}
    for ts, values in _rows(data):
        for key, raw in values.items():
            sid = str(key)
            if sid == "sum":
                continue
            factor = scale.get(sid)
            v = _num(raw)
            if factor is None or v is None:
                continue
            for t in _expand(ts, interval, step):
                out.setdefault(sid, {})[t] = sign * v * factor
    return {k: strip_trailing_zeros(s) for k, s in out.items()}


def strip_trailing_zeros(series: Series) -> Series:
    """Am aktuellen Rand liefert cbpf für noch nicht veröffentlichte Flüsse 0.0 statt null.

    Eine abschließende Folge exakter Nullen wird daher als "noch nicht verfügbar" behandelt –
    außer die ganze Reihe ist null (Leitung tatsächlich außer Betrieb).
    """
    keys = sorted(series)
    last_nonzero = next((i for i in range(len(keys) - 1, -1, -1) if series[keys[i]] != 0.0), None)
    if last_nonzero is None:
        return series
    return {k: series[k] for k in keys[: last_nonzero + 1]}


# --------------------------------------------------------------------------- Abruf


@dataclass
class FetchOutcome:
    country: str
    endpoint: str
    status: str  # ok | not_found | failed | skipped
    payload: bytes | None = None


class EnergyChartsClient:
    def __init__(self, http: HttpClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    def fetch(self, endpoint: str, country: str, start: datetime, end: datetime,
              budget: Budget | None = None) -> FetchOutcome:
        params = {
            "country": country,
            "start": start.strftime("%Y-%m-%dT%H:%MZ"),
            "end": end.strftime("%Y-%m-%dT%H:%MZ"),
        }
        res = self.http.get(f"{self.base_url}/v2/{endpoint}", params=params, budget=budget)
        if res is None:
            return FetchOutcome(country, endpoint, "skipped" if budget and budget.exhausted() else "failed")
        if res.status == 404:
            log.info("Energy-Charts %s/%s: keine Daten (404)", endpoint, country)
            return FetchOutcome(country, endpoint, "not_found")
        if res.status != 200:
            log.warning("Energy-Charts %s/%s: HTTP %d", endpoint, country, res.status)
            return FetchOutcome(country, endpoint, "failed")
        return FetchOutcome(country, endpoint, "ok", res.body)

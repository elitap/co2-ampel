"""ENTSO-E Transparency Platform REST API (sekundäre Quelle, nur mit ENTSOE_API_TOKEN).

Dokumenttypen:
  A75  Actual Generation per Production Type (processType A16)
  A11  Cross-border Physical Flows (in_Domain/out_Domain)
  A69  Day-ahead Generation Forecasts for Wind and Solar (processType A01)
  A71  Generation Forecast – Day ahead (processType A01), nur Summe

Das XML wird mit defusedxml geparst (Schutz vor XXE/Entity-Expansion). Namensräume werden
ignoriert, damit Versionswechsel der Schemata (z. B. :3:0 -> :4:0) nicht brechen.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from xml.etree.ElementTree import Element  # nur Typen; Parsing über defusedxml

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET

from ..http import Budget, HttpClient
from ..models import Series

log = logging.getLogger(__name__)

ATTRIBUTION = "ENTSO-E Transparency Platform, transparency.entsoe.eu"
_RES = re.compile(r"^PT(\d+)M$|^PT(\d+)H$|^P1D$")


class EntsoeParseError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: Element, name: str) -> Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _children(el: Element, name: str) -> Iterator[Element]:
    for c in el:
        if _local(c.tag) == name:
            yield c


def _text(el: Element | None) -> str | None:
    return None if el is None or el.text is None else el.text.strip()


def _path_text(el: Element, *names: str) -> str | None:
    cur: Element | None = el
    for n in names:
        if cur is None:
            return None
        cur = _child(cur, n)
    return _text(cur)


def _parse_dt(value: str) -> datetime:
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


def _resolution(value: str) -> timedelta:
    m = _RES.match(value)
    if not m:
        raise EntsoeParseError(f"Unbekannte Auflösung {value!r}")
    if m.group(1):
        return timedelta(minutes=int(m.group(1)))
    if m.group(2):
        return timedelta(hours=int(m.group(2)))
    return timedelta(days=1)


def _root(xml: bytes) -> Element:
    try:
        root: Element = SafeET.fromstring(xml)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise EntsoeParseError(f"Ungültiges oder unsicheres XML: {exc}") from exc
    return root


def is_acknowledgement(xml: bytes) -> str | None:
    """Gibt den Begründungstext zurück, wenn die Antwort ein Acknowledgement (keine Daten/Fehler) ist."""
    root = _root(xml)
    if _local(root.tag) != "Acknowledgement_MarketDocument":
        return None
    reason = _child(root, "Reason")
    return _path_text(reason, "text") if reason is not None else "Acknowledgement ohne Begründung"


def _period_points(period: Element, curve_type: str, step: timedelta) -> Series:
    start_s = _path_text(period, "timeInterval", "start")
    end_s = _path_text(period, "timeInterval", "end")
    res_s = _text(_child(period, "resolution"))
    if not (start_s and end_s and res_s):
        raise EntsoeParseError("Period ohne timeInterval/resolution")
    start, end, res = _parse_dt(start_s), _parse_dt(end_s), _resolution(res_s)
    n_total = int((end - start) / res)
    points: dict[int, float] = {}
    for p in _children(period, "Point"):
        pos_s, qty_s = _text(_child(p, "position")), _text(_child(p, "quantity"))
        if pos_s is None or qty_s is None:
            continue
        try:
            points[int(pos_s)] = float(qty_s)
        except ValueError:
            continue
    out: Series = {}
    if not points:
        return out
    last: float | None = None
    for pos in range(1, n_total + 1):
        if pos in points:
            last = points[pos]
        elif curve_type != "A03":  # A01: fehlender Punkt = Lücke; A03: Wert gilt bis zum nächsten Punkt
            last = None
        if last is None:
            continue
        t0 = start + (pos - 1) * res
        n = max(1, int(res / step))
        for i in range(n):
            out[t0 + i * step] = last
    return out


@dataclass
class GenerationDoc:
    """Erzeugung (in_Domain) und Verbrauch (out_Domain) je PSR-Typ; Schlüssel None = ohne PSR-Typ."""

    generation: dict[str | None, Series] = field(default_factory=dict)
    consumption: dict[str | None, Series] = field(default_factory=dict)


def parse_generation(xml: bytes, step: timedelta = timedelta(minutes=15)) -> GenerationDoc:
    """Parser für A75, A69 und A71 (GL_MarketDocument)."""
    if (reason := is_acknowledgement(xml)) is not None:
        log.info("ENTSO-E: keine Daten (%s)", reason)
        return GenerationDoc()
    root = _root(xml)
    if _local(root.tag) != "GL_MarketDocument":
        raise EntsoeParseError(f"GL_MarketDocument erwartet, erhalten: {_local(root.tag)}")
    doc = GenerationDoc()
    for ts in _children(root, "TimeSeries"):
        psr = _path_text(ts, "MktPSRType", "psrType")
        unit = _text(_child(ts, "quantity_Measure_Unit.name")) or "MAW"
        if unit != "MAW":
            log.warning("ENTSO-E: Einheit %s ignoriert", unit)
            continue
        curve = _text(_child(ts, "curveType")) or "A01"
        is_out = _child(ts, "outBiddingZone_Domain.mRID") is not None and _child(
            ts, "inBiddingZone_Domain.mRID") is None
        target = doc.consumption if is_out else doc.generation
        series = target.setdefault(psr, {})
        for period in _children(ts, "Period"):
            for t, v in _period_points(period, curve, step).items():
                series[t] = series.get(t, 0.0) + max(0.0, v)
    return doc


def parse_flows(xml: bytes, step: timedelta = timedelta(minutes=15)) -> dict[tuple[str, str], Series]:
    """Parser für A11: (out_Domain, in_Domain) -> Fluss in MW (>= 0) von out nach in."""
    if (reason := is_acknowledgement(xml)) is not None:
        log.info("ENTSO-E: keine Daten (%s)", reason)
        return {}
    root = _root(xml)
    if _local(root.tag) != "Publication_MarketDocument":
        raise EntsoeParseError(f"Publication_MarketDocument erwartet, erhalten: {_local(root.tag)}")
    out: dict[tuple[str, str], Series] = {}
    for ts in _children(root, "TimeSeries"):
        src = _text(_child(ts, "out_Domain.mRID"))
        dst = _text(_child(ts, "in_Domain.mRID"))
        if not src or not dst:
            continue
        curve = _text(_child(ts, "curveType")) or "A01"
        series = out.setdefault((src, dst), {})
        for period in _children(ts, "Period"):
            series.update(_period_points(period, curve, step))
    return out


def _fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%d%H%M")


class EntsoeClient:
    """Dünner Client; das Token wird nie geloggt."""

    def __init__(self, token: str, http: HttpClient, base_url: str) -> None:
        self._token = token
        self.http = http
        self.base_url = base_url

    def _get(self, params: dict[str, str], budget: Budget | None) -> bytes | None:
        shown = "ENTSO-E " + " ".join(f"{k}={v}" for k, v in params.items())
        res = self.http.get(self.base_url, params={**params, "securityToken": self._token}, budget=budget,
                            log_url=shown)
        if res is None:
            return None
        if res.status in (200, 400) and res.body.lstrip().startswith(b"<"):
            # 400 enthält bei "keine Daten" ein Acknowledgement-Dokument
            return res.body
        log.warning("%s: HTTP %d", shown, res.status)
        return None

    def actual_generation(self, eic: str, start: datetime, end: datetime, budget: Budget | None = None
                          ) -> bytes | None:
        return self._get({"documentType": "A75", "processType": "A16", "in_Domain": eic,
                          "periodStart": _fmt(start), "periodEnd": _fmt(end)}, budget)

    def wind_solar_forecast(self, eic: str, start: datetime, end: datetime, budget: Budget | None = None
                            ) -> bytes | None:
        return self._get({"documentType": "A69", "processType": "A01", "in_Domain": eic,
                          "periodStart": _fmt(start), "periodEnd": _fmt(end)}, budget)

    def generation_forecast(self, eic: str, start: datetime, end: datetime, budget: Budget | None = None
                            ) -> bytes | None:
        return self._get({"documentType": "A71", "processType": "A01", "in_Domain": eic,
                          "periodStart": _fmt(start), "periodEnd": _fmt(end)}, budget)

    def physical_flow(self, eic_from: str, eic_to: str, start: datetime, end: datetime,
                      budget: Budget | None = None) -> bytes | None:
        return self._get({"documentType": "A11", "out_Domain": eic_from, "in_Domain": eic_to,
                          "periodStart": _fmt(start), "periodEnd": _fmt(end)}, budget)

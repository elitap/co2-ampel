"""Gebotszonen statt Länder für NO, SE, DK, IT (nur mit ENTSO-E-Token).

Ablauf je Lauf:
1. fetch_split: A75 je Gebotszone. Ein Land wird nur aufgeteilt, wenn alle seine Gebotszonen
   aktuelle Ist-Werte (<= max_stale_hours) haben. Danach A11 für alle Grenzen der aufgeteilten Länder.
2. apply_split: Land durch Gebotszonen ersetzen. Energy-Charts-Länderflüsse werden einer Gebotszonen-
   Grenze zugeordnet, wenn die Länder-Grenze aus genau einer Gebotszonen-Grenze besteht (z. B. NO-DE nur
   über NO2); sonst stammen die Flüsse aus A11.
3. aggregate_countries: Land als verbrauchsgewichtetes Mittel seiner Gebotszonen ausgeben.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta

from .config import Config, SplitCountry
from .gapfill import SourceData
from .http import Budget, HttpClient
from .models import Quality, Series, ZoneResult
from .sources import entsoe as en

log = logging.getLogger(__name__)

Edge = tuple[str, str]


def _resolve(code: str, cfg: Config, split: Mapping[str, SplitCountry]) -> str:
    """Gebotszone eines nicht aufgeteilten Landes -> Land."""
    for s in cfg.bidding:
        if code in s.codes and s.country not in split:
            return s.country
    return code


def split_edges(cfg: Config, split: Mapping[str, SplitCountry]) -> set[Edge]:
    edges: set[Edge] = set()
    for s in split.values():
        for a, b in (*s.internal, *s.external):
            ra, rb = _resolve(a, cfg, split), _resolve(b, cfg, split)
            if ra != rb:
                edges.add((ra, rb) if ra < rb else (rb, ra))
    return edges


def _eic(code: str, cfg: Config) -> str | None:
    try:
        z = cfg.zone(code)
    except KeyError:
        return None  # externe Region (z. B. GB): keine A11-Daten
    return z.entsoe if z.parent else z.border_eic


def fetch_split(cfg: Config, data: SourceData, now: datetime, token: str,
                http: HttpClient | None = None) -> dict[str, SplitCountry]:
    client = en.EntsoeClient(token, http or HttpClient(), cfg.entsoe_base_url)
    budget = Budget(cfg.entsoe_split_budget_seconds)
    step = timedelta(minutes=cfg.step_minutes)
    start = now - timedelta(hours=cfg.fetch_window_hours)
    fresh = now - timedelta(hours=cfg.max_stale_hours)
    split: dict[str, SplitCountry] = {}
    for s in cfg.bidding:
        gens: dict[str, dict[str, Series]] = {}
        for z in s.zones:
            body = client.actual_generation(z.entsoe, start, now, budget)
            try:
                gen = en.canonical_generation(en.parse_generation(body, step), cfg.mapping_entsoe) if body else {}
            except en.EntsoeParseError as exc:
                log.error("ENTSO-E A75 %s: %s", z.code, exc)
                gen = {}
            latest = max((max(v) for v in gen.values() if v), default=None)
            if latest is None or latest < fresh:
                log.info("Gebotszonen %s: %s ohne aktuelle A75-Daten -> Land bleibt ein Knoten", s.country, z.code)
                break
            gens[z.code] = gen
        else:
            data.en_gen.update(gens)
            split[s.country] = s
    for a, b in sorted(split_edges(cfg, split)):
        ea, eb = _eic(a, cfg), _eic(b, cfg)
        if ea is None or eb is None or budget.exhausted():
            continue
        net: Series = {}
        try:
            for src, dst, sign in ((ea, eb, 1.0), (eb, ea, -1.0)):
                body = client.physical_flow(src, dst, start, now, budget)
                for s_ in (en.parse_flows(body, step).values() if body else ()):
                    for t, v in s_.items():
                        net[t] = net.get(t, 0.0) + sign * v
        except en.EntsoeParseError as exc:
            log.error("ENTSO-E A11 %s-%s: %s", a, b, exc)
            continue
        if net:
            data.en_flows[(a, b)] = net
    log.info("Gebotszonen: aufgeteilt %s, %d ENTSO-E-Anfragen", sorted(split) or "keine",
             client.http.request_count)
    return split


def apply_split(cfg: Config, data: SourceData, split: Mapping[str, SplitCountry]) -> list[str]:
    """Ersetzt aufgeteilte Länder durch ihre Gebotszonen; liefert die Zonenliste für das Tracing."""
    zones: list[str] = []
    for code in cfg.zone_codes:
        zones.extend(split[code].codes if code in split else [code])
    if not split:
        return zones
    for c in split:
        data.ec_gen.pop(c, None)
        data.en_gen.pop(c, None)
    edges = split_edges(cfg, split)

    def side(code: str) -> set[str]:
        return set(split[code].codes) if code in split else {code}

    remapped: dict[str, dict[str, Series]] = {}
    for reporter, neigh in data.ec_flows.items():
        for other, series in neigh.items():
            if reporter not in split and other not in split:
                remapped.setdefault(reporter, {})[other] = series
                continue
            rs, os_ = side(reporter), side(other)
            links = [(a, b) if a in rs else (b, a) for a, b in edges
                     if (a in rs and b in os_) or (b in rs and a in os_)]
            if len(links) == 1:
                r, o = links[0]
                remapped.setdefault(r, {})[o] = series  # Import in r aus o
            elif not links:
                log.warning("Keine Gebotszonen-Grenze für %s-%s konfiguriert", reporter, other)
    data.ec_flows = remapped
    return zones


def aggregate_countries(results: dict[datetime, dict[str, ZoneResult]], split: Mapping[str, SplitCountry],
                        significant_share: float = 0.05) -> None:
    """Fügt je Zeitschritt das Land als verbrauchsgewichtetes Mittel seiner Gebotszonen hinzu."""
    for t, rs in results.items():
        for country, s in split.items():
            subs = [rs[c] for c in s.codes if c in rs]
            known = [r for r in subs if r.quality is not Quality.UNKNOWN and r.consumption is not None]
            if not known:
                rs[country] = ZoneResult(country, t, None, None, Quality.UNKNOWN)
                continue
            uses = [max(0.0, r.net_use_mw) for r in known]
            total_use = sum(uses)
            if total_use > 0:
                cons = sum((r.consumption or 0.0) * u for r, u in zip(known, uses, strict=True)) / total_use
            else:
                cons = sum(r.consumption or 0.0 for r in known) / len(known)
            own = sum(r.own_generation_mw for r in known)
            prod = sum(r.emissions for r in known) / own if own > 0 else None
            q = Quality.MEASURED
            for r, u in zip(known, uses, strict=True):
                if total_use <= 0 or u / total_use >= significant_share:
                    q = Quality.worst(q, r.quality)
            if len(known) < len(s.codes):
                q = Quality.worst(q, Quality.ESTIMATED)
            rs[country] = ZoneResult(
                country, t, cons, prod, q,
                generation_mw=sum(r.generation_mw for r in known),
                own_generation_mw=own,
                emissions=sum(r.emissions for r in known),
            )

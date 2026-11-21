"""Ein Rechenlauf: Vorstand laden, Daten abrufen, Flow-Tracing, Dateien schreiben."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .bidding import aggregate_countries, apply_split, fetch_split
from .cache import CacheEntry, EcCache
from .config import Config, SplitCountry
from .gapfill import Assembler, SourceData
from .http import Budget, HttpClient
from .models import Quality, Series, ZoneResult
from .output import (
    PlausibilityError,
    attribution,
    check_plausibility,
    iso,
    keep_better,
    latest_entry,
    merge_history,
    pick_latest,
    points_from_history,
    thresholds,
    validate,
    write_json,
)
from .sources import energy_charts as ec
from .sources import entsoe as en
from .tracing import NoSupplyError, TracingConfig, TracingError, trace

log = logging.getLogger(__name__)

NOT_FOUND_RETRY = timedelta(hours=6)


def floor_step(ts: datetime, step: timedelta) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return epoch + ((ts - epoch) // step) * step


# --------------------------------------------------------------------------- Vorstand


@dataclass
class PreviousState:
    latest: dict[str, Any] | None = None
    history: dict[str, dict[str, Any]] = field(default_factory=dict)
    cache: dict[str, Any] | None = None


def _json_or_none(body: bytes | None) -> dict[str, Any] | None:
    if not body:
        return None
    try:
        doc = json.loads(body)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def load_previous_from_url(base_url: str, zones: list[str], http: HttpClient) -> PreviousState:
    """Zuletzt veröffentlichte Pages-Version lesen (Cache-Busting per Query-Parameter)."""
    base = base_url.rstrip("/")
    bust = {"t": str(int(time.time()))}

    def get(path: str) -> dict[str, Any] | None:
        res = http.get(f"{base}/{path}", params=bust)
        if res is None or res.status != 200:
            log.info("Vorstand %s nicht verfügbar (%s)", path, None if res is None else res.status)
            return None
        return _json_or_none(res.body)

    state = PreviousState(latest=get("latest.json"), cache=get("state/cache.json"))
    for z in zones:
        doc = get(f"history/{z}.json")
        if doc:
            state.history[z] = doc
    return state


def load_previous_from_dir(path: Path, zones: list[str]) -> PreviousState:
    def get(rel: str) -> dict[str, Any] | None:
        p = path / rel
        return _json_or_none(p.read_bytes()) if p.is_file() else None

    state = PreviousState(latest=get("latest.json"), cache=get("state/cache.json"))
    for z in zones:
        doc = get(f"history/{z}.json")
        if doc:
            state.history[z] = doc
    return state


# --------------------------------------------------------------------------- Energy-Charts


def plan_requests(countries: list[str], cache: EcCache, endpoint: str, now: datetime) -> list[str]:
    """Rotation: nie abgefragte zuerst, dann die am längsten nicht aktualisierten."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    plan = []
    for c in countries:
        e = cache.get(endpoint, c)
        if e is not None and e.status == "not_found" and now - e.fetched_at < NOT_FOUND_RETRY:
            continue
        plan.append(c)
    def last_fetch(c: str) -> datetime:
        e = cache.get(endpoint, c)
        return e.fetched_at if e is not None else epoch

    return sorted(plan, key=lambda c: (last_fetch(c), c))


def fetch_energy_charts(cfg: Config, cache: EcCache, now: datetime, bootstrap: bool,
                        http_factory: Any = HttpClient) -> dict[str, int]:
    start = now - timedelta(hours=cfg.fetch_window_hours)
    end = now + timedelta(minutes=cfg.step_minutes)
    budget_s = cfg.ec_bootstrap_budget_seconds if bootstrap else cfg.ec_budget_seconds
    countries = [z.energy_charts for z in cfg.zones]
    endpoints = {"public_power": countries, "cbpf": countries}
    outcomes: dict[str, list[ec.FetchOutcome]] = {}

    def worker(endpoint: str, plan: list[str]) -> None:
        client = ec.EnergyChartsClient(http_factory(), cfg.ec_base_url)
        budget = Budget(budget_s)
        res: list[ec.FetchOutcome] = []
        for c in plan:
            if budget.exhausted():
                res.append(ec.FetchOutcome(c, endpoint, "skipped"))
                continue
            res.append(client.fetch(endpoint, c, start, end, budget))
        outcomes[endpoint] = res

    threads = [threading.Thread(target=worker, args=(ep, plan_requests(cs, cache, ep, now)), daemon=True)
               for ep, cs in endpoints.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats: dict[str, int] = {}
    step = timedelta(minutes=cfg.step_minutes)
    for endpoint, res in outcomes.items():
        for o in res:
            stats[f"{endpoint}.{o.status}"] = stats.get(f"{endpoint}.{o.status}", 0) + 1
            if o.status == "not_found":
                cache.put(endpoint, o.country, CacheEntry(now, "not_found"))
            if o.status != "ok" or o.payload is None:
                continue
            try:
                if endpoint == "public_power":
                    series = ec.parse_public_power(o.payload, cfg.mapping_ec, step).generation
                else:
                    series = ec.parse_cbpf(o.payload, step)
            except ec.ParseError as exc:
                log.error("Energy-Charts %s/%s nicht lesbar: %s", endpoint, o.country, exc)
                stats[f"{endpoint}.parse_error"] = stats.get(f"{endpoint}.parse_error", 0) + 1
                continue
            old = cache.get(endpoint, o.country)
            # Eine neue Antwort ersetzt ihr ganzes Zeitfenster (Revisionen, entfernte Platzhalter).
            merged: dict[str, Series] = {
                k: {t: v for t, v in s.items() if t < start} for k, s in (old.series if old else {}).items()
            }
            for k, s in series.items():
                merged.setdefault(k, {}).update(s)
            cache.put(endpoint, o.country, CacheEntry(now, "ok", merged))
    cache.prune(now - timedelta(hours=cfg.fetch_window_hours + cfg.max_stale_hours))
    log.info("Energy-Charts: %s", ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    return stats


def source_data_from_cache(cfg: Config, cache: EcCache) -> SourceData:
    country_zone = cfg.ec_country_to_zone()
    alias = cfg.alias_map()
    data = SourceData()
    for c, e in cache.entries.get("public_power", {}).items():
        if c in country_zone and e.status == "ok" and e.series:
            data.ec_gen[country_zone[c]] = e.series
    for c, e in cache.entries.get("cbpf", {}).items():
        if c not in country_zone or e.status != "ok":
            continue
        zone = country_zone[c]
        flows: dict[str, Series] = {}
        for neighbor, s in e.series.items():
            code = alias.get(neighbor)
            if code is None:
                code = f"X-{neighbor}"
                log.warning("Unbekannter Nachbar %r von %s, als externe Region behandelt", neighbor, zone)
            flows[code] = s
        data.ec_flows[zone] = flows
    return data


# --------------------------------------------------------------------------- ENTSO-E (Lückenfüller)


def _latest(series_map: Mapping[str, Series] | None) -> datetime | None:
    ts = [max(s) for s in (series_map or {}).values() if s]
    return max(ts) if ts else None


def fill_from_entsoe(cfg: Config, data: SourceData, now: datetime, token: str,
                     http: HttpClient | None = None, skip: frozenset[str] = frozenset()) -> bool:
    """Fragt ENTSO-E nur für Zonen/Grenzen mit Lücken ab (je Zone und Datentyp höchstens einmal)."""
    client = en.EntsoeClient(token, http or HttpClient(), cfg.entsoe_base_url)
    budget = Budget(cfg.entsoe_budget_seconds)
    start = now - timedelta(hours=cfg.fetch_window_hours)
    end = now + timedelta(hours=1)
    gap_before = now - timedelta(hours=cfg.max_stale_hours)
    step = timedelta(minutes=cfg.step_minutes)
    used = False

    def gen_map(doc: en.GenerationDoc) -> dict[str, Series]:
        return en.canonical_generation(doc, cfg.mapping_entsoe)

    for z in cfg.zones:
        if z.code in skip:  # in Gebotszonen aufgeteilt, Daten stammen bereits aus ENTSO-E
            continue
        last = _latest(data.ec_gen.get(z.code))
        if last is not None and last >= gap_before:
            continue
        if budget.exhausted():
            break
        try:
            body = client.actual_generation(z.entsoe, start, now, budget)
            if body:
                data.en_gen[z.code] = gen_map(en.parse_generation(body, step))
                used = used or bool(data.en_gen[z.code])
            last_en = _latest(data.en_gen.get(z.code))
            if last_en is not None and last_en >= gap_before:
                continue
            body = client.wind_solar_forecast(z.entsoe, start, end, budget)
            if body:
                data.en_forecast_ws[z.code] = gen_map(en.parse_generation(body, step))
                used = used or bool(data.en_forecast_ws[z.code])
            body = client.generation_forecast(z.entsoe, start, end, budget)
            if body:
                total = en.parse_generation(body, step).generation.get(None, {})
                if total:
                    data.en_forecast_total[z.code] = total
                    used = True
        except en.EntsoeParseError as exc:
            log.error("ENTSO-E %s: %s", z.code, exc)

    eic = {z.code: z.entsoe for z in cfg.zones}
    pairs: set[tuple[str, str]] = set()
    for zone, neigh in data.ec_flows.items():
        for other in neigh:
            if other in eic:
                pairs.add(tuple(sorted((zone, other))))  # type: ignore[arg-type]
    for a, b in sorted(pairs):
        latest_ec = max(
            [max(s) for s in (data.ec_flows.get(a, {}).get(b, {}), data.ec_flows.get(b, {}).get(a, {})) if s],
            default=None,
        )
        if latest_ec is not None and latest_ec >= gap_before:
            continue
        if budget.exhausted():
            break
        try:
            net: Series = {}
            for src, dst, sign in ((a, b, 1.0), (b, a, -1.0)):
                body = client.physical_flow(eic[src], eic[dst], start, now, budget)
                if not body:
                    continue
                for s in en.parse_flows(body, step).values():
                    for t, v in s.items():
                        net[t] = net.get(t, 0.0) + sign * v
            if net:
                data.en_flows[(a, b)] = net
                used = True
        except en.EntsoeParseError as exc:
            log.error("ENTSO-E Fluss %s-%s: %s", a, b, exc)
    log.info("ENTSO-E: %d Anfragen, genutzt=%s", client.http.request_count, used)
    return used


# --------------------------------------------------------------------------- Rechnen


def tracing_config(cfg: Config) -> TracingConfig:
    return TracingConfig(
        factors=cfg.factors,
        storage_techs=cfg.storage_techs,
        external_intensity=cfg.external_intensity,
        default_external_intensity=cfg.default_external_intensity,
    )


def compute(cfg: Config, data: SourceData, steps: list[datetime], last_known: dict[str, float],
            zones: list[str] | None = None) -> dict[datetime, dict[str, ZoneResult]]:
    """Flow-Tracing für alle Zeitschritte (chronologisch, damit unbekannte Zonen den jeweils
    letzten bekannten Wert erhalten)."""
    asm = Assembler(data, zones or cfg.zone_codes, timedelta(hours=cfg.max_stale_hours), cfg.min_tech_coverage,
                    cfg.significant_share)
    tcfg = tracing_config(cfg)
    known = dict(last_known)
    out: dict[datetime, dict[str, ZoneResult]] = {}
    for t in sorted(steps):
        inp, unknown = asm.step(t, known)
        if not any(zs.quality in (Quality.MEASURED, Quality.FORECAST) for zs in inp.zones.values()):
            continue
        results: dict[str, ZoneResult] | None = None
        for _ in range(5):
            try:
                results = trace(inp, tcfg)
                break
            except NoSupplyError as exc:
                for z in exc.zones:
                    inp.zones.pop(z)
                    unknown.append(z)
                    if z in known:
                        inp.unknown_intensity[z] = known[z]
            except TracingError as exc:
                log.error("%s: Flow-Tracing fehlgeschlagen: %s", iso(t), exc)
                break
        if results is None:
            continue
        for z in unknown:
            results[z] = ZoneResult(z, t, None, None, Quality.UNKNOWN)
        for z, r in results.items():
            if r.consumption is not None:
                known[z] = r.consumption
        out[t] = results
    return out


# --------------------------------------------------------------------------- Lauf


@dataclass
class RunResult:
    latest: dict[str, Any]
    missing: list[str]
    entsoe_used: bool
    ec_stats: dict[str, int]


def run(cfg: Config, out_dir: Path, previous: PreviousState, now: datetime | None = None,
        entsoe_token: str | None = None, fetch: bool = True,
        http_factory: Any = HttpClient) -> RunResult:
    step = timedelta(minutes=cfg.step_minutes)
    now = floor_step(now or datetime.now(UTC), step)
    cache = EcCache.from_json((previous.cache or {}).get("energy_charts"), step)
    bootstrap = not any(cache.entries.get("public_power", {}).values())
    stats: dict[str, int] = {}
    if fetch:
        stats = fetch_energy_charts(cfg, cache, now, bootstrap, http_factory)
    data = source_data_from_cache(cfg, cache)
    entsoe_used = False
    split: dict[str, SplitCountry] = {}
    if entsoe_token and cfg.bidding:
        split = fetch_split(cfg, data, now, entsoe_token, http_factory())
        entsoe_used = bool(split)
    run_zones = apply_split(cfg, data, split)
    if entsoe_token:
        entsoe_used = fill_from_entsoe(cfg, data, now, entsoe_token, http_factory(), frozenset(split)) or entsoe_used
    else:
        log.info("ENTSOE_API_TOKEN nicht gesetzt: nur Energy-Charts")

    # Ausgabezonen: Länder, mit Token zusätzlich alle Gebotszonen (auch wenn gerade nicht aufgeteilt)
    catalog = cfg.zone_codes + ([z.code for z in cfg.sub_zones] if entsoe_token else [])
    histories = {z: points_from_history(previous.history.get(z)) for z in catalog}
    last_known: dict[str, float] = {}
    for z, pts in histories.items():
        if pts:
            p = pts[max(pts)]
            if p.consumption is not None:
                last_known[z] = p.consumption

    window_start = now - timedelta(hours=cfg.fetch_window_hours)
    steps = [window_start + i * step for i in range(int((now - window_start) / step) + 1)]
    results = compute(cfg, data, steps, last_known, run_zones)
    aggregate_countries(results, split, cfg.significant_share)
    per_zone: dict[str, dict[datetime, ZoneResult]] = {z: {} for z in catalog}
    for t, rs in results.items():
        for z, r in rs.items():
            per_zone.setdefault(z, {})[t] = r
    missing = [z for z in cfg.zone_codes
               if not any(r.quality is not Quality.UNKNOWN for r in per_zone.get(z, {}).values())]

    prev_latest = {e.get("zone"): e for e in (previous.latest or {}).get("zones", []) if isinstance(e, dict)}
    attr = attribution(entsoe_used)
    gen_at = iso(datetime.now(UTC))
    entries: list[dict[str, Any]] = []
    history_docs: dict[str, dict[str, Any]] = {}
    for z in catalog:
        merged = merge_history(histories[z], per_zone.get(z, {}), now, cfg.history_hours)
        entry = keep_better(latest_entry(cfg, z, pick_latest(merged), now), prev_latest.get(z))
        if entry.get("timestamp") and now - datetime.fromisoformat(
                entry["timestamp"].replace("Z", "+00:00")) > timedelta(hours=cfg.stale_after_hours) \
                and entry["quality"] in ("measured", "forecast"):
            entry["quality"] = "stale"
        entries.append(entry)
        zone = cfg.zone(z)
        history_docs[z] = {
            "schema_version": 1, "kind": "history", "generated_at": gen_at, "attribution": attr,
            "zone": z, "name": zone.name_de, "name_en": zone.name_en, "unit": "gCO2eq/kWh",
            "thresholds": thresholds(cfg), "points": [p.to_json() for p in merged.values()],
        }

    check_plausibility(cfg, entries, missing)  # wirft PlausibilityError -> nichts wird geschrieben
    for doc in history_docs.values():
        for p in doc["points"]:
            for key in ("consumption", "production"):
                v = p.get(key)
                if v is not None and not cfg.plausibility.min_value <= v <= cfg.plausibility.max_value:
                    raise PlausibilityError(f"Historie {doc['zone']}: {key}={v} unplausibel")

    latest = {
        "schema_version": 1, "kind": "latest", "generated_at": gen_at, "attribution": attr,
        "unit": "gCO2eq/kWh", "thresholds": thresholds(cfg), "zones": entries,
    }
    zones_doc = {
        "schema_version": 1, "kind": "zones", "generated_at": gen_at, "attribution": attr,
        "zones": [{"zone": c, "name": cfg.zone(c).name_de, "name_en": cfg.zone(c).name_en,
                   **({"parent": par} if (par := cfg.zone(c).parent) else {})} for c in catalog],
    }
    cache_doc = {
        "schema_version": 1, "kind": "cache", "generated_at": gen_at,
        "attribution": attribution(False), "energy_charts": cache.to_json(step),
    }
    # Erst alles validieren, dann schreiben (latest.json zuletzt).
    files: list[tuple[Path, dict[str, Any]]] = [
        *((out_dir / "history" / f"{z}.json", doc) for z, doc in history_docs.items()),
        (out_dir / "zones.json", zones_doc),
        (out_dir / "state" / "cache.json", cache_doc),
        (out_dir / "latest.json", latest),
    ]
    for _, doc in files:
        validate(doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    for path, doc in files:
        write_json(path, doc, schema_check=False)
    log.info("Fertig: %d Zonen, fehlend: %s", len(entries), ", ".join(missing) or "keine")
    return RunResult(latest, missing, entsoe_used, stats)

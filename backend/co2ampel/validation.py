"""Validierungsbericht (docs/VALIDATION.md) aus gespeicherten Energy-Charts-Rohdaten."""

from __future__ import annotations

import json
import logging
import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .cache import CacheEntry, EcCache
from .config import Config
from .gapfill import SourceData
from .models import Quality, ZoneResult
from .output import iso, parse_iso
from .pipeline import compute, source_data_from_cache
from .sources import energy_charts as ec

log = logging.getLogger(__name__)

# Erwartete Größenordnung der Verbrauchsintensität im Spätherbst (gCO2eq/kWh, Lebenszyklus).
# Eigene Einschätzung auf Basis veröffentlichter Jahres-/Monatsmittel (Ember, Electricity Maps,
# Umweltbundesamt, RTE); dient nur der Grobprüfung.
EXPECTED: dict[str, tuple[float, float, str]] = {
    "AT": (80, 300, "Wasserkraft + Gas, im Winter hohe Importe aus DE/CZ"),
    "DE": (200, 600, "Kohle/Gas-Anteil im November hoch, Wind schwankend"),
    "FR": (15, 120, "Kernkraft dominiert; Gas-Spitzen im Winter"),
    "PL": (500, 950, "Kohle dominiert"),
    "NO": (10, 80, "fast nur Wasserkraft"),
    "CH": (20, 180, "Kern + Wasser, Winterimporte"),
}


def load_raw_dir(cfg: Config, data_dir: Path) -> tuple[SourceData, datetime, datetime]:
    step = timedelta(minutes=cfg.step_minutes)
    cache = EcCache()
    for z in cfg.zones:
        c = z.energy_charts
        for endpoint in ("public_power", "cbpf"):
            f = data_dir / f"{endpoint}_{c}.json"
            if not f.is_file():
                continue
            payload = f.read_bytes()
            if endpoint == "public_power":
                series = ec.parse_public_power(payload, cfg.mapping_ec, step).generation
            else:
                series = ec.parse_cbpf(payload, step)
            fetched = parse_iso(str(json.loads(payload).get("generated_at", "1970-01-01T00:00:00Z")))
            cache.put(endpoint, c, CacheEntry(fetched, "ok", series))
    data = source_data_from_cache(cfg, cache)
    all_ts = [t for zs in data.ec_gen.values() for s in zs.values() for t in s]
    return data, min(all_ts), max(all_ts)


@dataclass
class ZoneStats:
    zone: str
    n_steps: int
    n_measured: int
    n_any: int
    cons: list[float]
    prod: list[float]


def zone_stats(cfg: Config, results: Mapping[datetime, Mapping[str, ZoneResult]], n_steps: int
               ) -> list[ZoneStats]:
    out = []
    for z in cfg.zone_codes:
        rs = [r[z] for r in results.values() if z in r]
        cons = [r.consumption for r in rs if r.consumption is not None and r.quality is not Quality.UNKNOWN]
        prod = [r.production for r in rs if r.production is not None and r.quality is not Quality.UNKNOWN]
        out.append(ZoneStats(
            zone=z, n_steps=n_steps,
            n_measured=sum(1 for r in rs if r.quality is Quality.MEASURED),
            n_any=len(cons), cons=cons, prod=prod,
        ))
    return out


def _fmt(vals: list[float]) -> str:
    if not vals:
        return "– / – / –"
    return f"{min(vals):.0f} / {statistics.median(vals):.0f} / {max(vals):.0f}"


def compare_reference(results: Mapping[datetime, Mapping[str, ZoneResult]], zone: str,
                      ref: Mapping[str, float]) -> dict[str, float] | None:
    """Vergleich Produktionsintensität mit Referenz (Stundenmittel, UTC-Stundenbeginn -> Wert)."""
    hourly: dict[datetime, list[float]] = {}
    for t, rs in results.items():
        r = rs.get(zone)
        if r is None or r.production is None or r.quality is Quality.UNKNOWN:
            continue
        hourly.setdefault(t.replace(minute=0), []).append(r.production)
    diffs, ours, theirs = [], [], []
    for ts_s, v in ref.items():
        t = parse_iso(ts_s)
        if t in hourly:
            o = statistics.fmean(hourly[t])
            diffs.append(o - v)
            ours.append(o)
            theirs.append(v)
    if len(diffs) < 10:
        return None
    corr = statistics.correlation(ours, theirs) if len(set(theirs)) > 1 and len(set(ours)) > 1 else float("nan")
    return {
        "n": len(diffs), "mean_ours": statistics.fmean(ours), "mean_ref": statistics.fmean(theirs),
        "mean_diff": statistics.fmean(diffs), "mae": statistics.fmean(abs(d) for d in diffs), "corr": corr,
    }


def write_report(cfg: Config, data_dir: Path, out: Path, reference: Path | None, notes: Path | None = None) -> None:
    data, t0, t1 = load_raw_dir(cfg, data_dir)
    step = timedelta(minutes=cfg.step_minutes)
    steps = [t0 + i * step for i in range(int((t1 - t0) / step) + 1)]
    results = compute(cfg, data, steps, {})
    stats = zone_stats(cfg, results, len(steps))
    by_zone = {s.zone: s for s in stats}
    refs: dict[str, Any] = json.loads(reference.read_text(encoding="utf-8")) if reference else {}

    lines = [
        "# Validierung",
        "",
        f"Zeitraum: {iso(t0)} bis {iso(t1)} (UTC), {len(steps)} Zeitschritte à {cfg.step_minutes} min.",
        "Datenbasis: echte Antworten der Energy-Charts API (`public_power`, `cbpf`) für alle Länder, einmalig",
        "abgerufen und mit `python -m co2ampel validate` durchgerechnet (ohne ENTSO-E-Token).",
        "",
        "Werte in gCO2eq/kWh (Lebenszyklus). „Anteil gemessen“ = Anteil der Zeitschritte, in denen die Zone",
        "mit Qualität `measured` berechnet wurde; „berechnet“ = Anteil mit irgendeinem Ergebnis",
        "(inkl. `stale`/`estimated`).",
        "",
        "## Kennzahlen pro Zone",
        "",
        "| Zone | Verbrauch min / median / max | Produktion min / median / max | Anteil gemessen | berechnet |",
        "|---|---|---|---|---|",
    ]
    for s in stats:
        lines.append(
            f"| {s.zone} | {_fmt(s.cons)} | {_fmt(s.prod)} | {s.n_measured / s.n_steps:.0%} | "
            f"{s.n_any / s.n_steps:.0%} |")

    lines += ["", "## Plausibilitätsprüfung (bekannte Größenordnungen)", "",
              "| Zone | Median Verbrauch | Erwartung | Ergebnis | Begründung |", "|---|---|---|---|---|"]
    for z, (lo, hi, why) in EXPECTED.items():
        s = by_zone[z]
        med = statistics.median(s.cons) if s.cons else None
        ok = med is not None and lo <= med <= hi
        lines.append(f"| {z} | {'–' if med is None else f'{med:.0f}'} | {lo:.0f}–{hi:.0f} | "
                     f"{'✅ plausibel' if ok else '⚠️ prüfen'} | {why} |")

    lines += ["", "## Vergleich mit offiziellen Landeswerten (Produktionsintensität)", ""]
    for z, ref in refs.items():
        meta = ref.get("meta", {})
        cmp_ = compare_reference(results, z, ref.get("hourly", {}))
        lines.append(f"### {z}: {meta.get('source', '')}")
        lines.append("")
        if meta.get("note"):
            lines += [str(meta["note"]), ""]
        if cmp_ is None:
            lines += ["Kein Vergleich möglich (zu wenige überlappende Stunden oder keine eigenen Werte).", ""]
            continue
        lines += [
            "| Stunden | Mittel CO2-Ampel | Mittel Referenz | mittlere Abweichung | MAE | Korrelation |",
            "|---|---|---|---|---|---|",
            f"| {cmp_['n']:.0f} | {cmp_['mean_ours']:.0f} | {cmp_['mean_ref']:.0f} | {cmp_['mean_diff']:+.0f} | "
            f"{cmp_['mae']:.0f} | {cmp_['corr']:.2f} |",
            "",
        ]
    if notes is not None and notes.is_file():
        lines += ["", notes.read_text(encoding="utf-8").rstrip()]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Bericht geschrieben: %s", out)

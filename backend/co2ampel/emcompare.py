"""Vergleich mit Electricity Maps (nur interne Validierung, Daten werden nicht veröffentlicht).

snapshot: unsere veröffentlichten Werte (+ optional Electricity Maps "latest") festhalten.
report:   Electricity Maps "history" (24 h, stündlich) mit unserer Historie vergleichen.
Das Token wird nur als HTTP-Header gesendet und nie geloggt.
"""

from __future__ import annotations

import itertools
import json
import logging
import statistics
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .http import HttpClient
from .output import iso, parse_iso

log = logging.getLogger(__name__)

EM_BASE = "https://api.electricitymaps.com/v3"
DEFAULT_ZONES = ("AT", "DE", "FR", "CH", "PL")
SAME_MAGNITUDE = 0.25  # |mittlere Abweichung| / Mittel EM


class EmClient:
    def __init__(self, token: str, http: HttpClient | None = None, base: str = EM_BASE) -> None:
        self.http = http or HttpClient(max_attempts=2)
        self.http.session.headers["auth-token"] = token
        self.base = base.rstrip("/")
        self.calls = 0

    def _get(self, path: str, zone: str) -> dict[str, Any] | None:
        self.calls += 1
        res = self.http.get(f"{self.base}/{path}", params={"zone": zone, "emissionFactorType": "lifecycle"},
                            log_url=f"ElectricityMaps {path} zone={zone}")
        if res is None:
            return None
        if res.status != 200:
            log.warning("Electricity Maps %s %s: HTTP %d", path, zone, res.status)
            return {"error": res.status}
        try:
            doc = json.loads(res.body)
        except ValueError:
            return {"error": "invalid json"}
        return doc if isinstance(doc, dict) else {"error": "unexpected"}

    def latest(self, zone: str) -> dict[str, Any] | None:
        return self._get("carbon-intensity/latest", zone)

    def history(self, zone: str) -> dict[str, Any] | None:
        return self._get("carbon-intensity/history", zone)


def _get_json(http: HttpClient, url: str) -> dict[str, Any] | None:
    res = http.get(url, params={"t": str(int(datetime.now(UTC).timestamp()))})
    if res is None or res.status != 200:
        return None
    try:
        doc = json.loads(res.body)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def snapshot(out: Path, pages_url: str, zones: tuple[str, ...], em: EmClient | None) -> dict[str, Any]:
    http = HttpClient(max_attempts=3)
    latest = _get_json(http, f"{pages_url.rstrip('/')}/latest.json") or {}
    ours = {e.get("zone"): e for e in latest.get("zones", []) if isinstance(e, dict) and e.get("zone") in zones}
    snap: dict[str, Any] = {
        "taken_at": iso(datetime.now(UTC)),
        "ours_generated_at": latest.get("generated_at"),
        "ours": ours,
        "em": {z: em.latest(z) for z in zones} if em else {},
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "snapshot.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Snapshot: ours_generated_at=%s, EM-Aufrufe=%d", snap["ours_generated_at"], em.calls if em else 0)
    return snap


def _hourly_ours(history: Mapping[str, Any]) -> dict[datetime, float]:
    buckets: dict[datetime, list[float]] = {}
    for p in history.get("points", []):
        v = p.get("consumption")
        if v is None or p.get("quality") == "unknown":
            continue
        t = parse_iso(p["t"]).replace(minute=0)
        buckets.setdefault(t, []).append(float(v))
    return {t: statistics.fmean(vs) for t, vs in buckets.items()}


def _em_hourly(doc: Mapping[str, Any]) -> dict[datetime, tuple[float, bool]]:
    out: dict[datetime, tuple[float, bool]] = {}
    for h in doc.get("history", []) if isinstance(doc.get("history"), list) else []:
        v = h.get("carbonIntensity")
        if isinstance(v, (int, float)) and h.get("datetime"):
            out[parse_iso(str(h["datetime"])).replace(minute=0, second=0)] = (float(v), bool(h.get("isEstimated")))
    return out


def compare(ours: Mapping[datetime, float], em: Mapping[datetime, tuple[float, bool]]) -> dict[str, float] | None:
    common = sorted(set(ours) & set(em))
    if len(common) < 3:
        return None
    a = [ours[t] for t in common]
    b = [em[t][0] for t in common]
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    corr = statistics.correlation(a, b) if len(set(a)) > 1 and len(set(b)) > 1 else float("nan")
    mean_b = statistics.fmean(b)
    return {
        "n": len(common),
        "n_em_estimated": sum(1 for t in common if em[t][1]),
        "mean_ours": statistics.fmean(a),
        "mean_em": mean_b,
        "mean_diff": statistics.fmean(diffs),
        "mae": statistics.fmean(abs(d) for d in diffs),
        "rel_diff": statistics.fmean(diffs) / mean_b if mean_b else float("nan"),
        "corr": corr,
    }


def _lag_minutes(taken: str, ts: str | None) -> float | None:
    if not ts:
        return None
    return (parse_iso(taken) - parse_iso(ts)).total_seconds() / 60


def _fmt_hours(minutes: list[float]) -> str:
    return f"{statistics.median(minutes) / 60:.1f} h" if minutes else "–"


def report(snap_dir: Path, out: Path, pages_url: str, zones: tuple[str, ...], em: EmClient) -> str:
    snaps = []
    for f in sorted(snap_dir.rglob("snapshot.json")):
        try:
            snaps.append(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    snaps.sort(key=lambda s: s.get("taken_at", ""))
    http = HttpClient(max_attempts=3)

    lines = ["# Vergleich CO2-Ampel ↔ Electricity Maps", "",
             f"Erstellt {iso(datetime.now(UTC))}. Snapshots: {len(snaps)}. Werte: Verbrauchsintensität "
             "gCO2eq/kWh, Lebenszyklus, Stundenmittel (UTC).", ""]

    # 1) Laufen unsere Updates im 15-min-Takt?
    gens = sorted({s["ours_generated_at"] for s in snaps if s.get("ours_generated_at")})
    if len(gens) >= 2:
        gaps = [(parse_iso(b) - parse_iso(a)).total_seconds() / 60 for a, b in itertools.pairwise(gens)]
        lines += ["## Aktualisierung der CO2-Ampel (compute)", "",
                  f"- verschiedene Veröffentlichungen über Nacht: {len(gens)}",
                  f"- Abstand zwischen Veröffentlichungen: Median {statistics.median(gaps):.0f} min, "
                  f"Maximum {max(gaps):.0f} min", ""]

    # 2) Aktualität (Verzug Messzeit -> Abruf)
    lines += ["## Aktualität (Verzug zwischen Zeitstempel des Werts und Abruf)", "",
              "| Zone | CO2-Ampel Median | Electricity Maps Median | EM-Werte geschätzt |", "|---|---|---|---|"]
    for z in zones:
        ours_lag = [lag for s in snaps if (lag := _lag_minutes(s["taken_at"], (s.get("ours", {}).get(z) or {})
                                                               .get("timestamp"))) is not None]
        em_snaps = [s["em"].get(z) for s in snaps if isinstance(s.get("em", {}).get(z), dict)]
        em_lag = [lag for s, e in ((s, s["em"].get(z)) for s in snaps if isinstance(s.get("em", {}).get(z), dict))
                  if (lag := _lag_minutes(s["taken_at"], e.get("datetime"))) is not None]
        est = sum(1 for e in em_snaps if e.get("isEstimated"))
        lines.append(f"| {z} | {_fmt_hours(ours_lag)} | {_fmt_hours(em_lag)} | {est}/{len(em_snaps)} |")

    # 3) Werte über die letzten 24 h
    lines += ["", "## Werte (gleiche Stunden, letzte 24 h)", "",
              "| Zone | Stunden | Mittel CO2-Ampel | Mittel EM | Abweichung | MAE | Korrelation | Größenordnung |",
              "|---|---|---|---|---|---|---|---|"]
    for z in zones:
        hist = _get_json(http, f"{pages_url.rstrip('/')}/history/{z}.json") or {}
        em_doc = em.history(z) or {}
        c = compare(_hourly_ours(hist), _em_hourly(em_doc))
        if c is None:
            lines.append(f"| {z} | – | – | – | – | – | – | keine gemeinsamen Stunden ({em_doc.get('error', 'ok')}) |")
            continue
        ok = abs(c["rel_diff"]) <= SAME_MAGNITUDE
        lines.append(
            f"| {z} | {c['n']:.0f} ({c['n_em_estimated']:.0f} EM geschätzt) | {c['mean_ours']:.0f} | "
            f"{c['mean_em']:.0f} | {c['mean_diff']:+.0f} ({c['rel_diff']:+.0%}) | {c['mae']:.0f} | "
            f"{c['corr']:.2f} | {'✅ gleich' if ok else '⚠️ abweichend'} |")
    lines += ["", f"Electricity-Maps-Aufrufe in diesem Bericht: {em.calls}. „Gleiche Größenordnung“ = mittlere "
              f"Abweichung höchstens ±{SAME_MAGNITUDE:.0%}."]
    text = "\n".join(lines) + "\n"
    out.write_text(text, encoding="utf-8")
    return text

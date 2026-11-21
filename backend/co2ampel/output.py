"""Ausgabedateien bauen, mit dem Vorstand zusammenführen, prüfen und atomar schreiben."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from .config import Config
from .models import Quality, ZoneResult
from .sources import apg, energy_charts, entsoe

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "schema.json"
UNIT = "gCO2eq/kWh"


class PlausibilityError(RuntimeError):
    """Ergebnis unplausibel: alte Dateien bleiben bestehen, Lauf schlägt fehl."""


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def attribution(entsoe_used: bool, apg_used: bool = False) -> list[dict[str, str]]:
    out = [{
        "source": energy_charts.ATTRIBUTION,
        "license": "CC BY 4.0",
        "url": "https://energy-charts.info",
    }]
    if entsoe_used:
        out.append({
            "source": entsoe.ATTRIBUTION,
            "license": "ENTSO-E Transparency Platform Terms and Conditions",
            "url": "https://transparency.entsoe.eu",
        })
    if apg_used:
        out.append({
            "source": apg.ATTRIBUTION,
            "license": "mit Zustimmung von APG",
            "url": "https://transparency.apg.at",
        })
    return out


def thresholds(cfg: Config) -> dict[str, Any]:
    return {"green_below": cfg.traffic_light.green_below, "red_above": cfg.traffic_light.red_above,
            "unit": UNIT}


@lru_cache(maxsize=1)
def _validator() -> jsonschema.protocols.Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    validator: jsonschema.protocols.Validator = cls(schema)
    return validator


def validate(doc: Mapping[str, Any]) -> None:
    _validator().validate(doc)


# --------------------------------------------------------------------------- Historie


@dataclass
class Point:
    t: datetime
    consumption: float | None
    production: float | None
    quality: Quality

    def to_json(self) -> dict[str, Any]:
        # Nur was angezeigt wird: Zeit, Verbrauchsintensität (ganzzahlig), Qualität.
        return {"t": iso(self.t), "consumption": None if self.consumption is None else round(self.consumption),
                "quality": self.quality.value}


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def points_from_history(doc: Mapping[str, Any] | None) -> dict[datetime, Point]:
    out: dict[datetime, Point] = {}
    if not doc:
        return out
    for p in doc.get("points", []):
        try:
            q = Quality(p["quality"])
            if q is Quality.UNKNOWN:
                continue
            out[parse_iso(p["t"])] = Point(parse_iso(p["t"]), p.get("consumption"), p.get("production"), q)
        except (KeyError, ValueError, TypeError):
            continue
    return out


def merge_history(
    old: dict[datetime, Point], new: Mapping[datetime, ZoneResult], now: datetime, hours: float
) -> dict[datetime, Point]:
    """Neue Ergebnisse ersetzen alte nur bei gleicher oder besserer Qualität."""
    merged = dict(old)
    for t, r in new.items():
        if r.quality is Quality.UNKNOWN or r.consumption is None:
            continue
        prev = merged.get(t)
        if prev is None or r.quality.rank <= prev.quality.rank:
            merged[t] = Point(t, r.consumption, r.production, r.quality)
    cutoff = now - timedelta(hours=hours)
    return {t: p for t, p in sorted(merged.items()) if t > cutoff}


def pick_latest(points: Mapping[datetime, Point]) -> Point | None:
    """Jüngster Punkt mit Messwert/Prognose, sonst jüngster Punkt überhaupt."""
    if not points:
        return None
    good = [p for p in points.values() if p.quality in (Quality.MEASURED, Quality.FORECAST)]
    pool = good or list(points.values())
    return max(pool, key=lambda p: p.t)


# --------------------------------------------------------------------------- latest.json


def latest_entry(cfg: Config, zone: str, point: Point | None, now: datetime) -> dict[str, Any]:
    z = cfg.zone(zone)
    if point is None or point.consumption is None:
        return {"zone": zone, "name": z.name_de, "name_en": z.name_en, "timestamp": None,
                "consumption": None, "production": None, "quality": Quality.UNKNOWN.value, "level": "unknown"}
    q = point.quality
    if now - point.t > timedelta(hours=cfg.stale_after_hours):
        q = Quality.worst(q, Quality.STALE)
    return {
        "zone": zone, "name": z.name_de, "name_en": z.name_en, "timestamp": iso(point.t),
        "consumption": _r(point.consumption), "production": _r(point.production), "quality": q.value,
        "level": cfg.traffic_light.level(point.consumption),
    }


def keep_better(new: dict[str, Any], old: Mapping[str, Any] | None) -> dict[str, Any]:
    """Nie einen schlechteren Eintrag als den bisherigen veröffentlichen."""
    if not old or old.get("consumption") is None or old.get("timestamp") is None:
        return new
    if new.get("consumption") is None or new.get("timestamp") is None:
        return dict(old)
    t_new, t_old = parse_iso(new["timestamp"]), parse_iso(old["timestamp"])
    if t_new < t_old:
        return dict(old)
    if t_new == t_old and Quality(new["quality"]).rank > Quality(str(old["quality"])).rank:
        return dict(old)
    return new


def check_plausibility(cfg: Config, entries: list[dict[str, Any]], missing: list[str]) -> None:
    pl = cfg.plausibility
    for e in entries:
        for key in ("consumption", "production"):
            v = e.get(key)
            if v is not None and not pl.min_value <= v <= pl.max_value:
                raise PlausibilityError(f"{e['zone']}: {key}={v} außerhalb [{pl.min_value}, {pl.max_value}]")
    share = len(missing) / max(1, len(cfg.zones))
    if share > pl.max_missing_share:
        raise PlausibilityError(
            f"{len(missing)} von {len(cfg.zones)} Zonen ohne Ergebnis ({share:.0%} > "
            f"{pl.max_missing_share:.0%}): {', '.join(sorted(missing))}")


# --------------------------------------------------------------------------- Schreiben


def write_json(path: Path, doc: Mapping[str, Any], schema_check: bool = True) -> None:
    if schema_check:
        validate(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

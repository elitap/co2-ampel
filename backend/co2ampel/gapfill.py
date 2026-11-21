"""Lückenregeln: aus den Rohdaten aller Quellen die Eingangsdaten je Zeitschritt bilden.

Regelwerk je Zone, Technologie und Zeitschritt (in dieser Reihenfolge):
  1. Ist-Wert der Primärquelle (Energy-Charts)                      -> measured
  2. Ist-Wert der Sekundärquelle (ENTSO-E A75)                       -> measured
  3. Prognose (ENTSO-E A69 für Wind/Solar, A71-Summe auf den letzten
     bekannten Mix verteilt für die übrigen Technologien)            -> forecast
  4. letzter bekannter Ist-Wert, höchstens max_stale_hours alt        -> stale
  5. sonst fehlt der Wert.
Eine Zone gilt in einem Zeitschritt als vorhanden, wenn mindestens min_tech_coverage ihrer aktiven
Technologien über die Stufen 1–3 (bzw. 1–4 für "stale") belegt sind; sonst ist sie "unknown".
Flüsse analog: Energy-Charts (Mittel beider Seiten) -> ENTSO-E A11 -> letzter Wert <= 3 h.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import Quality, Series, StepInput, ZoneStep

WIND_SOLAR = frozenset({"solar", "wind_onshore", "wind_offshore"})


@dataclass
class SourceData:
    """Rohdaten aller Quellen, bereits auf Zonen-Codes und kanonische Technologien abgebildet."""

    ec_gen: dict[str, dict[str, Series]] = field(default_factory=dict)
    ec_flows: dict[str, dict[str, Series]] = field(default_factory=dict)  # zone -> nachbar -> Import MW
    en_gen: dict[str, dict[str, Series]] = field(default_factory=dict)
    en_forecast_ws: dict[str, dict[str, Series]] = field(default_factory=dict)
    en_forecast_total: dict[str, Series] = field(default_factory=dict)
    en_flows: dict[tuple[str, str], Series] = field(default_factory=dict)  # (a, b) -> netto a->b MW


class _Lookup:
    """Schneller Zugriff auf 'letzter bekannter Wert vor t'."""

    def __init__(self, series: Series) -> None:
        self.series = series
        self.keys = sorted(series)

    def at(self, t: datetime) -> float | None:
        return self.series.get(t)

    def last_before(self, t: datetime, max_age: timedelta) -> float | None:
        i = bisect.bisect_left(self.keys, t)
        if i == 0:
            return None
        k = self.keys[i - 1]
        return self.series[k] if t - k <= max_age else None


def _merge(primary: Series | None, secondary: Series | None) -> Series:
    out: Series = dict(secondary or {})
    out.update(primary or {})
    return out


class Assembler:
    def __init__(
        self,
        data: SourceData,
        zones: Iterable[str],
        max_stale: timedelta,
        min_coverage: float,
        significant_share: float,
    ) -> None:
        self.data = data
        self.zones = list(zones)
        self.max_stale = max_stale
        self.min_coverage = min_coverage
        self.significant_share = significant_share
        self._ec: dict[str, dict[str, _Lookup]] = {}
        self._actual: dict[str, dict[str, _Lookup]] = {}
        for z in self.zones:
            ec = data.ec_gen.get(z, {})
            en = data.en_gen.get(z, {})
            self._ec[z] = {k: _Lookup(v) for k, v in ec.items()}
            self._actual[z] = {k: _Lookup(_merge(ec.get(k), en.get(k))) for k in set(ec) | set(en)}
        self._flows = self._build_flows()

    # ------------------------------------------------------------------ Erzeugung

    def _active_techs(self, zone: str) -> list[str]:
        return sorted(k for k, lk in self._actual[zone].items() if lk.series)

    def zone_step(self, zone: str, t: datetime) -> ZoneStep | None:
        techs = self._active_techs(zone)
        if not techs:
            return None
        values: dict[str, tuple[float, Quality]] = {}
        fc_ws = self.data.en_forecast_ws.get(zone, {})
        for k in techs:
            ec_v = self._ec[zone].get(k)
            v = ec_v.at(t) if ec_v else None
            if v is None:
                v = self._actual[zone][k].at(t)  # Ist-Wert ENTSO-E (EC hat Vorrang im Merge)
            if v is not None:
                values[k] = (v, Quality.MEASURED)
                continue
            fc = fc_ws.get(k, {}).get(t) if k in WIND_SOLAR else None
            if fc is not None:
                values[k] = (fc, Quality.FORECAST)

        if len(values) / len(techs) < self.min_coverage:
            self._fill_total_forecast(zone, t, techs, values)
        # Stufe 4: letzter bekannter Wert
        for k in techs:
            if k not in values:
                last = self._actual[zone][k].last_before(t, self.max_stale)
                if last is not None:
                    values[k] = (last, Quality.STALE)

        if len(values) / len(techs) < self.min_coverage:
            return None
        good = sum(1 for _, q in values.values() if q in (Quality.MEASURED, Quality.FORECAST))

        total = sum(v for v, _ in values.values())
        quality = Quality.MEASURED
        if total > 0:
            for v, q in values.values():
                if v / total >= self.significant_share:
                    quality = Quality.worst(quality, q)
        if good / len(techs) < self.min_coverage:
            quality = Quality.worst(quality, Quality.STALE)
        return ZoneStep(
            generation={k: v for k, (v, _) in values.items()},
            storage_charge=0.0,
            quality=quality,
        )

    def _fill_total_forecast(self, zone: str, t: datetime, techs: list[str],
                             values: dict[str, tuple[float, Quality]]) -> None:
        """A71-Summenprognose auf den letzten bekannten Mix der fehlenden Technologien verteilen."""
        total = self.data.en_forecast_total.get(zone, {}).get(t)
        if total is None:
            return
        missing = [k for k in techs if k not in values]
        mix = {k: self._actual[zone][k].last_before(t, timedelta(hours=48)) or 0.0 for k in missing}
        mix_sum = sum(mix.values())
        rest = max(0.0, total - sum(v for v, _ in values.values()))
        if mix_sum <= 0:
            return
        for k, share in mix.items():
            values[k] = (rest * share / mix_sum, Quality.FORECAST)

    # ------------------------------------------------------------------ Flüsse

    def _build_flows(self) -> dict[tuple[str, str], tuple[_Lookup, _Lookup]]:
        """(a, b) mit a < b -> (Energy-Charts netto a->b, ENTSO-E netto a->b)."""
        ec_pair: dict[tuple[str, str], dict[datetime, list[float]]] = {}
        for zone, neigh in self.data.ec_flows.items():
            for other, series in neigh.items():
                if other == zone:
                    continue
                a, b = sorted((zone, other))
                # series = Import in 'zone' aus 'other' => Fluss other -> zone
                sign = 1.0 if (other, zone) == (a, b) else -1.0
                bucket = ec_pair.setdefault((a, b), {})
                for t, v in series.items():
                    bucket.setdefault(t, []).append(sign * v)
        en_pair: dict[tuple[str, str], Series] = {}
        for (x, y), series in self.data.en_flows.items():
            a, b = sorted((x, y))
            sign = 1.0 if (x, y) == (a, b) else -1.0
            target = en_pair.setdefault((a, b), {})
            for t, v in series.items():
                target[t] = sign * v
        out: dict[tuple[str, str], tuple[_Lookup, _Lookup]] = {}
        for key in set(ec_pair) | set(en_pair):
            ec_series = {t: sum(vs) / len(vs) for t, vs in ec_pair.get(key, {}).items()}
            out[key] = (_Lookup(ec_series), _Lookup(en_pair.get(key, {})))
        return out

    def flow_step(self, t: datetime) -> dict[tuple[str, str], tuple[float, Quality]]:
        res: dict[tuple[str, str], tuple[float, Quality]] = {}
        for key, (ec, en) in self._flows.items():
            v = ec.at(t)
            if v is None:
                v = en.at(t)
            if v is not None:
                res[key] = (v, Quality.MEASURED)
                continue
            last = ec.last_before(t, self.max_stale)
            if last is None:
                last = en.last_before(t, self.max_stale)
            if last is not None:
                res[key] = (last, Quality.STALE)
        return res

    # ------------------------------------------------------------------ Zeitschritt

    def step(self, t: datetime, last_known: dict[str, float]) -> tuple[StepInput, list[str]]:
        """Eingangsdaten für Zeitschritt t; zweiter Rückgabewert = unbekannte Zonen."""
        zones: dict[str, ZoneStep] = {}
        unknown: list[str] = []
        for z in self.zones:
            zs = self.zone_step(z, t)
            if zs is None or sum(zs.generation.values()) <= 0:
                unknown.append(z)
            else:
                zones[z] = zs
        unknown_intensity = {z: last_known[z] for z in unknown if z in last_known}
        return StepInput(t, zones, self.flow_step(t), unknown_intensity), unknown

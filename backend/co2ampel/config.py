"""Laden und Prüfen der YAML-Konfiguration (backend/config)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CHARGE = "charge"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Zone:
    code: str
    name_de: str
    name_en: str
    energy_charts: str
    alias: str
    entsoe: str


@dataclass(frozen=True)
class TrafficLight:
    green_below: float
    red_above: float

    def level(self, value: float | None) -> str:
        if value is None:
            return "unknown"
        if value < self.green_below:
            return "green"
        if value > self.red_above:
            return "red"
        return "yellow"


@dataclass(frozen=True)
class Plausibility:
    min_value: float
    max_value: float
    max_missing_share: float


@dataclass(frozen=True)
class Config:
    zones: tuple[Zone, ...]
    external_aliases: dict[str, str]
    factors: dict[str, float]
    factor_sources: dict[str, str]
    storage_techs: frozenset[str]
    mapping_ec: dict[str, str | None]
    mapping_entsoe: dict[str, str | None]
    traffic_light: TrafficLight
    plausibility: Plausibility
    step_minutes: int = 15
    fetch_window_hours: float = 8
    history_hours: float = 48
    max_stale_hours: float = 3
    stale_after_hours: float = 4
    min_tech_coverage: float = 0.5
    significant_share: float = 0.05
    ec_base_url: str = "https://api.energy-charts.info"
    ec_budget_seconds: float = 540
    ec_bootstrap_budget_seconds: float = 1500
    entsoe_base_url: str = "https://web-api.tp.entsoe.eu/api"
    entsoe_budget_seconds: float = 240
    external_intensity: dict[str, float] = field(default_factory=dict)
    default_external_intensity: float = 450

    @property
    def zone_codes(self) -> list[str]:
        return [z.code for z in self.zones]

    def zone(self, code: str) -> Zone:
        for z in self.zones:
            if z.code == code:
                return z
        raise KeyError(code)

    def alias_map(self) -> dict[str, str]:
        """Energy-Charts-Nachbar-ID -> Zonen-Code (inkl. externer Regionen)."""
        out = {z.alias: z.code for z in self.zones}
        out.update(self.external_aliases)
        return out

    def ec_country_to_zone(self) -> dict[str, str]:
        return {z.energy_charts: z.code for z in self.zones}


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: erwartet eine Zuordnung auf oberster Ebene")
    return data


def load_config(config_dir: Path = DEFAULT_CONFIG_DIR) -> Config:
    zones_raw = _load(config_dir / "zones.yaml")
    ef_raw = _load(config_dir / "emission_factors.yaml")
    tl_raw = _load(config_dir / "traffic_light.yaml")
    st_raw = _load(config_dir / "settings.yaml")

    zones = tuple(
        Zone(
            code=str(z["code"]),
            name_de=str(z["name_de"]),
            name_en=str(z["name_en"]),
            energy_charts=str(z["energy_charts"]),
            alias=str(z["alias"]),
            entsoe=str(z["entsoe"]),
        )
        for z in zones_raw["zones"]
    )
    codes = [z.code for z in zones]
    if len(set(codes)) != len(codes):
        raise ConfigError("Doppelte Zonen-Codes in zones.yaml")
    aliases = [z.alias for z in zones]
    if len(set(aliases)) != len(aliases):
        raise ConfigError("Doppelte Aliase in zones.yaml")
    external = {str(k): str(v) for k, v in (zones_raw.get("external") or {}).items()}

    techs: dict[str, Any] = ef_raw["technologies"]
    factors = {str(k): float(v["factor"]) for k, v in techs.items()}
    sources = {str(k): str(v.get("source", "")) for k, v in techs.items()}
    storage = frozenset(str(k) for k, v in techs.items() if v.get("storage"))
    mapping = ef_raw["mapping"]
    mapping_ec = {str(k): (None if v is None else str(v)) for k, v in mapping["energy_charts"].items()}
    mapping_entsoe = {str(k): (None if v is None else str(v)) for k, v in mapping["entsoe"].items()}
    for name, m in (("energy_charts", mapping_ec), ("entsoe", mapping_entsoe)):
        for src, dst in m.items():
            if dst is not None and dst != CHARGE and dst not in factors:
                raise ConfigError(f"mapping.{name}.{src} -> '{dst}' hat keinen Emissionsfaktor")
    for k, f in factors.items():
        if not 0 <= f <= 1500:
            raise ConfigError(f"Emissionsfaktor {k}={f} außerhalb 0..1500")

    tl = TrafficLight(float(tl_raw["green_below"]), float(tl_raw["red_above"]))
    if not 0 < tl.green_below <= tl.red_above:
        raise ConfigError("traffic_light: 0 < green_below <= red_above verletzt")

    pl = st_raw.get("plausibility", {})
    ec = st_raw.get("energy_charts", {})
    en = st_raw.get("entsoe", {})
    ext = st_raw.get("external_intensity", {})
    return Config(
        zones=zones,
        external_aliases=external,
        factors=factors,
        factor_sources=sources,
        storage_techs=storage,
        mapping_ec=mapping_ec,
        mapping_entsoe=mapping_entsoe,
        traffic_light=tl,
        plausibility=Plausibility(
            float(pl.get("min_value", 0)), float(pl.get("max_value", 1500)),
            float(pl.get("max_missing_share", 0.3)),
        ),
        step_minutes=int(st_raw.get("step_minutes", 15)),
        fetch_window_hours=float(st_raw.get("fetch_window_hours", 8)),
        history_hours=float(st_raw.get("history_hours", 48)),
        max_stale_hours=float(st_raw.get("max_stale_hours", 3)),
        stale_after_hours=float(st_raw.get("stale_after_hours", 4)),
        min_tech_coverage=float(st_raw.get("min_tech_coverage", 0.5)),
        significant_share=float(st_raw.get("significant_share", 0.05)),
        ec_base_url=str(ec.get("base_url", "https://api.energy-charts.info")),
        ec_budget_seconds=float(ec.get("budget_seconds", 540)),
        ec_bootstrap_budget_seconds=float(ec.get("bootstrap_budget_seconds", 1500)),
        entsoe_base_url=str(en.get("base_url", "https://web-api.tp.entsoe.eu/api")),
        entsoe_budget_seconds=float(en.get("budget_seconds", 240)),
        external_intensity={str(k): float(v) for k, v in (ext.get("zones") or {}).items()},
        default_external_intensity=float(ext.get("default", 450)),
    )

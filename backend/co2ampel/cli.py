"""Kommandozeile: ``python -m co2ampel run --out ../public``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_DIR, load_config
from .http import HttpClient
from .output import PlausibilityError
from .pipeline import PreviousState, load_previous_from_dir, load_previous_from_url, run

log = logging.getLogger("co2ampel")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="co2ampel", description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Einen Rechenlauf ausführen")
    p_run.add_argument("--out", type=Path, required=True, help="Zielordner (Pages-Artefakt)")
    src = p_run.add_mutually_exclusive_group()
    src.add_argument("--previous-url", help="Basis-URL der zuletzt veröffentlichten Version")
    src.add_argument("--previous-dir", type=Path, help="Ordner mit der vorherigen Ausgabe")
    p_run.add_argument("--no-fetch", action="store_true", help="Nur Cache nutzen (Tests/Offline)")

    p_val = sub.add_parser("validate", help="Validierungsbericht aus gespeicherten Rohdaten erzeugen")
    p_val.add_argument("--data", type=Path, required=True, help="Ordner mit public_power_<land>.json/cbpf_<land>.json")
    p_val.add_argument("--reference", type=Path, help="JSON mit Referenzwerten (RTE, Energinet)")
    p_val.add_argument("--notes", type=Path, help="Markdown-Datei, die angehängt wird (Einordnung)")
    p_val.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # urllib3 würde auf DEBUG vollständige URLs inkl. Token loggen
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    cfg = load_config(args.config)

    if args.cmd == "run":
        if args.previous_url:
            previous = load_previous_from_url(args.previous_url, cfg.zone_codes, HttpClient(max_attempts=3))
        elif args.previous_dir:
            previous = load_previous_from_dir(args.previous_dir, cfg.zone_codes)
        else:
            previous = PreviousState()
        token = os.environ.get("ENTSOE_API_TOKEN", "").strip() or None
        try:
            res = run(cfg, args.out, previous, entsoe_token=token, fetch=not args.no_fetch)
        except PlausibilityError as exc:
            log.error("Ergebnis unplausibel, nichts geschrieben: %s", exc)
            return 2
        at = next((e for e in res.latest["zones"] if e["zone"] == "AT"), None)
        if at:
            log.info("AT: %s gCO2eq/kWh (%s, %s)", at["consumption"], at["quality"], at["timestamp"])
        return 0

    if args.cmd == "validate":
        from .validation import write_report

        write_report(cfg, args.data, args.out, args.reference, args.notes)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

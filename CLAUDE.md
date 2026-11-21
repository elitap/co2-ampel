# CLAUDE.md – CO2-Ampel

Verbrauchsbasierte CO2-Intensität (gCO2eq/kWh, Lebenszyklus) für europäische Zonen per Flow-Tracing.
Backend rechnet alle 15 min und veröffentlicht JSON auf GitHub Pages. Dazu gibt es eine Android-App mit Widget.
Details und Begründungen stehen in `docs/DECISIONS.md`. Bitte dort nachlesen, bevor die Methodik geändert wird.

## Struktur
- `backend/` – Python ≥ 3.11, Paket `co2ampel`
  - `pipeline.py` – Lauf: Vorstand laden → Abruf → Lückenfüllen → Tracing → Ausgabe
  - `tracing.py` – lineares System (numpy)
  - `gapfill.py` – Lückenregeln
  - `bidding.py` – Gebotszonen, nur mit ENTSO-E-Token
  - `sources/energy_charts.py`, `sources/entsoe.py` – Datenquellen (ENTSO-E per defusedxml)
  - `cache.py` – Rohdaten-Cache für die Rotation
  - `output.py` – Schema-Validierung, Zusammenführen, Plausibilität
  - `validation.py` – erzeugt `docs/VALIDATION.md`
  - `emcompare.py` – Vergleich mit Electricity Maps, nur intern
  - `config/` – YAML-Konfiguration:
    - `zones.yaml` – Zonen und externe Regionen
    - `bidding_zones.yaml` – Gebotszonen
    - `emission_factors.yaml` – Emissionsfaktoren und Technologie-Zuordnung
    - `traffic_light.yaml` – Ampelgrenzen
    - `settings.yaml`
- `android/` – Kotlin, AGP 9.5 (eingebautes Kotlin), Compose, Glance-Widget (klein/mittel), WorkManager, DataStore, OkHttp
- `site/index.html` – Webseite auf Pages: Dropdown, interaktives 48-h-Diagramm, Tabelle. Reines JS ohne Bibliotheken.
- `docs/` – `DECISIONS.md`, `VALIDATION.md`, `schema.json` (validiert alle Ausgabedateien), `validation/`
- `.github/workflows/`:
  - `compute.yml` – Rechnen und Pages-Deploy
  - `ci.yml`
  - `release.yml` – Tag `v*` → signierte APK
  - `keepalive.yml`
  - `em-validation.yml` – nur für die Nacht 21./22.11.2026, deaktiviert sich danach selbst

## Befehle
```
cd backend
python -m pip install --require-hashes --no-deps -r requirements-dev.txt
python -m pytest -q            # ohne Netz; ENTSO-E-Live-Test nur mit ENTSOE_API_TOKEN
python -m ruff check .         # line-length 120
python -m mypy                 # --strict, muss fehlerfrei sein
python -m co2ampel run --out ../public --previous-url https://elitap.github.io/co2-ampel
```
- Android wird nur in CI gebaut, lokal gibt es kein SDK: `./gradlew lintDebug testDebugUnitTest assembleDebug`.
- Lockfiles nach Änderung an `pyproject.toml` neu erzeugen:
  `uv pip compile pyproject.toml [--extra dev] --generate-hashes --python-version 3.12 --python-platform x86_64-unknown-linux-gnu -o requirements[-dev].txt`

## Regeln und Konventionen
- **Keine Daten-Commits.** Historie und Cache werden aus der letzten Pages-Version gelesen und fortgeschrieben.
- **Actions per Commit-SHA pinnen** (mit Versionskommentar):
  - minimale `permissions` pro Job
  - Secrets nur im nötigen Schritt
  - kein `pull_request_target`
- **Signierdaten nie ins Repo.** Der Keystore liegt nur als GitHub Secret (`ANDROID_KEYSTORE_*`) und als lokale Kopie beim Inhaber.
- **Tokens nie loggen oder ausgeben.** Das gilt für `ENTSOE_API_TOKEN` und `ELECTRICITYMAPS_TOKEN`. Electricity-Maps-Daten nicht auf Pages veröffentlichen (Lizenz).
- **Nichts speichern, was nicht angezeigt oder zum Rechnen gebraucht wird:**
  - Historie: rollendes 48-h-Fenster, nur `t`, `consumption` (ganzzahlig) und `quality`
  - Cache: 11 h
- **Robustheit:**
  - Neue Werte ersetzen alte nur bei gleicher oder besserer Qualität.
  - Unplausible Läufe (Werte < 0 oder > 1500, > 30 % Zonen fehlen) enden mit Exit-Code 2. Es wird nichts geschrieben.
- **Texte:** Doku und Logs auf Deutsch, App-Texte auf Deutsch und Englisch (`values`/`values-de`).

## Fallstricke (beobachtet)
- **Energy-Charts:**
  - ca. 2 Anfragen/min pro Endpunkt, deshalb Rotation mit Zeitbudget und `state/cache.json`
  - nur Länder, keine Gebotszonen
  - Daten mit 1–4 h Verzug
  - `public_power` für DK und UA liefert 404, UK-Daten sind unvollständig (GB ist deshalb extern)
  - `cbpf` liefert am aktuellen Rand Platzhalter `0.0` statt `null`; sie werden abgeschnitten
- **AGP 9:**
  - compileSdk 37.2 nötig (`compileSdk { version = release(37) { minorApiLevel = 2 } }`)
  - Unit-Tests gibt es nur für debug (`testDebugUnitTest`)
- **Glance:** `actionStartActivity<T>()` kommt aus `androidx.glance.action`, nicht aus `glance.appwidget.action`.
- **GitHub-Cron** hat anfangs nicht ausgelöst. compute und em-validation haben deshalb einen `next`-Job, der den
  nächsten Lauf per `workflow_dispatch` einplant, solange kein `schedule`-Lauf in den letzten 40 min existiert.
- **Windows-Entwicklung:** `.gitattributes` erzwingt LF. `gradlew` braucht das Ausführungsbit (`git update-index --chmod=+x`).

## Offene Punkte
- **ENTSO-E-Token fehlt noch** (`gh secret set ENTSOE_API_TOKEN`). Ohne Token ist DK `unknown`, und Gebotszonen
  sind inaktiv. Nach dem Setzen den ersten Lauf prüfen: Log „Gebotszonen: aufgeteilt …“, EIC-Codes in `bidding_zones.yaml`.
- **Aktualität:** Messwerte sind 2–4 h alt. Geplant sind:
  1. Hochrechnung der aktuellen Stunde mit Prognosen (`forecast`)
  2. Echtzeitquelle APG für AT
- **Bericht Electricity Maps:** liegt nach 07:00 UTC am 22.11.2026 im letzten `em-validation`-Lauf
  (Job-Zusammenfassung und Artefakt `em-report`).

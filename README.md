# CO2-Ampel

Die CO2-Ampel zeigt, wie klimaschädlich der Strom gerade ist, **der in einer europäischen Zone verbraucht
wird**. Angegeben ist der Wert in gCO₂eq/kWh über den Lebenszyklus, als Ampel grün, gelb oder rot.

- **Backend** (Python, `backend/`): rechnet alle 15 Minuten die verbrauchsbasierte CO2-Intensität für
  35 Zonen per Flow-Tracing und veröffentlicht JSON-Dateien auf GitHub Pages.
- **Android-App** (Kotlin, `android/`): zeigt den Wert als große Ampel mit Verlauf und bietet ein
  Homescreen-Widget in zwei Größen.

**Webseite mit Länderauswahl und Verlauf:** <https://elitap.github.io/co2-ampel/>

**Daten:** <https://elitap.github.io/co2-ampel/latest.json> · Zonen: [`zones.json`](https://elitap.github.io/co2-ampel/zones.json) ·
Verlauf: `history/<ZONE>.json` (z. B. [`history/AT.json`](https://elitap.github.io/co2-ampel/history/AT.json)) ·
Schema: [`docs/schema.json`](docs/schema.json)

## Methodik in Kurzform

1. **Erzeugung je Technologie** und **physikalische Grenzflüsse** aller Länder kommen von Energy-Charts,
   ergänzt durch ENTSO-E, falls ein Token gesetzt ist.
2. Jede Technologie bekommt einen **Lebenszyklus-Emissionsfaktor**: IPCC-AR5-Medianwerte, z. B. Braunkohle
   1100, Steinkohle 820, Gas 490, Solar 48, Wasser 24, Kernkraft 12, Wind 11 g/kWh. Alle Werte und Quellen
   stehen in [`backend/config/emission_factors.yaml`](backend/config/emission_factors.yaml).
3. **Flow-Tracing (proportionale Aufteilung):** Für jeden 15-Minuten-Schritt wird das ganze vernetzte
   europäische Netz in einem linearen Gleichungssystem gelöst. Importierter Strom trägt die Intensität der
   exportierenden Zone, die selbst wieder Importe enthält, bis hin zu Transit und Ringflüssen:

   `c_i · (G_i + Σ_j F_ji) = Σ_k G_ik · e_k + Σ_j F_ji · c_j`

4. **Pumpspeicher:**
   - Laden ist Verbrauch.
   - Entladen zählt mit der Intensität der eigenen Zone.
5. **Andere Netze:**
   - Länder außerhalb des Datenbereichs (z. B. GB, UA, TR) gehen mit fester, konfigurierbarer Intensität ein.
   - Zonen ohne aktuelle Daten gehen mit ihrem letzten bekannten Wert ein.
6. **Qualitätsflag** jedes Werts:

   | Flag | Bedeutung |
   |---|---|
   | `measured` | Ist-Werte |
   | `forecast` | Prognose |
   | `stale` | letzter bekannter Wert (max. 3 h) bzw. Daten älter als 4 h |
   | `estimated` | wesentliche Importe aus Zonen ohne Daten |
   | `unknown` | keine Daten |

Ausführlich: [`docs/DECISIONS.md`](docs/DECISIONS.md). Plausibilitätsprüfung mit echten Daten und Vergleich
mit RTE (Frankreich, r = 0,98): [`docs/VALIDATION.md`](docs/VALIDATION.md).

## Datenquellen und Lizenzen

| Quelle | Nutzung | Lizenz |
|---|---|---|
| [Energy-Charts](https://energy-charts.info) (Fraunhofer ISE), API `api.energy-charts.info` | Erzeugung (`public_power`), Grenzflüsse (`cbpf`) – Primärquelle | **CC BY 4.0**, Namensnennung „energy-charts.info“ |
| [ENTSO-E Transparency Platform](https://transparency.entsoe.eu) | A75, A11, A69, A71 – nur als Lückenfüller, nur mit Token | ENTSO-E Terms and Conditions (Quellenangabe) |
| IPCC AR5 WG III, Annex III (2014); IPCC SRREN (2011) | Emissionsfaktoren | Zitat mit Quellenangabe |
| RTE éCO2mix, Energinet (nur Validierung) | Vergleichswerte in `docs/validation/` | Licence Ouverte 2.0 / Energinet-Bedingungen |

Jede veröffentlichte JSON-Datei enthält ein Feld `attribution`. ENTSO-E wird dort nur genannt, wenn es im
jeweiligen Lauf tatsächlich genutzt wurde.

## App installieren (APK)

1. Auf der [Releases-Seite](https://github.com/elitap/co2-ampel/releases) die neueste
   `co2-ampel-vX.Y.Z.apk` herunterladen. Optional die SHA-256 mit der `.sha256`-Datei vergleichen.
2. Auf dem Android-Gerät (ab Android 8.0) die Installation aus dieser Quelle erlauben, wenn Android danach
   fragt (Browser bzw. Dateimanager → „Unbekannte Apps installieren“).
3. APK öffnen und installieren. Updates mit derselben Signatur lassen sich direkt drüber installieren.
4. Widget: lange auf den Homescreen tippen → Widgets → „CO2-Ampel (klein)“ oder „(mittel)“. Ohne Auswahl
   gilt Österreich. Ein Tipp aufs Widget öffnet die App.

Die App braucht nur Internet (plus Netzwerkstatus für „nur mit Netz aktualisieren“). Sie enthält kein
Tracking und keine Analytics und lädt ausschließlich von `https://elitap.github.io/co2-ampel/`.

## Ampelgrenzen ändern

Die Grenzen stehen in [`backend/config/traffic_light.yaml`](backend/config/traffic_light.yaml):

```yaml
green_below: 150   # grün:  Wert < 150
red_above: 300     # rot:   Wert > 300, dazwischen gelb
```

Nach einem Commit auf `main` gelten die neuen Grenzen ab dem nächsten Rechenlauf. Das Backend schreibt sie in
jede `latest.json` (`thresholds`), App und Widget übernehmen sie von dort, ohne neues APK.

## ENTSO-E-Token nachträglich hinzufügen

1. Ein Konto auf <https://transparency.entsoe.eu> anlegen und per E-Mail an `transparency@entsoe.eu` den
   „Restful API access“ beantragen. Das Token steht danach unter „My Account Settings“.
2. Das Token als Secret hinterlegen (der Befehl fragt es verdeckt ab):

   ```
   gh secret set ENTSOE_API_TOKEN --repo elitap/co2-ampel
   ```

3. Mehr ist nicht nötig. Ab dem nächsten Lauf von `compute` werden Lücken (z. B. Dänemark, verspätete Länder)
   mit ENTSO-E gefüllt, und `attribution` nennt ENTSO-E. Ohne Secret läuft alles nur mit Energy-Charts.
   Lokal: `ENTSOE_API_TOKEN=… python -m pytest` führt zusätzlich den Live-Test aus.

## Lokal ausführen

```
cd backend
python -m pip install --require-hashes --no-deps -r requirements-dev.txt
python -m pytest -q                                   # Tests (ohne Netz)
python -m ruff check . && python -m mypy              # Lint + Typen (strict)
python -m co2ampel run --out ../public --previous-url https://elitap.github.io/co2-ampel
```

Die Android-App wird in der CI gebaut (`ci.yml`: Lint, Unit-Tests, Debug-APK). Ein Tag `v*` erzeugt über
`release.yml` eine signierte Release-APK.

## Automatisierung

| Workflow | Auslöser | Aufgabe |
|---|---|---|
| `compute.yml` | alle 15 min, manuell | rechnen, auf Pages veröffentlichen (keine Daten-Commits) |
| `ci.yml` | Push/PR | ruff, mypy --strict, pytest; Android Lint, Unit-Tests, Build |
| `release.yml` | Tag `v*` | signierte APK, GitHub Release |
| `keepalive.yml` | monatlich | verhindert die Deaktivierung geplanter Workflows nach 60 Tagen ohne Aktivität |

Alle Actions sind per Commit-SHA gepinnt. Dependabot aktualisiert pip, Gradle und Actions wöchentlich.

## Gebotszonen

Mit ENTSO-E-Token werden Norwegen (NO1–NO5), Schweden (SE1–SE4), Dänemark (DK1/DK2) und Italien (7 Zonen)
automatisch in Gebotszonen aufgeteilt (`backend/config/bidding_zones.yaml`). Die Länder bleiben als gewichtetes
Mittel erhalten. Ohne Token wird länderweise gerechnet, weil Energy-Charts nur Länderdaten liefert.

## Speicherung

Es gibt keine Datenbank und keine Daten-Commits. Auf GitHub Pages liegen nur:

- der aktuelle Wert je Zone,
- ein **rollendes 48-h-Fenster** je Zone (Zeit, Verbrauch, Qualität),
- ein Rohdaten-Cache der letzten 11 h.

Jede Veröffentlichung ersetzt die vorige vollständig. Details: `docs/DECISIONS.md`, Abschnitt „Speicherung“.

## Bekannte Grenzen

- **Verzögerung:** Die Quellen veröffentlichen je nach Land mit 1–4 h Verzug, manche Balkanländer mit Tagen.
  Der angezeigte Wert ist der jüngste gemessene, mit Zeitstempel. Ab 4 h Alter steht „veraltet“ dabei.
- **Länder statt Gebotszonen:**
  - Energy-Charts liefert Daten nur je Land. NO, SE, DK und IT sind deshalb je ein Knoten, regionale
    Unterschiede (z. B. Nord- gegenüber Süd-Norwegen) gehen verloren.
  - DE und LU werden getrennt gerechnet.
- **Dänemark** fehlt bei Energy-Charts, die Zone ist ohne ENTSO-E-Token `unknown`. **Großbritannien** und die
  **Ukraine** sind externe Regionen mit fester Intensität.
- **Aggregierte Kopplung:**
  - Gerechnet wird über Netto-Grenzflüsse, ohne Netzverluste und ohne Flüsse innerhalb einer Zone.
  - Die Emissionsfaktoren sind Medianwerte, keine kraftwerksgenauen Werte.
  - Einige Kategorien (Braunkohle, Abfall, Sonstige) beruhen auf dokumentierten Annahmen.
- **Ratenlimit:** Energy-Charts erlaubt ca. 2 Anfragen/min pro Endpunkt. Bei Engpässen werden einzelne Länder
  aus dem Cache des Vorlaufs übernommen (Rotation).
- **GitHub-Cron:** Geplante Läufe können sich unter Last um einige Minuten verzögern.

## Lizenz

Code: MIT. Daten: siehe „Datenquellen und Lizenzen“. Weiterverwendung der JSON-Dateien nur mit Namensnennung
von Energy-Charts (CC BY 4.0) und ggf. ENTSO-E.

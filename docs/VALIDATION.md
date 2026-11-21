# Validierung

Zeitraum: 2026-11-14T00:00:00Z bis 2026-11-21T18:45:00Z (UTC), 748 Zeitschritte à 15 min.
Datenbasis: echte Antworten der Energy-Charts API (`public_power`, `cbpf`) für alle Länder, einmalig
abgerufen und mit `python -m co2ampel validate` durchgerechnet (ohne ENTSO-E-Token).

Werte in gCO2eq/kWh (Lebenszyklus). „Anteil gemessen“ = Anteil der Zeitschritte, in denen die Zone
mit Qualität `measured` berechnet wurde; „berechnet“ = Anteil mit irgendeinem Ergebnis
(inkl. `stale`/`estimated`).

## Kennzahlen pro Zone

| Zone | Verbrauch min / median / max | Produktion min / median / max | Anteil gemessen | berechnet |
|---|---|---|---|---|
| AT | 131 / 253 / 369 | 85 / 168 / 257 | 100% | 100% |
| BA | 426 / 558 / 850 | 464 / 611 / 944 | 91% | 100% |
| BE | 65 / 177 / 363 | 67 / 162 / 354 | 99% | 100% |
| BG | 281 / 440 / 570 | 291 / 453 / 649 | 95% | 96% |
| CH | 42 / 70 / 164 | 45 / 65 / 80 | 99% | 100% |
| CY | 353 / 760 / 834 | 353 / 760 / 834 | 99% | 100% |
| CZ | 456 / 577 / 624 | 463 / 594 / 625 | 99% | 100% |
| DE | 163 / 305 / 441 | 165 / 316 / 489 | 100% | 100% |
| DK | – / – / – | – / – / – | 0% | 0% |
| EE | 172 / 312 / 463 | 304 / 585 / 888 | 99% | 100% |
| ES | 50 / 75 / 208 | 52 / 76 / 225 | 100% | 100% |
| FI | 42 / 73 / 130 | 42 / 73 / 141 | 99% | 100% |
| FR | 24 / 32 / 67 | 24 / 31 / 63 | 99% | 100% |
| GE | 70 / 143 / 230 | 60 / 125 / 151 | 99% | 100% |
| GR | 86 / 238 / 439 | 82 / 234 / 443 | 97% | 100% |
| HR | 126 / 288 / 426 | 104 / 164 / 260 | 99% | 100% |
| HU | 141 / 275 / 326 | 138 / 251 / 325 | 99% | 100% |
| IE | 137 / 275 / 547 | 134 / 300 / 567 | 96% | 100% |
| IT | 143 / 277 / 376 | 154 / 313 / 436 | 92% | 95% |
| LT | 65 / 151 / 352 | 51 / 96 / 305 | 99% | 100% |
| LU | 95 / 194 / 350 | 49 / 87 / 306 | 99% | 100% |
| LV | 116 / 278 / 399 | 43 / 238 / 408 | 99% | 100% |
| MD | 221 / 305 / 410 | 325 / 412 / 468 | 99% | 100% |
| ME | 24 / 359 / 596 | 19 / 411 / 550 | 89% | 91% |
| MK | 261 / 476 / 818 | 407 / 671 / 819 | 64% | 65% |
| NL | 191 / 418 / 515 | 193 / 479 / 562 | 99% | 100% |
| NO | 27 / 39 / 72 | 26 / 28 / 30 | 99% | 100% |
| PL | 366 / 550 / 667 | 366 / 569 / 729 | 99% | 100% |
| PT | 60 / 77 / 136 | 60 / 79 / 147 | 99% | 100% |
| RO | 169 / 258 / 343 | 169 / 234 / 364 | 96% | 100% |
| RS | 245 / 669 / 882 | 150 / 719 / 935 | 84% | 100% |
| SE | 48 / 70 / 106 | 47 / 63 / 92 | 100% | 100% |
| SI | 180 / 301 / 379 | 196 / 301 / 399 | 99% | 100% |
| SK | 116 / 256 / 343 | 82 / 97 / 140 | 97% | 99% |
| XK | 582 / 833 / 1100 | 1100 / 1100 / 1100 | 71% | 100% |

## Plausibilitätsprüfung (bekannte Größenordnungen)

| Zone | Median Verbrauch | Erwartung | Ergebnis | Begründung |
|---|---|---|---|---|
| AT | 253 | 80–300 | ✅ plausibel | Wasserkraft + Gas, im Winter hohe Importe aus DE/CZ |
| DE | 305 | 200–600 | ✅ plausibel | Kohle/Gas-Anteil im November hoch, Wind schwankend |
| FR | 32 | 15–120 | ✅ plausibel | Kernkraft dominiert; Gas-Spitzen im Winter |
| PL | 550 | 500–950 | ✅ plausibel | Kohle dominiert |
| NO | 39 | 10–80 | ✅ plausibel | fast nur Wasserkraft |
| CH | 70 | 20–180 | ✅ plausibel | Kern + Wasser, Winterimporte |

## Vergleich mit offiziellen Landeswerten (Produktionsintensität)

### FR: RTE éCO2mix (eco2mix-national-tr, Feld taux_co2), Licence Ouverte Etalab 2.0

RTE weist direkte Emissionen der französischen Erzeugung aus (ohne Vorketten). Die CO2-Ampel rechnet Lebenszykluswerte (IPCC AR5), daher ist eine positive Abweichung von grob +10 bis +25 g zu erwarten (Kernkraft 12, Wasser 24, Wind 11, Solar 48 g/kWh statt 0).

| Stunden | Mittel CO2-Ampel | Mittel Referenz | mittlere Abweichung | MAE | Korrelation |
|---|---|---|---|---|---|
| 187 | 34 | 21 | +13 | 13 | 0.98 |

### DK: Energinet, Energi Data Service, Datensatz CO2Emis (Mittel DK1/DK2)

Energy-Charts liefert für Dänemark keine Erzeugungsdaten (HTTP 404); ohne ENTSO-E-Token kann die CO2-Ampel für DK nichts berechnen. Referenz-Mittelwert im Zeitraum: 90 g/kWh.

Kein Vergleich möglich (zu wenige überlappende Stunden oder keine eigenen Werte).


## Einordnung

**Gesamtbild.** Die Medianwerte aller sechs geprüften Zonen liegen in den erwarteten Bereichen. Die Reihenfolge
NO < FR < CH < ES/PT < AT < DE < PL entspricht der bekannten Struktur des europäischen Strommixes. Für Frankreich
korreliert die berechnete Produktionsintensität mit den offiziellen RTE-Werten mit r = 0,98. Der mittlere
Versatz von etwa +13 g/kWh ist durch die Methodik erklärt (Lebenszyklus statt direkter Emissionen).

**Wirkung des Flow-Tracings.** Bei Ländern mit hohem Importanteil weicht der Verbrauch deutlich von der
Produktion ab:

- AT: Median-Verbrauch 253 g gegenüber 168 g Produktion, wegen der Winterimporte aus DE und CZ.
- CH: Verbrauch bis 164 g gegenüber höchstens 80 g Produktion.
- EE: Verbrauch 312 g gegenüber 585 g Produktion. Estland importiert viel aus Finnland, und der Ölschiefer
  (1100 g) dominiert nur die eigene Erzeugung.
- LU, LT, SK und HR importieren ebenfalls stark.

Bei Inseln bzw. fast isolierten Zonen sind Verbrauch und Produktion praktisch gleich:

- CY ist nicht vernetzt.
- IE handelt nur mit GB, und GB ist extern.

**Datenlage.** Diese Ergebnisse stammen aus einem Lauf über 7 Tage (alle Daten auf einmal vorhanden). Im
Live-Betrieb kommen die Daten je nach Land mit 1–4 h Verzug, siehe docs/DECISIONS.md.

- **DK:** Energy-Charts liefert für Dänemark keine Erzeugung (HTTP 404). DK ist erst mit ENTSO-E-Token
  berechenbar. Bis dahin gehen DK-Exporte mit 150 g/kWh ein, der Energinet-Mittelwert im Zeitraum lag bei
  ca. 90 g/kWh. Diese Annahme ist für DE, NO, SE und NL konservativ.
- **MK, ME, XK, RS, BA:**
  - MK und ME werden von Energy-Charts unregelmäßig und mit Tagen Verzug aktualisiert: Anteil gemessen 64 %
    bzw. 89 %.
  - XK meldet nur Braunkohle, daher ist die Produktion konstant 1100 g. Die tatsächliche Intensität dürfte
    durch Wasser und Wind etwas niedriger liegen.
- **IT:** einzelne Technologien (Steinkohle, Pumpspeicher) melden zeitweise keine Werte. Die Lückenregel füllt
  sie bis 3 h mit dem letzten Wert.

**Bekannte Grenzen dieser Validierung.**

- Die Erwartungsbereiche sind grobe Größenordnungen und keine Referenzwerte.
- Ein stündlicher Vergleich ist nur für FR möglich. Für DK fehlt die eigene Berechnung (siehe oben).
- Länder mit mehreren Gebotszonen (NO, SE, DK, IT) werden als ein Knoten gerechnet. Unterschiede innerhalb
  eines Landes (z. B. NO1 gegenüber NO4, IT-Nord gegenüber IT-Süd) sind nicht sichtbar.

**Reproduzieren.**

```
cd backend
python -m co2ampel validate --data <ordner mit public_power_<land>.json und cbpf_<land>.json> \
    --reference ../docs/validation/reference.json --notes ../docs/validation/notes.md --out ../docs/VALIDATION.md
```

Die Rohdaten wurden am 2026-11-21 über `/v2/public_power` und `/v2/cbpf` für alle Länder abgerufen
(Zeitraum 2026-11-14T00:00Z bis 2026-11-21T21:00Z). Die Referenzwerte (RTE éCO2mix, Energinet CO2Emis) liegen
in `docs/validation/reference.json`.

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

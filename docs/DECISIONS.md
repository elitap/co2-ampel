# Entscheidungen

Hier steht, was ich ohne Rückfrage entschieden habe, jeweils mit Begründung. Die Reihenfolge folgt etwa dem
Projektverlauf.

## Datenquellen

### D1 – Energy-Charts v2, länderweise
Die Energy-Charts API liefert `public_power` und `cbpf` nur je **Land**, nicht je Gebotszone. Die zulässigen
Werte für `country` sind ch, at, ba, be, … Die Modellzonen sind deshalb Länder:

- Länder mit mehreren Gebotszonen (NO, SE, DK, IT) sind jeweils **ein** Knoten.
- **DE und LU** werden getrennt gerechnet, obwohl sie die Gebotszone DE-LU bilden. Beide Quellen weisen sie
  getrennt aus, das ergibt die feinere Auflösung. In der Validierung steht DE für „DE-LU“.

Ich nutze die `/v2`-Endpunkte (selbstbeschreibende Hülle mit Einheiten, Auflösung und Zeitzone). Daten mit
Stunden- oder Halbstundenauflösung (CH, BE, PT, IE, Balkan …) werden auf 15-min-Schritte verteilt: Der Wert
gilt für alle Viertelstunden des Intervalls.

### D2 – Ratenlimit und Rotation
Energy-Charts begrenzt auf ca. **2 Anfragen/min pro Endpunkt und IP** (Burst 4–5, bei 429 mit `Retry-After`).
35 Länder × 2 Endpunkte passen nicht sicher in einen 15-min-Takt. Deshalb:

- Pro Lauf und Endpunkt gilt ein Zeitbudget (`energy_charts.budget_seconds`, 9 min). Beide Endpunkte laufen
  parallel, weil die Limits je Endpunkt gelten.
- Zuerst werden Länder abgefragt, die noch nie oder am längsten nicht abgefragt wurden (Rotation). Die
  übrigen kommen aus einem **Rohdaten-Cache** (`state/cache.json`). Er wird zusammen mit den Ergebnissen auf
  Pages veröffentlicht und im nächsten Lauf wieder gelesen, ohne Daten-Commits.
- Der erste Lauf ohne Cache hat ein größeres Budget (25 min), damit alle Länder einmal geladen werden.
- Länder mit HTTP 404 (DK, UA) werden höchstens alle 6 h erneut versucht.
- Pro Lauf wird jede Kombination aus Quelle, Datentyp und Land **höchstens einmal** abgefragt (per Test
  abgesichert). Das ist meine Auslegung von „jede Quelle höchstens einmal pro Datentyp“, denn Energy-Charts
  kennt keine Abfrage für alle Länder auf einmal.
- Ich umgehe die Limits nicht, etwa über mehrere Runner-IPs.

In der Praxis waren die Limits beim Bau großzügiger: Ein Lauf schaffte alle 70 Anfragen in etwa 6–12 min.

### D3 – Fehlende oder unvollständige Länder bei Energy-Charts
- **DK**: `public_power` liefert 404. DK bleibt eine Zone, ist ohne ENTSO-E-Token aber `unknown`. Seine
  Exporte gehen mit dem letzten bekannten Wert ein, ohne Historie mit 150 g/kWh (`external_intensity.DK`).
- **GB**: `uk` liefert nur Öl, Gas, Wind an Land und „Others“, also keine Kernkraft, Offshore-Wind oder Solar.
  Die Werte wären grob falsch, und ENTSO-E hat seit dem Brexit keine GB-Daten mehr. GB ist deshalb eine
  **externe Region** mit 150 g/kWh.
- **UA**: kein `public_power` (404), daher extern mit 300 g/kWh.
- **Weitere externe Regionen** (AL, TR, RU, MT, AM, AZ, BY) kommen nur als Nachbarn vor und haben feste,
  konfigurierbare Intensitäten (`settings.yaml`). Die Werte sind grobe Jahresmittel-Größenordnungen.
- **GE** (Georgien) ist nur mit externen Regionen verbunden und wird trotzdem als Zone geführt, weil
  Energy-Charts Daten liefert.

### D4 – Platzhalter-Nullen in `cbpf`
Am aktuellen Rand liefert `cbpf` für noch nicht veröffentlichte Grenzen `0.0` statt `null`. Beobachtet am
21.11.: DE zeigte zu allen Nachbarn außer BE genau 0. Eine abschließende Folge exakter Nullen gilt deshalb als
„noch nicht verfügbar“. Ausnahme: Die ganze Reihe ist 0, dann ist die Leitung tatsächlich außer Betrieb. Eine
neue Antwort ersetzt außerdem ihr ganzes Zeitfenster im Cache, damit Revisionen und entfernte Platzhalter
übernommen werden.

### D5 – ENTSO-E als Lückenfüller
- ENTSO-E wird nur abgefragt, wenn `ENTSOE_API_TOKEN` gesetzt ist, und nur für Lücken:
  - **A75** für Zonen, deren Energy-Charts-Erzeugung fehlt oder älter als 3 h ist.
  - **A69/A71** nur, wenn auch A75 nichts Aktuelles liefert.
  - **A11** nur für Grenzen ohne aktuelle Energy-Charts-Flüsse.
- Ich parse das XML selbst mit `defusedxml` statt mit `entsoe-py`. Das ist kleiner (keine pandas-Abhängigkeit)
  und schützt vor XXE und Entity-Expansion. Namensräume werden ignoriert, curveType A01 und A03 werden
  unterstützt, „keine Daten“-Acknowledgements gelten als leer.
- Die Fixtures sind nach den Beispielen der offiziellen Doku nachgebaut, weil noch kein Token vorhanden war.
  Ein Live-Test (`test_live_actual_generation_at`) läuft automatisch, sobald ein Token in der Umgebung ist.
- Das Token wird nie geloggt. Logzeilen nutzen eine URL ohne Token, und das DEBUG-Logging von urllib3 ist
  abgeschaltet.

## Methodik

### M1 – Flow-Tracing
Proportional Sharing über **Netto**-Grenzflüsse, ein lineares System für das ganze Netz pro Zeitschritt:

    c_i · (G_i + Σ_j F_ji) = Σ_k G_ik · e_k + Σ_j F_ji · c_j      (F_ji = positiver Nettoimport aus j nach i)

Lösung mit `numpy.linalg.solve`. Vorher wird die Kondition geprüft (cond ≤ 1e12), danach das Residuum. Jede
Lösung muss in der konvexen Hülle der Emissionsfaktoren und festen Quellen liegen, sonst gilt sie als Fehler.

- **Netto-Fluss je Grenze**: Energy-Charts meldet jede Grenze aus beiden Länderperspektiven. Sind beide
  vorhanden, wird gemittelt.
- **Speicher**:
  - Pumpspeicher- und Batterie-**Entladung** zählt als Erzeugung mit der Intensität der **eigenen** Zone und
    kürzt sich in der Gleichung heraus.
  - **Laden** ist Verbrauch der Zone und taucht im System nicht auf. Die Verbrauchsintensität gilt für den
    gesamten Zonenverbrauch, also auch für den Ladestrom.
  - Die **Produktionsintensität** rechnet ohne Speicherentladung.
- **Zonen ohne Erzeugung und ohne Importe** würden die Matrix singulär machen. Sie werden in diesem Schritt
  als unbekannt behandelt.
- **Unbekannte Zonen** (keine Daten ≤ 3 h) sind feste Quellen mit ihrem letzten bekannten Verbrauchswert aus
  der 48-h-Historie, ersatzweise mit `external_intensity`.
- **Mischkategorien**: „Others“ zählt mit 700 g als überwiegend fossil, „Other renewables“ mit 38 g.

### M2 – Emissionsfaktoren
- Quelle sind die IPCC-AR5-Medianwerte (WG III, Annex III, Tab. A.III.2), für Öl IPCC SRREN 2011.
- Kategorien ohne IPCC-Wert sind als **Annahme** markiert, jeweils mit Begründung in
  `backend/config/emission_factors.yaml`: Braunkohle, Ölschiefer und Torf 1100; Abfall 580; Kuppelgas 820;
  Sonstige 700.
- **electricitymaps-contrib** habe ich geprüft und nicht übernommen: Das Repository steht unter **AGPL-3.0**,
  eine Übernahme hätte Copyleft-Pflichten für dieses Projekt ausgelöst.
- Jede Technologie-ID beider Quellen ist eindeutig zugeordnet (Energy-Charts-IDs und ENTSO-E B01–B20, B25).
  Unbekannte Serien werden mit Warnung ignoriert und nicht geraten.

### M3 – Lückenregeln und Qualitätsflags
Je Zone, Technologie und Zeitschritt gilt diese Reihenfolge:

1. Ist-Wert Energy-Charts → `measured`
2. Ist-Wert ENTSO-E → `measured`
3. Prognose (A69 Wind/Solar; A71-Summe, verteilt auf den letzten bekannten Mix) → `forecast`
4. letzter Ist-Wert ≤ 3 h → `stale`
5. sonst fehlt der Wert

Eine Zone ist vorhanden, wenn mindestens 50 % ihrer aktiven Technologien belegt sind, sonst ist sie `unknown`.

Wie das Flag einer Zone zustande kommt:

- **Eigene Werte**: Sie erhält das schlechteste Flag unter den Technologien mit ≥ 5 % Anteil. Eine fehlende
  Kleinstquelle verschlechtert das Flag also nicht.
- **Importe aus unbekannten Zonen** mit ≥ 5 % Anteil an der Versorgung führen zu `estimated`.
- **Lückengefüllte Flüsse** zählen erst ab 25 % Anteil. Sonst wäre wegen der unterschiedlichen
  Veröffentlichungsverzüge fast jede Zone `stale`.
- **Alter in `latest.json`**: Werte älter als 4 h (`stale_after_hours`) werden als `stale` markiert, die App
  zeigt dann „veraltet“. Die 3-h-Regel gilt für das Lückenfüllen, die 4-h-Grenze für die Anzeige.
  Energy-Charts veröffentlicht je nach Land mit 1–4 h Verzug, bei 3 h wären ständig rund 40 % der Zonen
  „veraltet“.

### M4 – „Aktueller Wert“ je Zone
Jeder Lauf rechnet die letzten 8 h neu, weil Daten nachträglich eintreffen. Pro Zone wird der **jüngste
Zeitschritt mit Qualität `measured` oder `forecast`** veröffentlicht, sonst der jüngste überhaupt. Deshalb
tragen die Zonen in `latest.json` unterschiedliche Zeitstempel. Das ist ehrlicher als ein gemeinsamer Zeitpunkt,
zu dem die Hälfte der Zonen lückengefüllt wäre.

### M5 – Robustheit
- **Netzwerk**: Timeouts von 10 s (Verbindung) und 60 s (Lesen). Bis zu 5 Versuche mit exponentiellem
  Backoff, bei 429 und 5xx gilt `Retry-After`.
- **Nie schlechter als vorher**: Die Historie übernimmt neue Werte nur bei gleicher oder besserer Qualität.
  In `latest.json` wird ein Eintrag nie durch einen älteren oder (bei gleichem Zeitstempel) schlechteren
  ersetzt. Bei einem Totalausfall bleibt der vorige Stand erhalten (Test `test_outage_never_makes_latest_worse`).
- **Plausibilität**: Werte < 0 oder > 1500, oder mehr als 30 % Zonen ohne Ergebnis, führen zu Exit-Code 2.
  Es wird nichts geschrieben, der Workflow schlägt sichtbar fehl, das Deployment entfällt, und die alte
  Pages-Version bleibt online.
- **Schreiben**: Alle Dateien werden vor dem Schreiben gegen `docs/schema.json` validiert und atomar
  geschrieben, `latest.json` zuletzt.

## Automatisierung

### A1 – Veröffentlichung ohne Daten-Commits
`compute.yml` liest die zuletzt veröffentlichte Version von `https://elitap.github.io/co2-ampel/` (mit
Cache-Busting), schreibt Historie und Cache fort und veröffentlicht über `upload-pages-artifact` und
`deploy-pages`. Mit `concurrency: compute` laufen keine zwei Rechenläufe gleichzeitig. GitHub behält dabei
höchstens einen wartenden Lauf, weitere werden als „cancelled“ verworfen. Bei 15-min-Cron und Laufzeiten bis
ca. 10 min ist das selten.

### A2 – Sicherheit der Workflows
- Alle Actions sind per Commit-SHA gepinnt (mit Versionskommentar für Dependabot).
- `permissions: {}` gilt auf Workflow-Ebene, minimale Rechte werden pro Job vergeben.
- Es gibt kein `pull_request_target`. Secrets stehen nur im jeweiligen Schritt als `env`.
- Checkout läuft mit `persist-credentials: false`, außer im Keepalive, der pushen muss.
- Python-Abhängigkeiten sind mit Hash gepinnt (`requirements*.txt`, erzeugt mit `uv pip compile --generate-hashes`).
- Der Gradle-Wrapper wurde gegen die offizielle SHA-256 geprüft, die Distribution ist per
  `distributionSha256Sum` gepinnt, und `setup-gradle` validiert den Wrapper.

### A3 – 60-Tage-Deaktivierung
`keepalive.yml` läuft monatlich:

1. Ein leerer Commit, falls seit 30 Tagen nichts committet wurde. Das zählt als Repo-Aktivität, und Commits
   mit `GITHUB_TOKEN` lösen keine weiteren Workflows aus.
2. `gh workflow enable compute.yml` als zusätzliche Absicherung (Recht `actions: write`).

Beides geht mit den vorhandenen Rechten. Ist ein Branch-Schutz mit Pflicht-PRs aktiv, schlägt Schritt 1 fehl,
Schritt 2 wirkt trotzdem.

## Android

### X1 – Toolchain
Stand November 2026:

- AGP 9.5.2 (mit eingebautem Kotlin, ohne `kotlin-android`-Plugin), Kotlin 2.4.21, Gradle 9.9.2
- compileSdk 37.2 (Compose 1.13 verlangt mindestens 37.1), targetSdk 37, minSdk 26
- Compose BOM 2026.11.01, Glance 1.2.0, WorkManager 2.12.0, DataStore 1.3.0, OkHttp 5.5.1,
  kotlinx.serialization 1.13.0

Es gibt keine Navigation-Bibliothek und keine Material-Icons-Bibliothek (eigene Vektor-Icons), um die
Abhängigkeiten klein zu halten.

### X2 – Berechtigungen
Die App nutzt `INTERNET` und `ACCESS_NETWORK_STATE`; Letzteres braucht WorkManager für die Bedingung „nur mit
Netz“. WorkManager bringt außerdem `RECEIVE_BOOT_COMPLETED`, `WAKE_LOCK` und `FOREGROUND_SERVICE` mit. Diese
werden per `tools:node="remove"` entfernt. Nach einem Neustart plant das Widget-Update (`updatePeriodMillis`
30 min) die periodische Arbeit neu, beim App-Start passiert das ohnehin.

### X3 – Widget
Es gibt zwei getrennte Widget-Provider, klein und mittel, damit beide in der Widget-Auswahl erscheinen. Die
Konfiguration ist optional (`configuration_optional|reconfigurable`): Ohne Auswahl gilt AT, später lässt sich
die Zone ändern.

„Veraltet“ wird angezeigt, wenn der Wert älter als 4 h ist, wenn er als `stale` oder `unknown` markiert ist
oder wenn der letzte erfolgreiche Abruf länger als 45 min zurückliegt (kein Netz).

### X4 – Signierung
- Der Keystore wurde lokal mit `keytool` erzeugt: PKCS12, RSA 4096, 10000 Tage, Passwort mit 40 Zeichen aus
  `secrets`. Dafür lag ein portables Temurin-JDK im Temp-Ordner, nichts wurde installiert.
- Die Signierdaten liegen nur als GitHub Secrets vor (`ANDROID_KEYSTORE_BASE64`, `…_PASSWORD`, `…_KEY_ALIAS`,
  `…_KEY_PASSWORD`). Eine Kopie liegt lokal beim Repo-Inhaber außerhalb des Repos, nicht im Repo.
- `release.yml` dekodiert den Keystore nur im Build-Schritt in `$RUNNER_TEMP`, löscht ihn danach und prüft die
  Signatur mit `apksigner verify`.

## Gebotszonen (ab ENTSO-E-Token)

### G1 – Aufteilung von NO, SE, DK und IT
Energy-Charts kennt nur Länder, ENTSO-E liefert Erzeugung (A75) und Flüsse (A11) je Gebotszone. Mit Token
werden deshalb vier Länder aufgeteilt: NO in NO1–NO5, SE in SE1–SE4, DK in DK1/DK2 und IT in NORD, CNOR,
CSUD, SUD, CALA, SICI, SARD. Konfiguriert ist das in `backend/config/bidding_zones.yaml`, mit EIC-Codes,
internen Grenzen und Grenzen zu Nachbarn.

- **Bedingung je Land und Lauf**: Alle Gebotszonen des Landes müssen A75-Ist-Werte haben, die höchstens 3 h
  alt sind. Sonst bleibt das Land für diesen Lauf ein Knoten mit Energy-Charts-Daten. Es wird also nie mit
  halben Daten aufgeteilt.
- **Flüsse**: A11 je Gebotszonen-Grenze. Besteht eine Ländergrenze aus genau einer Gebotszonen-Grenze
  (z. B. NO–DE nur über NO2, IT–AT nur über NORD), wird zusätzlich der Energy-Charts-Länderfluss dieser
  Grenze zugeordnet. Das ist wichtig für Grenzen zu externen Regionen wie NO2–GB.
- **An Grenzen zu Deutschland** wird der EIC der Gebotszone DE-LU verwendet (Feld `bzn` in `zones.yaml`).
- **Ausgabe**:
  - Die Gebotszonen erscheinen zusätzlich, z. B. `NO-NO1`, in `zones.json` mit `parent: "NO"`.
  - Das Land wird weiter ausgegeben, als verbrauchsgewichtetes Mittel seiner Gebotszonen: Σ cᵢ·Lᵢ / Σ Lᵢ mit
    Lᵢ = Erzeugung + Importe − Exporte. Die Produktion des Landes ist Σ Emissionen / Σ Erzeugung.
  - App und Widget mit „NO“ funktionieren deshalb unverändert.
- **Abfragen**: ca. 18 × A75 und 2 × ~45 × A11 je Lauf, eigenes Zeitbudget (`split_budget_seconds`). ENTSO-E
  erlaubt 400 Anfragen pro Minute.
- **Ohne Token** ändert sich nichts.
- **Getestet**: Ohne echtes Token bisher nur mit generierten ENTSO-E-Dokumenten (`tests/test_bidding.py`).
  Die EIC-Codes und Grenzen sollten nach dem Setzen des Tokens am ersten echten Lauf geprüft werden. Im Log
  steht „Gebotszonen: aufgeteilt …“.

## Speicherung

Es gibt keine Datenbank und keine Daten-Commits. Gespeichert wird nur, was angezeigt oder zum Rechnen
gebraucht wird. Jede Pages-Veröffentlichung ersetzt die vorige vollständig, es sammelt sich also nichts an.

| Was | Wo | Umfang | Warum |
|---|---|---|---|
| `latest.json` | GitHub Pages | ein Eintrag je Zone (~6 KB) | App, Widget, Webseite |
| `history/<zone>.json` | GitHub Pages | **rollendes 48-h-Fenster**: nur Zeit, Verbrauch (ganzzahlig), Qualität; ~5 KB je Zone | Diagramm |
| `zones.json`, `schema.json`, `index.html` | GitHub Pages | klein | Zonenauswahl, Doku |
| `state/cache.json` | GitHub Pages | Energy-Charts-Rohdaten der letzten 11 h (~80 KB) | Rotation wegen Ratenlimit (D2) |
| Pages-Artefakt | GitHub Actions | 1 Tag Aufbewahrung | nur für das Deployment |
| CI-Berichte, Validierung | GitHub Actions | 2–7 Tage | Fehlersuche |
| App-Cache | Gerät (`filesDir/data`) | letzte `latest.json`, `zones.json`, Verlauf **nur der gewählten Zone** | Offline-Anzeige, Widget |

Die Produktionsintensität steht nur in `latest.json` (aktueller Wert) und nicht in der Historie, weil kein
Diagramm sie zeigt.

## Aktualität

### F1 – ENTSO-E als frischere Ist-Quelle
Energy-Charts übernimmt die Netzbetreiber-Daten mit 2–4 h Verzug, ENTSO-E hat sie oft nach ~1 h. Mit Token
werden ENTSO-E-Ist-Werte (A75, A11) deshalb schon abgefragt, wenn die Energy-Charts-Daten einer Zone oder
Grenze älter als 1 h sind (`entsoe.fill_if_older_than_hours`). Im Lückenfüllen hat Energy-Charts Vorrang,
ENTSO-E belegt den jüngeren Rand. Prognosen (A69/A71) kommen erst bei einer echten Lücke > 3 h dazu.

### F2 – APG (Österreich), standardmäßig aus
Die APG-Transparenzplattform (`/api/v1/AGPT/Data/English/PT15M/<Tag>/<Tag+1>`) liefert die Erzeugung je
Produktionstyp für AT mit ca. **1 h Verzug**. Am 21.11. um 22:52 UTC reichte sie bis 22:00 UTC, Energy-Charts
nur bis 18:00 UTC. Die Werte sind identisch mit Energy-Charts, das sie später übernimmt.

**Technik**:
- Spalten sind ENTSO-E-PSR-Typen, B10 ist netto (negativ = Laden).
- Abgefragt wird ein Tag in Ortszeit Wien, 1–2 Anfragen pro Lauf.
- Die Zeitstempel werden aus dem Tagesbeginn und dem Zeilenindex berechnet, damit Tage mit Zeitumstellung
  (92 bzw. 100 Zeilen) stimmen.

**Lizenz**: APG nennt **keine Lizenz** für die Weiterverwendung. Die allgemeinen Nutzungsbedingungen von
apg.at behalten alle Rechte vor und verlangen für die Nutzung eine vorherige schriftliche Zustimmung. Ob das
für Markttransparenzdaten gilt, ist unklar. Daher gilt:
- Die Anbindung ist fertig und getestet, aber mit `apg.enabled: false` **abgeschaltet**.
- Die Tests nutzen synthetische Antworten im APG-Format, damit keine APG-Daten im öffentlichen Repo liegen.
- Einschalten erst nach schriftlicher Zustimmung von APG (marktinformation@apg.at). Ist sie erteilt, nennt
  `attribution` APG automatisch.
- Rechtlich unproblematische Alternative: dieselben Daten über ENTSO-E (F1). APG meldet sie dort nach
  VO (EU) 543/2013.
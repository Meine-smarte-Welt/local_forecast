# Lokale Wetterprognose

Eine Home-Assistant-Integration, die aus den Sensoren deiner eigenen
Wetterstation eine echte **`weather`-Entity** erzeugt — ohne Cloud, ohne
API-Schlüssel, ohne Internetverbindung.

Der Unterschied zu den vorhandenen Zambretti-Projekten: hier entsteht keine
Sammlung von Textsensoren, sondern eine vollwertige Wetter-Entity. Damit
funktionieren die Standard-Wetterkarte, die Zustandssymbole und alle
Automatisierungen, die auf `weather.*` reagieren.

## Inhaltsverzeichnis

- [Was du brauchst](#was-du-brauchst)
- [Installation](#installation)
- [Einrichtung](#einrichtung)
- [Wie es funktioniert](#wie-es-funktioniert)
- [Bewölkung aus dem Lichtsensor](#bewölkung-aus-dem-lichtsensor)
- [Warum stündlich, und warum sechs Einträge](#warum-stündlich-und-warum-sechs-einträge)
- [Zuordnungstabelle](#zuordnungstabelle)
- [Dashboard-Karte](#dashboard-karte)
- [Attribute](#attribute)
- [Optionen](#optionen)
- [Bekannte Einschränkungen](#bekannte-einschränkungen)
- [Herkunft des Verfahrens](#herkunft-des-verfahrens)
- [Stand der Prüfung](#stand-der-prüfung)

## Was du brauchst

| Messgröße | Pflicht | Bemerkung |
|---|---|---|
| Luftdruck | ja | **relativer** (auf Meereshöhe reduzierter) Druck |
| Außentemperatur | ja | für Frosterkennung und Druckreduktion |
| Windrichtung | nein | verbessert das Ergebnis deutlich |
| Luftfeuchte | nein | nur zur Anzeige |
| Windgeschwindigkeit | nein | nur zur Anzeige |
| Regenrate | nein | lässt bei echtem Regen die Messung gewinnen |
| Sonneneinstrahlung | nein | **stark empfohlen** — macht den aktuellen Zustand zur Messung |

### Hinweis für Ecowitt-Besitzer

Der Luftdruck kommt **nicht** vom Außensensor. Weder der WS90 (7-in-1,
Wittboy) noch der WS69 hat ein Barometer — der sitzt im Gateway bzw. in der
Konsole. Beim GW2000 heißt die passende Entität in Home Assistant meist
„Relativer Luftdruck" (`..._relative_pressure`).

Wähle diese, **nicht** den absoluten Druck. Der relative Druck ist bereits auf
Meereshöhe reduziert; genau den erwartet das Verfahren. Voraussetzung: du hast
im Gateway deine Höhe über NN korrekt hinterlegt. Ist das nicht der Fall, sind
alle Prognosen systematisch verschoben.

Falls du bewusst den absoluten Druck verwenden willst, gibt es im
Einrichtungsdialog einen Schalter dafür — die Reduktion übernimmt dann diese
Integration anhand der Höhe aus den Optionen.

## Installation

### Über HACS

1. HACS → Integrationen → Menü (drei Punkte) → Benutzerdefinierte Repositories
2. URL `https://github.com/Meine-smarte-Welt/local_forecast`, Kategorie *Integration*
3. Installieren, Home Assistant neu starten

### Manuell

Den Ordner `custom_components/local_forecast` in dein
Konfigurationsverzeichnis kopieren und Home Assistant neu starten.

## Einrichtung

Einstellungen → Geräte & Dienste → Integration hinzufügen → **Lokale
Wetterprognose**. Anschließend die Sensoren auswählen.

Die Integration prüft beim Anlegen, ob der gewählte Drucksensor überhaupt einen
Zahlenwert liefert, und meldet sich später mit einer klaren Fehlermeldung, falls
der Druck außerhalb von 870–1085 hPa liegt — das ist praktisch immer ein Zeichen
dafür, dass versehentlich der absolute Druck gewählt wurde.

## Wie es funktioniert

1. Alle paar Minuten (einstellbar) wird der Luftdruck gelesen und in einer
   gleitenden Historie über das Trendfenster (Standard 3 Stunden) abgelegt.
2. Beim Start wird diese Historie **einmalig aus dem Recorder vorgefüllt**.
   Dadurch liefert die Integration sofort nach einem Neustart eine Prognose und
   nicht erst nach drei Stunden. Ist der Recorder deaktiviert oder der Sensor
   nicht aufgezeichnet, baut sich die Historie eben live auf — kein Fehler.
3. Aus der Historie wird die Drucktendenz in hPa pro Stunde als Steigung einer
   **Ausgleichsgeraden** bestimmt. Das ist gegen einzelne Ausreißer und gegen
   ungleichmäßige Messabstände deutlich robuster als ein simpler Vergleich von
   erstem und letztem Wert.
4. Druck, Tendenz, Windrichtung und Monat gehen in das Zambretti-Verfahren, das
   einen Buchstaben A–Z liefert.
5. Der Buchstabe wird in einen Home-Assistant-Wetterzustand übersetzt.

### Woher der angezeigte Zustand kommt

Rangfolge von hart nach weich. Welche Quelle gegriffen hat, steht im Attribut
`condition_source`:

1. **Regenmessung.** Regnet es messbar, gewinnt sie. Keine Rechnung darf
   „sonnig" behaupten, während der Regenmesser läuft. Ab 4 mm/h `pouring`,
   unter 1 °C `snowy`.
2. **Strahlungsmessung** (seit 0.3.0, siehe unten). Auch das ist eine Messung.
3. **Zambretti-Ausblick.** Nur noch Rückfall für die Nacht und für
   Einrichtungen ohne Strahlungssensor.

Bei `sunny` nach Sonnenuntergang wird auf `clear-night` gewechselt. Home
Assistant macht das **nicht** von selbst — im Core existiert die Konstante,
aber keine automatische Umsetzung.

## Bewölkung aus dem Lichtsensor

Bis Version 0.2.0 hatte diese Integration eine Schwäche, die niemandem auffiel:
Der als „jetzt" angezeigte Zustand war in Wahrheit eine **Vorhersage** für die
kommenden Stunden. Seit 0.3.0 wird er bei Tageslicht gemessen.

Der Gedanke: aus der Astronomie ist bekannt, wie viel Strahlung bei
wolkenlosem Himmel ankommen müsste. Was der Sensor davon tatsächlich misst,
verrät, wie stark die Sonne verdeckt ist.

1. **Sonnenstand** — vereinfachtes NOAA-Verfahren.
2. **Klarhimmelstrahlung** — Modell nach Haurwitz (1945).
3. **Klarheitsindex** — Messung geteilt durch Erwartung. Der Trübungsgrad ist
   sein Kehrwert und landet im Feld `cloud_coverage`.

### Was der Wert wirklich bedeutet

Ein einzelner Strahlungssensor misst **nicht den Bedeckungsgrad des Himmels**,
sondern die **Verdunkelung der Sonne**. Das ist etwas anderes. Eine dicke Wolke
genau vor der Sonne bei sonst blauem Himmel ergibt einen hohen Wert. Der Name
`cloud_coverage` ist übernommen, weil Home Assistant kein passenderes Feld
kennt — nicht, weil er genau stimmt.

### Warum nicht Kasten-Czeplak

Die naheliegende Wahl wäre die Beziehung von Kasten und Czeplak (1980) gewesen,
die Bedeckungsgrad in Achteln mit der Strahlungsabschwächung verknüpft. Sie
wurde bewusst verworfen: Sie beschreibt **Mittelwerte** über Stunden oder Tage.
Auf einen Momentanwert angewendet liefert sie unbrauchbare Zahlen — nach ihr
lässt halbe Bedeckung noch 93 % der Klarhimmelstrahlung durch, weil im Mittel
die Sonne meist zwischen den Wolken hindurchscheint. Rückwärts gerechnet käme
man schon bei 99 % der erwarteten Strahlung auf zwei Achtel Bedeckung; jede
kleine Kalibrierungsabweichung des Sensors würde einen wolkenlosen Tag
dauerhaft als „wolkig" ausweisen.

### Nachts wird nichts behauptet

Unterhalb von 5° Sonnenhöhe ist die erwartete Strahlung so klein, dass das
Verhältnis nur noch Rauschen ist. Dann liefert die Rechnung bewusst **kein**
Ergebnis statt eines erfundenen, und der Zambretti-Ausblick übernimmt wieder.
„Keine Aussage möglich" ist etwas anderes als „stockdunkel bewölkt".

### Wenn die Werte nicht passen

In den Optionen steht ein **Abgleich des Klarhimmelmodells**. Meldet die Karte
an einem wolkenlosen Mittag dauerhaft Bewölkung, liest dein Sensor zu niedrig:
Wert unter 1 setzen. Umgekehrt bei „sonnig" unter bedecktem Himmel: über 1.

Wurde die Integration vor 0.3.0 eingerichtet, lässt sich der Strahlungssensor
in den Optionen nachtragen — kein Neuanlegen nötig.

## Warum stündlich, und warum sechs Einträge

Diese Entscheidung wurde in 0.1.1 gegen die ursprüngliche Absicht getroffen und
gehört erklärt.

Fachlich richtig wäre *ein* Prognoseeintrag gewesen — das Verfahren liefert
genau eine Aussage. Genau so war 0.1.0 gebaut. In der Praxis drehte sich damit
in der Wetterkarte dauerhaft der Ladekreis, ohne Fehlermeldung im Protokoll.

Ursache: das Home-Assistant-Frontend stellt eine Prognose erst ab **mehr als
zwei** Einträgen dar. Die Funktion `getForecast()` in
`frontend/src/data/weather.ts` prüft `forecast.length > 2` und gibt sonst
`undefined` zurück — die Anzeige bleibt dann im Ladezustand hängen. Das
Backend arbeitete korrekt und lieferte seinen einen Eintrag aus; er wurde nur
nie gerendert.

Von den drei möglichen Prognosearten passt die stündliche am besten: „gleiche
Erwartung für die nächsten sechs Stunden" ist genau das, was das Verfahren
aussagt. Eine zweimal-tägliche Prognose hätte drei Einträge gebraucht und damit
eine Aussage über *morgen* erfunden, die es nicht gibt.

## Zuordnungstabelle

Das ist die zentrale Übersetzungsentscheidung dieser Integration. Die 26
Zambretti-Texte müssen auf die 15 von Home Assistant unterstützten Zustände
abgebildet werden — dabei geht zwangsläufig Feinheit verloren. Der
Originaltext bleibt deshalb als Attribut erhalten.

| Code | Text | Zustand |
|---|---|---|
| A | Beständig schön | `sunny` |
| B | Schönes Wetter | `sunny` |
| C | Aufheiternd | `partlycloudy` |
| D | Schön, unbeständiger werdend | `partlycloudy` |
| E | Schön, einzelne Schauer möglich | `partlycloudy` |
| F | Recht schön, Besserung | `partlycloudy` |
| G | Recht schön, frühe Schauer möglich | `partlycloudy` |
| H | Recht schön, später Schauer | `partlycloudy` |
| I | Frühe Schauer, Besserung | `rainy` |
| J | Wechselhaft, Besserung | `partlycloudy` |
| K | Recht schön, Schauer wahrscheinlich | `rainy` |
| L | Eher unbeständig, später aufklarend | `cloudy` |
| M | Unbeständig, wahrscheinlich Besserung | `cloudy` |
| N | Schauer, zeitweise aufgelockert | `rainy` |
| O | Schauer, zunehmend unbeständig | `rainy` |
| P | Wechselhaft, etwas Regen | `rainy` |
| Q | Unbeständig, kurze freundliche Abschnitte | `cloudy` |
| R | Unbeständig, später Regen | `cloudy` |
| S | Unbeständig, etwas Regen | `rainy` |
| T | Überwiegend sehr unbeständig | `cloudy` |
| U | Zeitweise Regen, Verschlechterung | `rainy` |
| V | Zeitweise Regen, sehr unbeständig | `rainy` |
| W | Häufige Regenfälle | `rainy` |
| X | Regen, sehr unbeständig | `pouring` |
| Y | Stürmisch, mögliche Besserung | `windy-variant` |
| Z | Stürmisch, viel Regen | `pouring` |

Bei Temperaturen unter 1 °C werden `rainy` → `snowy-rainy` und `pouring` →
`snowy` übersetzt. Das Zambretti-Verfahren selbst kennt keinen Schnee, es sagt
nur Niederschlag voraus.

## Dashboard-Karte

Die Karte wird beim Start automatisch als Frontend-Ressource bereitgestellt —
du musst sie **nicht** von Hand unter Einstellungen → Dashboards → Ressourcen
eintragen. Nach dem Neustart erscheint sie in der Kartenauswahl als
„Lokale Wetterprognose".

```yaml
type: custom:local-forecast-card
entity: weather.lokale_wetterprognose
```

| Option | Standard | Bedeutung |
|---|---|---|
| `entity` | — | Pflicht, muss aus der Domäne `weather` stammen |
| `show_chart` | `true` | Barografen anzeigen |
| `smooth` | `true` | Sensorrauschen in der Kurve glätten |
| `show_forecast` | `true` | Ausblick anzeigen |
| `forecast_style` | `band` | `band` oder `hourly` |
| `hours` | Trendfenster der Integration | Zeitraum des Barografen abweichend festlegen |

**Was die Karte zeigt, das die mitgelieferte nicht kann:** den Druckverlauf,
aus dem die Prognose entsteht. Die durchgezogene Linie ist der echte Verlauf
aus dem Recorder, die gestrichelte Gerade ist die Tendenz, mit der das
Verfahren tatsächlich rechnet. Damit siehst du nicht nur das Ergebnis, sondern
auch seine Eingabe — und erkennst sofort, ob eine überraschende Prognose auf
einem echten Drucksturz beruht oder auf einem Ausreißer.

### Der Ausblick, und warum er als Band dargestellt wird

Die Karte holt die Prognose über dasselbe Abo, das auch die mitgelieferte
Wetterkarte verwendet (`weather/subscribe_forecast`) — sie baut sie nicht aus
dem Zambretti-Text nach. Damit zeigt sie exakt das, was das Backend ausliefert,
inklusive der stündlichen Tag/Nacht-Korrektur.

In der Vorgabe `band` erscheint **ein** Symbol mit dem Zeitraum, für den es
gilt („bis 5:30 Uhr, durchgehend gleiche Erwartung"). Das entspricht dem, was
das Verfahren tatsächlich aussagt: eine Aussage über die kommenden Stunden,
keine sechs unabhängigen Stundenwerte. Sind die Einträge einmal nicht
einheitlich — etwa weil die Sonne dazwischen untergeht — entfällt der Zusatz.

Wer die gewohnte Stundenleiste bevorzugt, setzt `forecast_style: hourly`. Sie
zeigt dann sechs Spalten, die in aller Regel dasselbe Symbol tragen. Das ist
keine Fehlfunktion, sondern die ehrliche Folge daraus, dass dahinter eine
einzige Aussage steht.

**Zur Glättung:** Der Drucksensor löst feiner auf, als das Wetter sich ändert.
Über drei Stunden zappelt der Messwert um wenige Hundertstel hPa hin und her,
was die Kurve zu einem Seismogramm macht, obwohl meteorologisch nichts
passiert. Ein gleitender Median über sechs Werte entfernt genau dieses Zappeln.
Bewusst ein Median und kein Mittelwert: Ein echter Drucksturz bleibt als
Sprung erhalten, statt verschliffen zu werden. **Geglättet wird nur das Bild —
die Prognose rechnet weiterhin auf den Rohdaten.** Wer die Rohwerte sehen will,
setzt `smooth: false`.

Die Fensterbreite ist bewusst *gerade*. Bei ungerader Breite wählt ein Median
schlicht den Mehrheitswert, und ein gleichmäßiges Hin-und-Her zwischen zwei
Werten — genau das typische Sensorzappeln — wandert unverändert mit. Ein
Testfall hält das fest.

Der Barograf braucht den Recorder. Zeichnet dieser den Drucksensor nicht auf,
zeigt die Karte das als Hinweis an, statt leer zu bleiben.

## Attribute

| Attribut | Bedeutung |
|---|---|
| `zambretti_code` | Buchstabe A–Z |
| `zambretti_text` | Prognosetext im Original-Wortlaut |
| `pressure_trend` | verwendete Drucktendenz in hPa/h |
| `sea_level_pressure` | verwendeter Druck auf Meereshöhe |
| `sample_count` | Messwerte im Trendfenster |
| `trend_hours` | eingestelltes Trendfenster in Stunden (für die Karte) |
| `pressure_entity_id` | verwendeter Drucksensor (für die Karte) |
| `clear_sky_index` | Anteil der ankommenden Klarhimmelstrahlung (0–1,3) |
| `condition_source` | `regenmessung`, `strahlungsmessung` oder `prognose` |

Beispiel für eine Automatisierung:

```yaml
trigger:
  - platform: state
    entity_id: weather.lokale_wetterprognose
condition:
  - condition: numeric_state
    entity_id: weather.lokale_wetterprognose
    attribute: pressure_trend
    below: -0.8
action:
  - action: notify.mobile_app
    data:
      message: >-
        Der Luftdruck fällt rasch:
        {{ state_attr('weather.lokale_wetterprognose', 'zambretti_text') }}
```

## Optionen

Änderungen greifen sofort, die Integration lädt sich selbst neu.

| Option | Standard | Bereich |
|---|---|---|
| Sonneneinstrahlung | — | Sensor, nachtragbar |
| Abgleich des Klarhimmelmodells | 1,0 | 0,5–1,5 |
| Trendfenster | 3 h | 1–12 h |
| Aktualisierungstakt | 5 min | 1–60 min |
| Höhe über NN | aus HA-Konfiguration | −500 bis 5000 m |

Das Trendfenster ist der interessanteste Hebel: das Verfahren ist klassisch auf
3 Stunden ausgelegt, bei sehr träger Wetterlage kann ein längeres Fenster
ruhigere Ergebnisse liefern.

## Bekannte Einschränkungen

Diese Punkte sind bewusst so und stehen hier, damit niemand sie erst im Betrieb
entdeckt:

- **Kein Mehrtagesausblick.** Das Verfahren liefert genau *einen* Ausblick auf
  die nächsten etwa 6–12 Stunden. Wer eine Wochenvorschau braucht, ist bei
  Met.no oder DWD richtig — diese Integration ersetzt sie nicht, sondern
  ergänzt sie um eine Einschätzung für den *eigenen* Standort.
- **Die sechs Prognoseeinträge sind identisch.** Sie verteilen eine einzige
  Aussage über ihren Gültigkeitszeitraum und enthalten *keine* eigenständige
  stündliche Auflösung. Mehrere Einträge sind technisch nötig (siehe
  [Warum stündlich](#warum-stündlich-und-warum-sechs-einträge)) — sie
  vortäuschen keine Detailtiefe, die das Verfahren nicht hat.
- **Keine Temperaturprognose.** Das Feld `native_temperature` ist im
  Prognosedatensatz von Home Assistant verpflichtend. Da es kein
  Temperaturmodell gibt, wird dort der *aktuelle* Messwert eingetragen — in
  allen sechs Einträgen derselbe. Wer den Prognoseeintrag auswertet, darf
  diesen Wert nicht als Vorhersage lesen.
- **Nur gemäßigte Breiten.** Die Koeffizienten sind für das nordwesteuropäische
  Wettergeschehen kalibriert. Für Deutschland gut geeignet, in den Tropen oder
  im Hochgebirge unbrauchbar.
- **Schwäche bei schnellen Wetterwechseln.** Das Verfahren unterstellt
  allmähliche Druckänderungen. Rasch ziehende Kaltfronten und Gewitterlagen
  bildet es systematisch schlecht ab.
- **Der relative Druck muss stimmen.** Ist die Höhe im Gateway falsch
  hinterlegt, ist jede Prognose falsch — und zwar ohne dass es auffällt, weil
  die Werte plausibel aussehen.

## Herkunft des Verfahrens

Der Zambretti-Forecaster geht auf einen Rechenschieber von Negretti & Zambra
aus dem frühen 20. Jahrhundert zurück. Die hier verwendeten Koeffizienten und
Nachschlagetabellen sind die in der Literatur und in zahlreichen
Open-Source-Projekten übereinstimmend dokumentierten Werte; als Referenz dienten
die Digitalisierung von beteljuice.com und die Erläuterungen auf
meteormetrics.com.

Der Code in `zambretti.py` ist eine eigenständige Implementierung und wurde
nicht aus einem bestehenden Projekt übernommen. **Offener Punkt:** dem
Repository fehlt noch eine LICENSE-Datei — bitte vor der Veröffentlichung
festlegen (MIT wäre für eine HACS-Integration üblich).

## Stand der Prüfung

Ehrlich, damit klar ist, was getestet wurde und was nicht:

**Geprüft:**

- 61 Testfälle gegen die Rechenlogik, alle grün
  (`python3 -m unittest discover -s tests`). `zambretti.py` importiert bewusst
  nichts aus Home Assistant und ist deshalb vollständig ohne laufende Instanz
  testbar.
- **Der eigene Sonnenstand wurde über ein volles Jahr gegen `astral`
  gegengeprüft** — die Bibliothek, die Home Assistant selbst dafür verwendet.
  Größte Abweichung an Thorstens Standort 0,009°, weltweit (Kapstadt,
  Reykjavík, Singapur) unter 0,011°. Der Vergleich steckt als Testfall im
  Repository und wird übersprungen, wenn `astral` nicht installiert ist.
- 35 Testfälle gegen die Lovelace-Karte, alle grün (`node tests/test_card.js`).
  Geprüft werden unter anderem das deutsche Zahlenformat, die Benennung der
  Tendenzrichtung an ihren Schwellwerten, das Lesen der Kurzform von
  Verlaufsdaten (`s`/`lu`/`lc`), das Überspringen von `unavailable`-Werten,
  dass alle Kurvenpunkte innerhalb der Zeichenfläche bleiben, und dass ein
  ruhiger Druckverlauf nicht zur dramatischen Zickzacklinie überhöht wird.
- Alle verwendeten Home-Assistant-Symbole wurden gegen den echten Quellcode von
  **Home Assistant 2026.7.4** abgeglichen, nicht aus dem Gedächtnis
  geschrieben: `WeatherEntityFeature.FORECAST_TWICE_DAILY`,
  `async_forecast_twice_daily`, `Forecast`, `AddConfigEntryEntitiesCallback`,
  `OptionsFlowWithReload`, `DeviceEntryType`, `_async_abort_entries_match`,
  `history.state_changes_during_period` (Signatur inklusive Parameternamen),
  `recorder.get_instance`, die moderne `filter`-Syntax des `EntitySelector` und
  die vollständige Liste der 15 gültigen Wetterzustände.
- `py_compile` und `pyflakes` sauber, alle JSON-Dateien valide.

**Nicht geprüft:**

- Kein Lauf gegen eine echte Home-Assistant-Installation. Der Einrichtungs- und
  Optionsdialog sowie das Vorfüllen aus dem Recorder sind nur auf Symbolebene
  abgesichert. Das Rendern der Wetterkarte wurde in 0.1.0/0.1.1 an echter
  Hardware getestet — dabei kamen zwei Fehler heraus, siehe Versionshistorie.
- Die Lovelace-Karte wurde gegen DOM-Attrappen getestet, nicht in einem echten
  Browser. Geprüft ist die erzeugte Auszeichnung, nicht ihr Aussehen.

## Versionshistorie

**0.4.0** — Ausblick in der Karte, bezogen über das Prognose-Abo von Home
Assistant. Wahlweise als Band mit Gültigkeitszeitraum (Vorgabe) oder als
Stundenleiste.

**0.3.1** — Barograf glättet Sensorrauschen (gleitender Median, nur für die
Darstellung). Einheitliches Minuszeichen, Tabellenziffern statt Monospace bei
der Druckanzeige.

**0.3.0** — Der aktuelle Zustand wird bei Tageslicht aus der
Sonneneinstrahlung **gemessen** statt aus der Prognose abgeleitet. Neues Feld
`cloud_coverage`, neue Attribute `clear_sky_index` und `condition_source`,
neue Option zum Abgleich des Klarhimmelmodells.

**0.2.0** — Lovelace-Karte mit Barograf. Prognosesymbole werden jetzt je
Stunde auf Tag/Nacht geprüft (vorher strahlten in der Nachtvorschau sechs
Sonnen). Neue Attribute `trend_hours` und `pressure_entity_id`.

**0.1.1** — Umstellung von `twice_daily` auf `hourly` mit sechs Einträgen; die
Karte blieb sonst dauerhaft im Ladezustand. Prognose wird bei jeder
Aktualisierung an Abonnenten geschoben.

**0.1.0** — Erstveröffentlichung.
- Keine Messung gegen echte Wetterdaten. Wie treffsicher die Prognose an deinem
  Standort ist, zeigt erst der Vergleich über mehrere Wochen.

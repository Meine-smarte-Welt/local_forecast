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
- [Zuordnungstabelle](#zuordnungstabelle)
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

Die Entity muss einen aktuellen Zustand haben, das Verfahren liefert aber einen
Ausblick auf die nächsten Stunden. Die Reihenfolge ist deshalb:

1. **Regnet es messbar** (Regenrate > 0), gewinnt die Messung. Eine Prognose
   darf nicht „sonnig" behaupten, während der Regenmesser läuft. Ab 4 mm/h wird
   auf `pouring` gewechselt, unter 1 °C auf `snowy`.
2. Sonst der Zambretti-Ausblick.
3. Bei `sunny` nach Sonnenuntergang wird auf `clear-night` gewechselt. Home
   Assistant macht das **nicht** von selbst — im Core existiert die Konstante,
   aber keine automatische Umsetzung.

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

## Attribute

| Attribut | Bedeutung |
|---|---|
| `zambretti_code` | Buchstabe A–Z |
| `zambretti_text` | Prognosetext im Original-Wortlaut |
| `pressure_trend` | verwendete Drucktendenz in hPa/h |
| `sea_level_pressure` | verwendeter Druck auf Meereshöhe |
| `sample_count` | Messwerte im Trendfenster |

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
  die nächsten etwa 6–12 Stunden. Die Wetterkarte zeigt entsprechend nur einen
  Prognoseeintrag, keine Wochenvorschau. Wer eine Wochenvorschau braucht, ist
  bei Met.no oder DWD richtig — diese Integration ersetzt sie nicht, sondern
  ergänzt sie um eine Einschätzung für den *eigenen* Standort.
- **Keine Temperaturprognose.** Das Feld `native_temperature` ist im
  Prognosedatensatz von Home Assistant verpflichtend. Da es kein
  Temperaturmodell gibt, wird dort der *aktuelle* Messwert eingetragen. Wer den
  Prognoseeintrag auswertet, darf diesen Wert nicht als Vorhersage lesen.
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

- 31 Testfälle gegen `zambretti.py`, alle grün
  (`python3 -m unittest discover -s tests`). `zambretti.py` importiert bewusst
  nichts aus Home Assistant und ist deshalb vollständig ohne laufende Instanz
  testbar.
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
  Optionsdialog, das Vorfüllen aus dem Recorder und das Rendern der Wetterkarte
  sind bislang nur auf Symbolebene abgesichert, nicht im Betrieb beobachtet.
- Keine Messung gegen echte Wetterdaten. Wie treffsicher die Prognose an deinem
  Standort ist, zeigt erst der Vergleich über mehrere Wochen.

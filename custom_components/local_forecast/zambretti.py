"""Reine Rechenlogik der lokalen Wetterprognose (Zambretti-Verfahren).

Dieses Modul importiert bewusst NICHTS aus Home Assistant. Dadurch ist die
gesamte Meteorologie-Logik ohne laufende HA-Instanz testbar - alle Testfaelle
in tests/test_zambretti.py laufen direkt gegen dieses Modul.

Quellen des Verfahrens (siehe README, Abschnitt "Herkunft des Verfahrens"):
Negretti & Zambra Forecaster (frueher 20. Jh.), digitalisiert von beteljuice.com,
zusaetzliche Erlaeuterungen von meteormetrics.com. Die hier verwendeten
Koeffizienten und Nachschlagetabellen sind die in der Literatur und in
zahlreichen Open-Source-Projekten uebereinstimmend dokumentierten Werte.
Der Code selbst ist eine eigenstaendige Implementierung.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Konstanten des Verfahrens
# --------------------------------------------------------------------------

#: Druckkorrektur je 16-Punkt-Windrichtung (Index 0 = Nord, 1 = NNO, ... 15 = NNW).
#: Nordwind wirkt wie ein hoeherer Druck (besseres Wetter), Suedwind wie ein
#: deutlich niedrigerer. Werte in hPa.
WIND_PRESSURE_OFFSETS: tuple[float, ...] = (
    5.2,    # N
    4.2,    # NNO
    3.2,    # NO
    1.05,   # ONO
    -1.1,   # O
    -3.15,  # OSO
    -5.2,   # SO
    -8.35,  # SSO
    -11.5,  # S
    -9.4,   # SSW
    -7.3,   # SW
    -5.25,  # WSW
    -3.2,   # W
    -1.15,  # WNW
    0.9,    # NW
    3.05,   # NNW
)

#: Nachschlagetabellen: Ergebnisindex -> Zambretti-Buchstabe, je Drucktendenz.
LUT_RISING = "ABBCFGIJLMMQTY"
LUT_FALLING = "BDHORUVXXZ"
LUT_STEADY = "ABBBEKNNPPSWWXXXZ"

#: Ab dieser Tendenz (hPa pro Stunde) gilt der Druck als steigend bzw. fallend.
TREND_THRESHOLD_HPA_PER_HOUR = 0.1

#: Jahreszeitliche Korrektur in hPa (Sommer auf der Nordhalbkugel bzw.
#: Winter auf der Suedhalbkugel).
SEASON_OFFSET_HPA = 3.2

#: Die 26 Prognosetexte des Verfahrens, auf Deutsch.
FORECAST_TEXT_DE: dict[str, str] = {
    "A": "Beständig schön",
    "B": "Schönes Wetter",
    "C": "Aufheiternd",
    "D": "Schön, unbeständiger werdend",
    "E": "Schön, einzelne Schauer möglich",
    "F": "Recht schön, Besserung",
    "G": "Recht schön, frühe Schauer möglich",
    "H": "Recht schön, später Schauer",
    "I": "Frühe Schauer, Besserung",
    "J": "Wechselhaft, Besserung",
    "K": "Recht schön, Schauer wahrscheinlich",
    "L": "Eher unbeständig, später aufklarend",
    "M": "Unbeständig, wahrscheinlich Besserung",
    "N": "Schauer, zeitweise aufgelockert",
    "O": "Schauer, zunehmend unbeständig",
    "P": "Wechselhaft, etwas Regen",
    "Q": "Unbeständig, kurze freundliche Abschnitte",
    "R": "Unbeständig, später Regen",
    "S": "Unbeständig, etwas Regen",
    "T": "Überwiegend sehr unbeständig",
    "U": "Zeitweise Regen, Verschlechterung",
    "V": "Zeitweise Regen, sehr unbeständig",
    "W": "Häufige Regenfälle",
    "X": "Regen, sehr unbeständig",
    "Y": "Stürmisch, mögliche Besserung",
    "Z": "Stürmisch, viel Regen",
}

#: Abbildung der 26 Buchstaben auf die von Home Assistant unterstuetzten
#: Wetterzustaende. Das ist die zentrale Uebersetzungsentscheidung dieser
#: Integration - siehe README, Abschnitt "Zuordnungstabelle".
CONDITION_MAP: dict[str, str] = {
    "A": "sunny",
    "B": "sunny",
    "C": "partlycloudy",
    "D": "partlycloudy",
    "E": "partlycloudy",
    "F": "partlycloudy",
    "G": "partlycloudy",
    "H": "partlycloudy",
    "I": "rainy",
    "J": "partlycloudy",
    "K": "rainy",
    "L": "cloudy",
    "M": "cloudy",
    "N": "rainy",
    "O": "rainy",
    "P": "rainy",
    "Q": "cloudy",
    "R": "cloudy",
    "S": "rainy",
    "T": "cloudy",
    "U": "rainy",
    "V": "rainy",
    "W": "rainy",
    "X": "pouring",
    "Y": "windy-variant",
    "Z": "pouring",
}

#: Zustaende, die bei Frost in ihre winterliche Entsprechung uebersetzt werden.
_FROST_REPLACEMENTS = {
    "rainy": "snowy-rainy",
    "pouring": "snowy",
}


@dataclass(frozen=True)
class ZambrettiResult:
    """Ergebnis einer Prognoseberechnung."""

    code: str
    """Zambretti-Buchstabe A-Z."""

    text: str
    """Deutscher Prognosetext."""

    condition: str
    """Home-Assistant-Wetterzustand."""

    trend: float
    """Verwendete Drucktendenz in hPa pro Stunde."""

    sea_level_pressure: float
    """Verwendeter, auf Meereshoehe reduzierter Druck in hPa."""

    wind_index: int | None
    """Verwendeter 16-Punkt-Windrichtungsindex, oder None."""


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------


def to_sea_level(absolute_hpa: float, elevation_m: float, temperature_c: float) -> float:
    """Reduziere einen absoluten Luftdruck auf Meereshoehe.

    Barometrische Hoehenformel mit Temperaturberuecksichtigung. Wird nur
    gebraucht, wenn der Nutzer den ABSOLUTEN Druck des Gateways ausgewaehlt hat;
    der relative Druck des Ecowitt-Gateways ist bereits reduziert.
    """
    if elevation_m == 0:
        return absolute_hpa
    lapse = 0.0065 * elevation_m
    return absolute_hpa / (1.0 - lapse / (temperature_c + lapse + 273.15)) ** 5.257


def bearing_to_index(bearing_deg: float | None) -> int | None:
    """Wandle eine Windrichtung in Grad in einen 16-Punkt-Index (0 = Nord)."""
    if bearing_deg is None:
        return None
    return int((bearing_deg % 360.0) / 22.5 + 0.5) % 16


def pressure_trend(samples: list[tuple[float, float]]) -> float | None:
    """Berechne die Drucktendenz in hPa pro Stunde.

    ``samples`` ist eine Liste aus (Zeitstempel in Sekunden, Druck in hPa).
    Statt einfach ersten und letzten Wert zu vergleichen, wird die Steigung
    einer Ausgleichsgeraden bestimmt - das ist gegen einzelne Ausreisser und
    gegen ungleichmaessige Messabstaende deutlich robuster.

    Gibt ``None`` zurueck, wenn zu wenige Messwerte vorliegen oder alle
    Messwerte denselben Zeitstempel tragen.
    """
    if len(samples) < 2:
        return None

    n = float(len(samples))
    mean_t = sum(t for t, _ in samples) / n
    mean_p = sum(p for _, p in samples) / n

    numerator = sum((t - mean_t) * (p - mean_p) for t, p in samples)
    denominator = sum((t - mean_t) ** 2 for t, _ in samples)
    if denominator == 0:
        return None

    # Steigung pro Sekunde -> pro Stunde
    return (numerator / denominator) * 3600.0


def zambretti_code(
    sea_level_hpa: float,
    month: int,
    wind_index: int | None,
    trend_hpa_per_hour: float,
    northern_hemisphere: bool = True,
) -> str:
    """Ermittle den Zambretti-Buchstaben A-Z.

    ``sea_level_hpa`` muss der auf Meereshoehe reduzierte Druck sein.
    ``month`` ist 1-12, ``wind_index`` ein 16-Punkt-Index oder None.
    """
    pressure = float(sea_level_hpa)

    if wind_index is not None:
        index = wind_index if northern_hemisphere else (wind_index + 8) % 16
        pressure += WIND_PRESSURE_OFFSETS[index]

    # "Sommer" meint hier die warme Jahreshaelfte der jeweiligen Halbkugel.
    is_summer_half_year = 4 <= month <= 9
    season_matches = northern_hemisphere == is_summer_half_year

    if trend_hpa_per_hour >= TREND_THRESHOLD_HPA_PER_HOUR:
        if season_matches:
            pressure += SEASON_OFFSET_HPA
        raw = 0.1740 * (1031.40 - pressure)
        lut = LUT_RISING
    elif trend_hpa_per_hour <= -TREND_THRESHOLD_HPA_PER_HOUR:
        if season_matches:
            pressure -= SEASON_OFFSET_HPA
        raw = 0.1553 * (1029.95 - pressure)
        lut = LUT_FALLING
    else:
        raw = 0.2314 * (1030.81 - pressure)
        lut = LUT_STEADY

    position = min(max(int(raw + 0.5), 0), len(lut) - 1)
    return lut[position]


def condition_for_code(code: str, temperature_c: float | None = None) -> str:
    """Uebersetze einen Zambretti-Buchstaben in einen HA-Wetterzustand.

    Bei Temperaturen unter 1 Grad Celsius werden Regenzustaende in ihre
    winterliche Entsprechung uebersetzt. Das Zambretti-Verfahren selbst kennt
    keinen Schnee - es sagt nur "Niederschlag" voraus.
    """
    condition = CONDITION_MAP[code]
    if temperature_c is not None and temperature_c < 1.0:
        return _FROST_REPLACEMENTS.get(condition, condition)
    return condition


def forecast(
    sea_level_hpa: float,
    month: int,
    trend_hpa_per_hour: float,
    wind_bearing_deg: float | None = None,
    temperature_c: float | None = None,
    northern_hemisphere: bool = True,
) -> ZambrettiResult:
    """Vollstaendige Prognose aus den bereits aufbereiteten Messwerten."""
    wind_index = bearing_to_index(wind_bearing_deg)
    code = zambretti_code(
        sea_level_hpa, month, wind_index, trend_hpa_per_hour, northern_hemisphere
    )
    return ZambrettiResult(
        code=code,
        text=FORECAST_TEXT_DE[code],
        condition=condition_for_code(code, temperature_c),
        trend=trend_hpa_per_hour,
        sea_level_pressure=sea_level_hpa,
        wind_index=wind_index,
    )

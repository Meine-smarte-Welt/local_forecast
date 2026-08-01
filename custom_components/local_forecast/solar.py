"""Bewölkungsgrad aus gemessener Sonneneinstrahlung.

Wie zambretti.py importiert dieses Modul bewusst NICHTS aus Home Assistant und
ist daher vollständig ohne laufende Instanz testbar.

Der Gedanke in einem Satz: man weiß aus der Astronomie, wie viel Strahlung bei
wolkenlosem Himmel ankommen müsste. Was der Sensor davon tatsächlich misst,
verrät, wie viel die Wolken schlucken.

Drei Schritte:

1. Sonnenstand  — vereinfachtes NOAA-Verfahren, Genauigkeit deutlich besser
   als ein Zehntelgrad; für diesen Zweck weit mehr als nötig.
2. Klarhimmel   — Modell nach Haurwitz (1945).
3. Trübung      — wie viel der erwarteten Strahlung fehlt.

Zur dritten Stufe eine bewusste Entscheidung, die Erklärung verdient. Der
naheliegende Weg wäre die Beziehung von Kasten und Czeplak (1980) gewesen, die
Bedeckungsgrad in Achteln und Strahlungsabschwächung verknüpft. Sie wurde hier
verworfen, aus zwei Gründen:

* Sie beschreibt MITTELWERTE über Stunden oder Tage. Auf einen Momentanwert
  angewendet ergibt sie unbrauchbare Zahlen: nach ihr liefert halbe Bedeckung
  noch 93 % der Klarhimmelstrahlung, weil im Mittel die Sonne meist zwischen
  den Wolken hindurchscheint. Umgekehrt gerechnet käme man bei 99 % der
  erwarteten Strahlung bereits auf zwei Achtel Bedeckung — jede kleine
  Kalibrierungsabweichung des Sensors würde einen wolkenlosen Tag dauerhaft
  als "wolkig" ausweisen.
* Ein einzelner Strahlungssensor misst ohnehin nicht den Bedeckungsgrad des
  HIMMELS, sondern die Verdunkelung der SONNE. Das ist etwas anderes, und es
  wäre unredlich, das eine als das andere auszugeben.

Deshalb wird hier direkt der Anteil der fehlenden Strahlung ausgegeben. Der
Wert landet im Feld ``cloud_coverage`` von Home Assistant, weil es dafür kein
passenderes gibt — was er wirklich bedeutet, steht in der README.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

#: Umrechnung Beleuchtungsstärke -> Bestrahlungsstärke für Tageslicht.
#: Ecowitt selbst rechnet mit diesem Faktor zwischen lx und W/m².
LUX_PER_WATT_PER_M2 = 126.7

#: Unterhalb dieser Sonnenhöhe ist die Klarhimmelstrahlung so klein, dass das
#: Verhältnis von Messung zu Erwartung nur noch Rauschen ist. Dämmerung und
#: Nacht liefern deshalb bewusst kein Ergebnis statt eines erfundenen.
MIN_ELEVATION_DEG = 5.0

#: Obergrenze des Klarheitsindex. Werte über 1 treten real auf, wenn helle
#: Wolkenränder zusätzliches Licht auf den Sensor streuen.
MAX_CLEAR_SKY_INDEX = 1.3


def _julian_centuries_since_j2000(moment: datetime) -> float:
    """Tage seit dem 1. Januar 2000, 12:00 UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    epoch = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    return (moment - epoch).total_seconds() / 86400.0


def solar_elevation(moment: datetime, latitude: float, longitude: float) -> float:
    """Höhe der Sonne über dem Horizont in Grad.

    Negative Werte bedeuten, dass die Sonne unter dem Horizont steht.
    Ohne Refraktionskorrektur — die spielt nur nahe des Horizonts eine Rolle,
    und dort wird ohnehin nicht gerechnet.
    """
    n = _julian_centuries_since_j2000(moment)

    mean_longitude = math.radians((280.460 + 0.9856474 * n) % 360.0)
    mean_anomaly = math.radians((357.528 + 0.9856003 * n) % 360.0)

    ecliptic_longitude = mean_longitude + math.radians(
        1.915 * math.sin(mean_anomaly) + 0.020 * math.sin(2.0 * mean_anomaly)
    )
    obliquity = math.radians(23.439 - 0.0000004 * n)

    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_longitude))
    right_ascension = math.atan2(
        math.cos(obliquity) * math.sin(ecliptic_longitude),
        math.cos(ecliptic_longitude),
    )

    # Sternzeit in Greenwich, daraus die lokale Sternzeit und der Stundenwinkel.
    greenwich_sidereal = (18.697374558 + 24.06570982441908 * n) % 24.0
    local_sidereal = math.radians((greenwich_sidereal * 15.0 + longitude) % 360.0)
    hour_angle = local_sidereal - right_ascension

    phi = math.radians(latitude)
    sin_elevation = math.sin(phi) * math.sin(declination) + math.cos(phi) * math.cos(
        declination
    ) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_elevation))))


def clear_sky_irradiance(elevation_deg: float) -> float:
    """Erwartete Globalstrahlung bei wolkenlosem Himmel in W/m² (Haurwitz).

    Gibt 0.0 zurück, wenn die Sonne unter dem Horizont steht.
    """
    if elevation_deg <= 0.0:
        return 0.0
    cos_zenith = math.sin(math.radians(elevation_deg))
    if cos_zenith <= 0.0:
        return 0.0
    return 1098.0 * cos_zenith * math.exp(-0.059 / cos_zenith)


def lux_to_irradiance(lux: float) -> float:
    """Rechne Beleuchtungsstärke in Bestrahlungsstärke um."""
    return lux / LUX_PER_WATT_PER_M2


def clear_sky_index(
    measured_irradiance: float,
    moment: datetime,
    latitude: float,
    longitude: float,
    calibration: float = 1.0,
) -> float | None:
    """Anteil der Klarhimmelstrahlung, der tatsächlich ankommt (0 bis 1.3).

    Gibt None zurück, wenn die Sonne zu tief steht. Bewusst None statt 0:
    „keine Aussage möglich" ist etwas anderes als „stockdunkel bewölkt".

    ``calibration`` skaliert das Klarhimmelmodell. Liest der Sensor
    systematisch zu niedrig, meldet die Integration sonst auch an
    wolkenlosen Tagen dauerhaft Bewölkung.
    """
    elevation = solar_elevation(moment, latitude, longitude)
    if elevation < MIN_ELEVATION_DEG:
        return None

    expected = clear_sky_irradiance(elevation) * calibration
    if expected <= 0.0:
        return None

    index = measured_irradiance / expected
    return max(0.0, min(MAX_CLEAR_SKY_INDEX, index))


def cloud_coverage(index: float) -> float:
    """Fehlende Strahlung in Prozent, aus dem Klarheitsindex."""
    return round(max(0.0, min(1.0, 1.0 - index)) * 100.0, 1)


def condition_for_coverage(coverage: float, is_daytime: bool) -> str:
    """Übersetze den Trübungsgrad in einen Home-Assistant-Wetterzustand."""
    if coverage <= 20.0:
        return "sunny" if is_daytime else "clear-night"
    if coverage <= 70.0:
        return "partlycloudy"
    return "cloudy"

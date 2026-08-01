"""Konstanten der Integration "Lokale Wetterprognose"."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "local_forecast"
VERSION: Final = "0.3.0"

#: Lovelace-Karte
CARD_FILENAME: Final = "local-forecast-card.js"
CARD_URL: Final = f"/{DOMAIN}/{CARD_FILENAME}"
MANUFACTURER: Final = "Lokale Wetterprognose"
DEFAULT_NAME: Final = "Lokale Wetterprognose"

# Konfigurationsschlüssel (Einrichtungsdialog)
CONF_PRESSURE_SENSOR: Final = "pressure_sensor"
CONF_PRESSURE_IS_ABSOLUTE: Final = "pressure_is_absolute"
CONF_TEMPERATURE_SENSOR: Final = "temperature_sensor"
CONF_HUMIDITY_SENSOR: Final = "humidity_sensor"
CONF_WIND_BEARING_SENSOR: Final = "wind_bearing_sensor"
CONF_WIND_SPEED_SENSOR: Final = "wind_speed_sensor"
CONF_RAIN_RATE_SENSOR: Final = "rain_rate_sensor"
CONF_SOLAR_SENSOR: Final = "solar_sensor"

# Konfigurationsschlüssel (Optionen, nachträglich änderbar)
CONF_ELEVATION: Final = "elevation"
CONF_TREND_HOURS: Final = "trend_hours"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_SOLAR_CALIBRATION: Final = "solar_calibration"

DEFAULT_SOLAR_CALIBRATION: Final = 1.0
MIN_SOLAR_CALIBRATION: Final = 0.5
MAX_SOLAR_CALIBRATION: Final = 1.5

DEFAULT_TREND_HOURS: Final = 3
MIN_TREND_HOURS: Final = 1
MAX_TREND_HOURS: Final = 12

DEFAULT_UPDATE_INTERVAL: Final = 5  # Minuten
MIN_UPDATE_INTERVAL: Final = 1
MAX_UPDATE_INTERVAL: Final = 60

#: So viele Messwerte müssen mindestens im Trendfenster liegen, bevor eine
#: Prognose ausgegeben wird. Verhindert wilde Sprünge direkt nach dem Start.
MIN_SAMPLES_FOR_TREND: Final = 3

#: Plausibilitätsgrenzen für den auf Meereshöhe reduzierten Druck. Werte
#: außerhalb dieses Bereichs deuten fast immer auf eine falsch gewählte
#: Entität (z. B. absoluter statt relativer Druck) hin.
PRESSURE_SANITY_MIN: Final = 870.0
PRESSURE_SANITY_MAX: Final = 1085.0

#: Anzahl der Prognoseeinträge. MUSS größer als 2 sein: das Home-Assistant-
#: Frontend stellt eine Prognose erst ab mehr als zwei Einträgen dar
#: (getForecast() in frontend/src/data/weather.ts prüft `forecast.length > 2`).
#: Bei weniger Einträgen dreht sich in der Karte dauerhaft der Ladekreis.
FORECAST_ENTRY_COUNT: Final = 6

#: Attributnamen der Weather-Entity
ATTR_ZAMBRETTI_CODE: Final = "zambretti_code"
ATTR_ZAMBRETTI_TEXT: Final = "zambretti_text"
ATTR_PRESSURE_TREND: Final = "pressure_trend"
ATTR_SEA_LEVEL_PRESSURE: Final = "sea_level_pressure"
ATTR_SAMPLE_COUNT: Final = "sample_count"
ATTR_TREND_HOURS: Final = "trend_hours"
ATTR_PRESSURE_ENTITY: Final = "pressure_entity_id"
ATTR_CLEAR_SKY_INDEX: Final = "clear_sky_index"
ATTR_CONDITION_SOURCE: Final = "condition_source"

#: Woher der angezeigte Zustand stammt - macht die Rangfolge nachvollziehbar.
SOURCE_RAIN: Final = "regenmessung"
SOURCE_SOLAR: Final = "strahlungsmessung"
SOURCE_FORECAST: Final = "prognose"

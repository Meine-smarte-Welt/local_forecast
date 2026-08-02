"""Weather-Entity der lokalen Wetterprognose."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_POURING,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SUNNY,
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.sun import is_up
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CLEAR_SKY_INDEX,
    ATTR_CONDITION_SOURCE,
    ATTR_PRESSURE_ENTITY,
    ATTR_PRESSURE_TREND,
    ATTR_TREND_HOURS,
    CONF_PRESSURE_SENSOR,
    CONF_TREND_HOURS,
    DEFAULT_TREND_HOURS,
    FORECAST_ENTRY_COUNT,
    SOURCE_FORECAST,
    SOURCE_RAIN,
    SOURCE_SOLAR,
    ATTR_SAMPLE_COUNT,
    ATTR_SEA_LEVEL_PRESSURE,
    ATTR_ZAMBRETTI_CODE,
    ATTR_ZAMBRETTI_TEXT,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import ForecastData, LocalForecastConfigEntry, LocalForecastCoordinator
from .solar import condition_for_coverage

#: Regenrate (mm/h), ab der von Starkregen statt Regen ausgegangen wird.
POURING_THRESHOLD_MM_H = 4.0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LocalForecastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Richte die Weather-Entity ein."""
    async_add_entities([LocalForecastWeather(config_entry.runtime_data, config_entry)])


class LocalForecastWeather(CoordinatorEntity[LocalForecastCoordinator], WeatherEntity):
    """Wetter-Entity, die ausschließlich aus lokalen Sensoren gespeist wird."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "local_forecast"
    _attr_attribution = "Zambretti-Verfahren, berechnet aus lokalen Sensordaten"

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS

    # Bewusst stündlich statt zweimal täglich: das Frontend rendert eine
    # Prognose erst ab MEHR ALS ZWEI Einträgen (getForecast() in
    # frontend/src/data/weather.ts prüft `forecast.length > 2`). Ein einzelner
    # Eintrag - was dem Verfahren eigentlich entspräche - lässt die Anzeige
    # dauerhaft im Ladezustand hängen. Siehe README.
    _attr_supported_features = WeatherEntityFeature.FORECAST_HOURLY

    def __init__(
        self,
        coordinator: LocalForecastCoordinator,
        config_entry: LocalForecastConfigEntry,
    ) -> None:
        """Initialisiere die Entity."""
        super().__init__(coordinator)
        self._attr_unique_id = config_entry.entry_id
        # Beides nur für die Lovelace-Karte: sie zeichnet den Druckverlauf und
        # muss dafür wissen, welche Entität über welchen Zeitraum abzufragen ist.
        self._pressure_entity: str = config_entry.data[CONF_PRESSURE_SENSOR]
        self._trend_hours: int = config_entry.options.get(
            CONF_TREND_HOURS, DEFAULT_TREND_HOURS
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=config_entry.title or DEFAULT_NAME,
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _data(self) -> ForecastData | None:
        return self.coordinator.data

    # ------------------------------------------------------------------
    # Aktuelle Messwerte
    # ------------------------------------------------------------------

    @property
    def native_temperature(self) -> float | None:
        """Aktuelle Temperatur."""
        return self._data.temperature if self._data else None

    @property
    def humidity(self) -> float | None:
        """Aktuelle Luftfeuchte."""
        return self._data.humidity if self._data else None

    @property
    def native_pressure(self) -> float | None:
        """Aktueller Luftdruck auf Meereshöhe."""
        return self._data.pressure if self._data else None

    @property
    def cloud_coverage(self) -> float | None:
        """Anteil der fehlenden Sonnenstrahlung in Prozent."""
        return self._data.cloud_coverage if self._data else None

    @property
    def wind_bearing(self) -> float | None:
        """Aktuelle Windrichtung in Grad."""
        return self._data.wind_bearing if self._data else None

    @property
    def native_wind_speed(self) -> float | None:
        """Aktuelle Windgeschwindigkeit."""
        return self._data.wind_speed if self._data else None

    # ------------------------------------------------------------------
    # Zustand
    # ------------------------------------------------------------------

    @property
    def condition(self) -> str | None:
        """Aktueller Wetterzustand.

        Rangfolge der Wahrheitsquellen, von hart nach weich:

        1. **Regenmessung.** Fällt messbar Regen, gewinnt sie. Keine Rechnung
           darf behaupten, es sei sonnig, während der Regenmesser läuft.
        2. **Strahlungsmessung** (seit 0.3.0). Steht die Sonne hoch genug,
           verrät der Vergleich von gemessener und erwarteter Strahlung, wie
           stark die Sonne verdeckt ist. Auch das ist eine Messung, kein Modell.
        3. **Zambretti-Ausblick.** Nur noch der Rückfall für die Nacht und für
           Einrichtungen ohne Strahlungssensor. Vor 0.3.0 war das der
           Normalfall - der angezeigte "aktuelle" Zustand war damals in
           Wahrheit eine Vorhersage.

        Welche Quelle gegriffen hat, steht im Attribut ``condition_source``.
        """
        data = self._data
        if data is None:
            return None

        if data.rain_rate is not None and data.rain_rate > 0:
            if data.temperature is not None and data.temperature < 1.0:
                return ATTR_CONDITION_SNOWY
            if data.rain_rate >= POURING_THRESHOLD_MM_H:
                return ATTR_CONDITION_POURING
            return ATTR_CONDITION_RAINY

        if data.cloud_coverage is not None:
            return condition_for_coverage(data.cloud_coverage, self._is_daytime())

        if data.result is None:
            return None

        condition = data.result.condition
        if condition == ATTR_CONDITION_SUNNY and not self._is_daytime():
            return ATTR_CONDITION_CLEAR_NIGHT
        return condition

    @property
    def _condition_source(self) -> str | None:
        """Benenne, welche Quelle den Zustand gerade bestimmt."""
        data = self._data
        if data is None:
            return None
        if data.rain_rate is not None and data.rain_rate > 0:
            return SOURCE_RAIN
        if data.cloud_coverage is not None:
            return SOURCE_SOLAR
        return SOURCE_FORECAST

    def _is_daytime(self, moment=None) -> bool:
        """Steht die Sonne zu diesem Zeitpunkt über dem Horizont?

        Bewusst über den Sonnenstands-Helfer und nicht über den Zustand von
        ``sun.sun``: dieser kennt nur das Jetzt. Für die Prognoseeinträge
        braucht es die Antwort für jede einzelne kommende Stunde, sonst
        strahlt in der Nachtvorschau sechsmal eine Sonne.
        """
        try:
            return is_up(self.hass, moment)
        except Exception:  # noqa: BLE001 - ohne Standortdaten lieber Tag annehmen
            return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Zusatzattribute mit dem Rohergebnis des Verfahrens."""
        data = self._data
        if data is None:
            return {}

        attributes: dict[str, Any] = {
            ATTR_SAMPLE_COUNT: data.sample_count,
            ATTR_TREND_HOURS: self._trend_hours,
            ATTR_PRESSURE_ENTITY: self._pressure_entity,
        }
        source = self._condition_source
        if source is not None:
            attributes[ATTR_CONDITION_SOURCE] = source
        if data.clear_sky_index is not None:
            attributes[ATTR_CLEAR_SKY_INDEX] = round(data.clear_sky_index, 2)
        if data.pressure is not None:
            attributes[ATTR_SEA_LEVEL_PRESSURE] = round(data.pressure, 1)
        if data.result is not None:
            attributes[ATTR_ZAMBRETTI_CODE] = data.result.code
            attributes[ATTR_ZAMBRETTI_TEXT] = data.result.text
            attributes[ATTR_PRESSURE_TREND] = round(data.result.trend, 2)
        return attributes

    # ------------------------------------------------------------------
    # Prognose
    # ------------------------------------------------------------------

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Gib den Zambretti-Ausblick als stündliche Einträge zurück.

        Wichtig zum Verständnis: das Verfahren liefert GENAU EINEN Ausblick für
        die kommenden Stunden. Die hier erzeugten Einträge tragen deshalb alle
        dieselbe Vorhersage - sie verteilen eine einzige Aussage über ihren
        Gültigkeitszeitraum und enthalten KEINE eigenständige stündliche
        Auflösung. Mehrere Einträge sind nötig, weil das Frontend eine Prognose
        erst ab mehr als zwei Einträgen darstellt.

        Eine Temperaturprognose gibt es nicht. Da das Feld verpflichtend ist,
        steht dort der aktuelle Messwert - er darf nicht als Vorhersage
        gelesen werden.
        """
        data = self._data
        if data is None or data.result is None:
            return None

        now = dt_util.utcnow()
        entries: list[Forecast] = []
        for hour in range(1, FORECAST_ENTRY_COUNT + 1):
            moment = now + timedelta(hours=hour)
            condition = data.result.condition
            if condition == ATTR_CONDITION_SUNNY and not self._is_daytime(moment):
                condition = ATTR_CONDITION_CLEAR_NIGHT
            entries.append(
                Forecast(
                    datetime=moment.isoformat(),
                    condition=condition,
                    native_temperature=data.temperature,
                    native_pressure=data.pressure,
                    wind_bearing=data.wind_bearing,
                    native_wind_speed=data.wind_speed,
                )
            )
        return entries

    @callback
    def _handle_coordinator_update(self) -> None:
        """Neuen Zustand schreiben UND die Prognose an Abonnenten schieben.

        Ohne den zweiten Teil bliebe eine geöffnete Wetterkarte auf dem Stand
        vom Abo-Zeitpunkt stehen - der Zustand würde sich aktualisieren, die
        Prognose darunter aber nicht.
        """
        if self.platform is not None and self.platform.config_entry is not None:
            self.platform.config_entry.async_create_task(
                self.hass, self.async_update_listeners(("hourly",))
            )
        super()._handle_coordinator_update()

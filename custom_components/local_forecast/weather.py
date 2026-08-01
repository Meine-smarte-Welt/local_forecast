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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_PRESSURE_TREND,
    ATTR_SAMPLE_COUNT,
    ATTR_SEA_LEVEL_PRESSURE,
    ATTR_ZAMBRETTI_CODE,
    ATTR_ZAMBRETTI_TEXT,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import ForecastData, LocalForecastConfigEntry, LocalForecastCoordinator

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

    _attr_supported_features = WeatherEntityFeature.FORECAST_TWICE_DAILY

    def __init__(
        self,
        coordinator: LocalForecastCoordinator,
        config_entry: LocalForecastConfigEntry,
    ) -> None:
        """Initialisiere die Entity."""
        super().__init__(coordinator)
        self._attr_unique_id = config_entry.entry_id
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

        Reihenfolge der Wahrheitsquellen:

        1. Fällt gerade messbar Regen, gewinnt die Messung - eine Prognose
           kann nicht behaupten, es sei sonnig, während der Regenmesser läuft.
        2. Sonst der Zambretti-Ausblick. Das ist bewusst eine Näherung: das
           Verfahren sagt die kommenden Stunden voraus, nicht den Moment.
           Die Alternative wäre gar kein Zustand gewesen.
        3. Bei "sunny" nach Sonnenuntergang wird auf "clear-night" gewechselt.
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

        if data.result is None:
            return None

        condition = data.result.condition
        if condition == ATTR_CONDITION_SUNNY and not self._is_daytime():
            return ATTR_CONDITION_CLEAR_NIGHT
        return condition

    def _is_daytime(self) -> bool:
        """Steht die Sonne über dem Horizont?"""
        sun = self.hass.states.get("sun.sun")
        if sun is None:
            return True
        return sun.state != "below_horizon"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Zusatzattribute mit dem Rohergebnis des Verfahrens."""
        data = self._data
        if data is None:
            return {}

        attributes: dict[str, Any] = {ATTR_SAMPLE_COUNT: data.sample_count}
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

    async def async_forecast_twice_daily(self) -> list[Forecast] | None:
        """Gib den Zambretti-Ausblick als einzelnen Prognoseeintrag zurück.

        Das Verfahren liefert genau EINEN Ausblick für die nächsten etwa
        6 bis 12 Stunden - deshalb steht hier auch nur ein Eintrag und keine
        Mehrtagesreihe. Eine Temperaturprognose gibt es nicht; da das Feld
        verpflichtend ist, wird der aktuelle Messwert eingetragen. Das ist in
        der README als bekannte Einschränkung dokumentiert.
        """
        data = self._data
        if data is None or data.result is None:
            return None

        now = dt_util.utcnow()
        target = now + timedelta(hours=6)

        return [
            Forecast(
                datetime=target.isoformat(),
                is_daytime=self._is_daytime(),
                condition=data.result.condition,
                native_temperature=data.temperature,
                native_pressure=data.pressure,
                wind_bearing=data.wind_bearing,
                native_wind_speed=data.wind_speed,
            )
        ]

"""Datenkoordinator der lokalen Wetterprognose.

Der Koordinator hält eine gleitende Druckhistorie über das konfigurierte
Trendfenster und berechnet daraus die Zambretti-Prognose. Beim Start wird die
Historie einmalig aus dem Recorder vorgefüllt - dadurch liefert die Integration
sofort nach einem Neustart eine Prognose und nicht erst nach drei Stunden.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ELEVATION,
    CONF_HUMIDITY_SENSOR,
    CONF_PRESSURE_IS_ABSOLUTE,
    CONF_PRESSURE_SENSOR,
    CONF_RAIN_RATE_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    CONF_TREND_HOURS,
    CONF_UPDATE_INTERVAL,
    CONF_WIND_BEARING_SENSOR,
    CONF_WIND_SPEED_SENSOR,
    DEFAULT_TREND_HOURS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MIN_SAMPLES_FOR_TREND,
    PRESSURE_SANITY_MAX,
    PRESSURE_SANITY_MIN,
)
from .zambretti import ZambrettiResult, forecast, pressure_trend, to_sea_level

_LOGGER = logging.getLogger(__name__)

type LocalForecastConfigEntry = ConfigEntry["LocalForecastCoordinator"]


@dataclass
class ForecastData:
    """Alles, was die Weather-Entity zum Rendern braucht."""

    result: ZambrettiResult | None
    """Prognose, oder None solange die Historie noch zu kurz ist."""

    temperature: float | None
    humidity: float | None
    pressure: float | None
    wind_bearing: float | None
    wind_speed: float | None
    rain_rate: float | None
    sample_count: int


class LocalForecastCoordinator(DataUpdateCoordinator[ForecastData]):
    """Sammelt Messwerte und berechnet daraus die lokale Prognose."""

    config_entry: LocalForecastConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: LocalForecastConfigEntry
    ) -> None:
        """Initialisiere den Koordinator."""
        options = config_entry.options
        interval = options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(minutes=interval),
        )

        data = config_entry.data
        self._pressure_entity: str = data[CONF_PRESSURE_SENSOR]
        self._pressure_is_absolute: bool = data.get(CONF_PRESSURE_IS_ABSOLUTE, False)
        self._temperature_entity: str = data[CONF_TEMPERATURE_SENSOR]
        self._humidity_entity: str | None = data.get(CONF_HUMIDITY_SENSOR)
        self._wind_bearing_entity: str | None = data.get(CONF_WIND_BEARING_SENSOR)
        self._wind_speed_entity: str | None = data.get(CONF_WIND_SPEED_SENSOR)
        self._rain_rate_entity: str | None = data.get(CONF_RAIN_RATE_SENSOR)

        self._trend_hours: int = options.get(CONF_TREND_HOURS, DEFAULT_TREND_HOURS)
        self._elevation: float = float(
            options.get(CONF_ELEVATION, hass.config.elevation or 0)
        )
        self._northern: bool = (hass.config.latitude or 0) >= 0

        # (Zeitstempel in Sekunden, Druck auf Meereshöhe in hPa)
        self._history: deque[tuple[float, float]] = deque()
        self._history_seeded = False

    # ------------------------------------------------------------------
    # Messwert-Zugriff
    # ------------------------------------------------------------------

    def _read_float(self, entity_id: str | None) -> float | None:
        """Lies einen numerischen Zustand, oder None wenn nicht verwertbar."""
        if not entity_id:
            return None
        state: State | None = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", "", None):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            _LOGGER.debug(
                "Zustand von %s ist nicht numerisch: %s", entity_id, state.state
            )
            return None

    def _to_sea_level(self, raw_pressure: float, temperature: float | None) -> float:
        """Reduziere den Rohdruck auf Meereshöhe, falls nötig."""
        if not self._pressure_is_absolute:
            return raw_pressure
        # Ohne Temperatur ist die Reduktion ungenau, aber immer noch besser als
        # gar keine - 15 °C ist der Standardwert der Normatmosphäre.
        return to_sea_level(
            raw_pressure, self._elevation, temperature if temperature is not None else 15.0
        )

    # ------------------------------------------------------------------
    # Historie
    # ------------------------------------------------------------------

    def _prune_history(self, now_ts: float) -> None:
        """Entferne Messwerte, die älter als das Trendfenster sind."""
        cutoff = now_ts - self._trend_hours * 3600.0
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    async def _async_seed_history(self) -> None:
        """Fülle die Druckhistorie einmalig aus dem Recorder vor.

        Schlägt das fehl (Recorder deaktiviert, Sensor nicht aufgezeichnet), ist
        das kein Fehler: die Historie baut sich dann eben live auf.
        """
        self._history_seeded = True
        try:
            from homeassistant.components.recorder import get_instance, history
        except ImportError:
            _LOGGER.debug("Recorder nicht verfügbar, Historie wird live aufgebaut")
            return

        end = dt_util.utcnow()
        start = end - timedelta(hours=self._trend_hours)

        def _fetch() -> list[State]:
            states = history.state_changes_during_period(
                self.hass,
                start,
                end,
                entity_id=self._pressure_entity,
                include_start_time_state=True,
                no_attributes=True,
            )
            return states.get(self._pressure_entity, [])

        try:
            recorded = await get_instance(self.hass).async_add_executor_job(_fetch)
        except Exception as err:  # noqa: BLE001 - Recorder-Fehler dürfen nicht töten
            _LOGGER.debug("Historie konnte nicht vorgefüllt werden: %s", err)
            return

        temperature = self._read_float(self._temperature_entity)
        seeded = 0
        for state in recorded:
            try:
                raw = float(state.state)
            except (TypeError, ValueError):
                continue
            timestamp: datetime = state.last_updated
            self._history.append(
                (timestamp.timestamp(), self._to_sea_level(raw, temperature))
            )
            seeded += 1

        _LOGGER.debug("%s Druckwerte aus dem Recorder übernommen", seeded)

    # ------------------------------------------------------------------
    # Aktualisierung
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> ForecastData:
        """Lies alle Sensoren und berechne die Prognose neu."""
        raw_pressure = self._read_float(self._pressure_entity)
        if raw_pressure is None:
            raise UpdateFailed(
                f"Drucksensor {self._pressure_entity} liefert keinen Messwert"
            )

        temperature = self._read_float(self._temperature_entity)
        humidity = self._read_float(self._humidity_entity)
        wind_bearing = self._read_float(self._wind_bearing_entity)
        wind_speed = self._read_float(self._wind_speed_entity)
        rain_rate = self._read_float(self._rain_rate_entity)

        sea_level = self._to_sea_level(raw_pressure, temperature)

        if not PRESSURE_SANITY_MIN <= sea_level <= PRESSURE_SANITY_MAX:
            raise UpdateFailed(
                f"Druck {sea_level:.1f} hPa liegt außerhalb des plausiblen Bereichs "
                f"({PRESSURE_SANITY_MIN:.0f}-{PRESSURE_SANITY_MAX:.0f} hPa). "
                "Ist wirklich der RELATIVE Druck ausgewählt?"
            )

        if not self._history_seeded:
            await self._async_seed_history()

        now = dt_util.utcnow()
        now_ts = now.timestamp()
        self._history.append((now_ts, sea_level))
        self._prune_history(now_ts)

        result: ZambrettiResult | None = None
        if len(self._history) >= MIN_SAMPLES_FOR_TREND:
            trend = pressure_trend(list(self._history))
            if trend is not None:
                result = forecast(
                    sea_level_hpa=sea_level,
                    month=dt_util.as_local(now).month,
                    trend_hpa_per_hour=trend,
                    wind_bearing_deg=wind_bearing,
                    temperature_c=temperature,
                    northern_hemisphere=self._northern,
                )

        return ForecastData(
            result=result,
            temperature=temperature,
            humidity=humidity,
            pressure=sea_level,
            wind_bearing=wind_bearing,
            wind_speed=wind_speed,
            rain_rate=rain_rate,
            sample_count=len(self._history),
        )

"""Einrichtungs- und Optionsdialog der lokalen Wetterprognose."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

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
    DEFAULT_NAME,
    DEFAULT_TREND_HOURS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_TREND_HOURS,
    MAX_UPDATE_INTERVAL,
    MIN_TREND_HOURS,
    MIN_UPDATE_INTERVAL,
)

# Bewusst nur nach Domain gefiltert, nicht nach device_class: selbst gebaute
# Template-Sensoren tragen oft keine device_class und wären sonst nicht
# auswählbar. Die moderne "filter"-Syntax statt des als feature-frozen
# markierten Legacy-Schlüssels "domain" auf oberster Ebene.
_SENSOR_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(
        filter=[
            selector.EntityFilterSelectorConfig(
                domain=["sensor", "number", "input_number"]
            )
        ]
    )
)


def _user_schema() -> vol.Schema:
    """Schema des Einrichtungsdialogs."""
    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
            vol.Required(CONF_PRESSURE_SENSOR): _SENSOR_SELECTOR,
            vol.Optional(CONF_PRESSURE_IS_ABSOLUTE, default=False): (
                selector.BooleanSelector()
            ),
            vol.Required(CONF_TEMPERATURE_SENSOR): _SENSOR_SELECTOR,
            vol.Optional(CONF_HUMIDITY_SENSOR): _SENSOR_SELECTOR,
            vol.Optional(CONF_WIND_BEARING_SENSOR): _SENSOR_SELECTOR,
            vol.Optional(CONF_WIND_SPEED_SENSOR): _SENSOR_SELECTOR,
            vol.Optional(CONF_RAIN_RATE_SENSOR): _SENSOR_SELECTOR,
        }
    )


def _options_schema(
    current: dict[str, Any], default_elevation: float
) -> vol.Schema:
    """Schema des Optionsdialogs."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_TREND_HOURS,
                default=current.get(CONF_TREND_HOURS, DEFAULT_TREND_HOURS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_TREND_HOURS,
                    max=MAX_TREND_HOURS,
                    step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                    unit_of_measurement="h",
                )
            ),
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=current.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_UPDATE_INTERVAL,
                    max=MAX_UPDATE_INTERVAL,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
            vol.Optional(
                CONF_ELEVATION,
                default=current.get(CONF_ELEVATION, default_elevation),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-500,
                    max=5000,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="m",
                )
            ),
        }
    )


class LocalForecastConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtungsdialog."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sensoren auswählen."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pressure_entity = user_input[CONF_PRESSURE_SENSOR]
            self._async_abort_entries_match(
                {CONF_PRESSURE_SENSOR: pressure_entity}
            )

            state = self.hass.states.get(pressure_entity)
            if state is None:
                errors[CONF_PRESSURE_SENSOR] = "entity_not_found"
            else:
                try:
                    float(state.state)
                except (TypeError, ValueError):
                    errors[CONF_PRESSURE_SENSOR] = "not_numeric"

            if not errors:
                title = user_input.pop(CONF_NAME, DEFAULT_NAME) or DEFAULT_NAME
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> LocalForecastOptionsFlow:
        """Optionsdialog bereitstellen."""
        return LocalForecastOptionsFlow()


class LocalForecastOptionsFlow(OptionsFlowWithReload):
    """Optionsdialog. Änderungen laden die Integration automatisch neu."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Trendfenster, Abfragetakt und Höhe über NN anpassen."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(
                dict(self.config_entry.options),
                float(self.hass.config.elevation or 0),
            ),
        )

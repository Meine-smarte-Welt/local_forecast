"""Die Integration "Lokale Wetterprognose"."""

from __future__ import annotations

import logging

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, Event, HomeAssistant

from .coordinator import LocalForecastConfigEntry, LocalForecastCoordinator
from .frontend import CardRegistration

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.WEATHER]

_CARD_REGISTERED = "local_forecast_card_registered"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Richte die Kartenregistrierung ein - einmal je Installation.

    Bewusst hier und nicht in async_setup_entry: Die Karte soll einmal pro
    Home-Assistant-Lauf registriert werden, nicht einmal je Wetterstation.
    Die eigentliche Registrierung wartet auf das Startende, weil die
    Lovelace-Ressourcen vorher noch nicht geladen sind.
    """

    async def _register(_event: Event | None = None) -> None:
        if hass.data.get(_CARD_REGISTERED):
            return
        hass.data[_CARD_REGISTERED] = True
        try:
            await CardRegistration(hass).async_register()
        except Exception as err:  # noqa: BLE001 - Karte darf den Start nie kippen
            _LOGGER.warning("Karte konnte nicht registriert werden: %s", err)

    if hass.state is CoreState.running:
        await _register()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register)

    return True


async def async_setup_entry(
    hass: HomeAssistant, config_entry: LocalForecastConfigEntry
) -> bool:
    """Richte einen Konfigurationseintrag ein."""
    coordinator = LocalForecastCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()

    config_entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: LocalForecastConfigEntry
) -> bool:
    """Entlade einen Konfigurationseintrag."""
    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

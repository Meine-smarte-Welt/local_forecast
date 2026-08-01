"""Die Integration "Lokale Wetterprognose"."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CARD_FILENAME, CARD_URL, DOMAIN, VERSION
from .coordinator import LocalForecastConfigEntry, LocalForecastCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.WEATHER]

_CARD_REGISTERED = f"{DOMAIN}_card_registered"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Mache die Lovelace-Karte verfuegbar, ohne dass sie jemand von Hand
    als Ressource eintragen muss.

    Passiert genau einmal pro Home-Assistant-Lauf, auch wenn mehrere
    Konfigurationseintraege existieren. Schlaegt es fehl, laeuft die
    Integration trotzdem weiter - die Karte ist Zubehoer, keine Bedingung.
    """
    if hass.data.get(_CARD_REGISTERED):
        return
    hass.data[_CARD_REGISTERED] = True

    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(card_path), True)]
        )
        # Die Version haengt an der Adresse, damit der Browser nach einem
        # Update nicht die alte Datei aus dem Zwischenspeicher nimmt.
        add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}")
    except Exception as err:  # noqa: BLE001 - Karte darf das Setup nie kippen
        _LOGGER.warning("Lovelace-Karte konnte nicht bereitgestellt werden: %s", err)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: LocalForecastConfigEntry
) -> bool:
    """Richte einen Konfigurationseintrag ein."""
    await _async_register_card(hass)

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

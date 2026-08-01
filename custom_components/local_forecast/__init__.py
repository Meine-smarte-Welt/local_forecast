"""Die Integration "Lokale Wetterprognose"."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import LocalForecastConfigEntry, LocalForecastCoordinator

PLATFORMS: list[Platform] = [Platform.WEATHER]


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

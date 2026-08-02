"""Automatische Registrierung der Lovelace-Karte als Ressource.

Warum eigens dafür ein Modul, statt einfach ``add_extra_js_url`` aufzurufen:
Dieser Aufruf legt eine Adresse nur in eine Liste, die das Frontend beim
Ausliefern der Startseite einliest. Hat der Browser die Seite schon geladen,
greift die Registrierung erst nach einem harten Neuladen - für die
Companion-App ist das unzuverlässig. Der belastbare Weg ist, die Karte als
richtige Lovelace-**Ressource** einzutragen, genau wie es ein Nutzer von Hand
täte; Home Assistant liefert sie dann bei jedem Seitenaufbau aus.

Drei Dinge sind dabei wichtig, die der naive Ansatz übersieht:

* Die Registrierung gehört in ``async_setup``, nicht in ``async_setup_entry`` -
  sie soll einmal je Installation geschehen, nicht je Konfigurationseintrag.
* Sie muss warten, bis die Lovelace-Ressourcen geladen sind; beim Start sind
  sie es anfangs nicht.
* Bei einem Versionswechsel muss der vorhandene Eintrag aktualisiert statt
  ein zweiter angelegt werden, sonst wird die Karte doppelt geladen.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from .const import CARD_FILENAME, CARD_URL, VERSION

_LOGGER = logging.getLogger(__name__)

_STORAGE_MODE = "storage"


class CardRegistration:
    """Trägt die Karte als statischen Pfad und als Lovelace-Ressource ein."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Merke die Home-Assistant-Instanz und die Lovelace-Daten."""
        self.hass = hass
        self.lovelace = hass.data.get("lovelace")

    async def async_register(self) -> None:
        """Registriere Pfad und - im Storage-Modus - die Ressource."""
        await self._async_register_path()

        # In aktuellem Home Assistant heißt das Feld "resource_mode"; ältere
        # Fassungen nannten es "mode". Beides wird berücksichtigt.
        mode = getattr(
            self.lovelace,
            "resource_mode",
            getattr(self.lovelace, "mode", None),
        )
        if mode == _STORAGE_MODE:
            await self._async_wait_for_resources()
        else:
            # YAML-Modus: die Datei ist über den statischen Pfad erreichbar,
            # den Ressourceneintrag muss der Nutzer aber selbst vornehmen.
            _LOGGER.debug(
                "Lovelace läuft im YAML-Modus; Ressource bitte manuell eintragen"
            )

    async def _async_register_path(self) -> None:
        """Mache die Kartendatei unter CARD_URL erreichbar."""
        card_path = Path(__file__).parent / "www" / CARD_FILENAME
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(CARD_URL, str(card_path), False)]
            )
            _LOGGER.debug("Statischer Pfad registriert: %s", CARD_URL)
        except RuntimeError:
            # Bei einem zweiten Aufruf (z. B. nach Reload) ist der Pfad schon da.
            _LOGGER.debug("Statischer Pfad war bereits registriert: %s", CARD_URL)

    async def _async_wait_for_resources(self) -> None:
        """Warte, bis die Lovelace-Ressourcen geladen sind, dann trage ein."""

        async def _check(_now: Any) -> None:
            resources = getattr(self.lovelace, "resources", None)
            if resources is not None and getattr(resources, "loaded", False):
                await self._async_register_resource(resources)
            else:
                async_call_later(self.hass, 5, _check)

        await _check(0)

    async def _async_register_resource(self, resources: Any) -> None:
        """Lege den Ressourceneintrag an oder aktualisiere ihn bei neuer Version."""
        versioned = f"{CARD_URL}?v={VERSION}"

        for item in resources.async_items():
            url = item.get("url", "")
            if url.split("?")[0] != CARD_URL:
                continue
            # Eintrag existiert bereits. Nur anfassen, wenn sich die Version
            # geändert hat - sonst bliebe eine alte Fassung im Cache verankert.
            if url == versioned:
                _LOGGER.debug("Ressource bereits aktuell: %s", versioned)
                return
            await resources.async_update_item(
                item["id"], {"res_type": "module", "url": versioned}
            )
            _LOGGER.info("Karten-Ressource auf %s aktualisiert", VERSION)
            return

        await resources.async_create_item(
            {"res_type": "module", "url": versioned}
        )
        _LOGGER.info("Karten-Ressource neu registriert: %s", versioned)

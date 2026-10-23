"""Smart TRV: room-sensor driven PI control for radiator thermostats."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.NUMBER, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = "/smart_trv/smart-trv-card.js"
CARD_FILE = Path(__file__).parent / "frontend" / "smart-trv-card.js"


@dataclass
class SmartTRVData:
    """State shared between the room's entities.

    diag: latest controller numbers, written by the climate entity, read by the sensors.
    night_temperature: owned by the number entity, used while the night entity is on.
    """

    diag: dict[str, Any] = field(default_factory=dict)
    night_temperature: float = 19.0


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the Smart TRV card and load it on every dashboard, so no resource has to be added."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=False)]
    )
    # frontend is an after_dependency: always there in a normal install, absent in tests.
    if "frontend" in hass.config.components:
        from homeassistant.components.frontend import add_extra_js_url

        # The file's mtime busts the browser cache whenever the card is updated.
        add_extra_js_url(hass, f"{CARD_URL}?v={int(CARD_FILE.stat().st_mtime)}")
    else:
        _LOGGER.debug("frontend not loaded; Smart TRV card served at %s but not auto-loaded", CARD_URL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry.runtime_data = SmartTRVData()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

"""Smart TRV: room-sensor driven PI control for radiator thermostats."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS = [Platform.CLIMATE, Platform.NUMBER, Platform.SENSOR]


@dataclass
class SmartTRVData:
    """State shared between the room's entities.

    diag: latest controller numbers, written by the climate entity, read by the sensors.
    night_temperature: owned by the number entity, used while the night entity is on.
    """

    diag: dict[str, Any] = field(default_factory=dict)
    night_temperature: float = 19.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry.runtime_data = SmartTRVData()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

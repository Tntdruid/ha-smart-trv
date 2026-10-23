"""TRV problem sensor per room: offline, silent for hours, low battery."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([TRVProblem(entry)])


class TRVProblem(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        name = {**entry.data, **entry.options}[CONF_NAME]
        self._attr_unique_id = f"{entry.entry_id}_problem"
        # Fixed English entity id, like the other Smart TRV entities.
        self.entity_id = f"binary_sensor.{slugify(name)}_problem"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATE.format(self._entry.entry_id), self.async_write_ha_state
            )
        )

    @property
    def _problems(self) -> dict[str, str]:
        return self._entry.runtime_data.diag.get("problems") or {}

    @property
    def available(self) -> bool:
        return "problems" in self._entry.runtime_data.diag

    @property
    def is_on(self) -> bool:
        return bool(self._problems)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._problems)

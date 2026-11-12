"""Night and away temperature per room, set on the device page or the dashboard."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import DOMAIN, SIGNAL_SETTINGS, TRV_MAX_TEMP, TRV_MIN_TEMP


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([RoomTemperature(entry, "night_temperature"), RoomTemperature(entry, "away_temperature")])


class RoomTemperature(RestoreNumber):
    """A temperature kept in the room's runtime data (night_temperature / away_temperature)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_native_min_value = TRV_MIN_TEMP
    _attr_native_max_value = TRV_MAX_TEMP
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        self._entry = entry
        self._key = key
        name = {**entry.data, **entry.options}[CONF_NAME]
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        # Fixed English entity id, so the dashboard generator finds it in any HA language.
        self.entity_id = f"number.{slugify(name)}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            setattr(self._entry.runtime_data, self._key, last.native_value)
        # The climate entity can change it too (thermostat card at night or away): follow along.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id), self.async_write_ha_state
            )
        )
        async_dispatcher_send(self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id))

    @property
    def native_value(self) -> float:
        return getattr(self._entry.runtime_data, self._key)

    async def async_set_native_value(self, value: float) -> None:
        setattr(self._entry.runtime_data, self._key, value)
        async_dispatcher_send(self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id))

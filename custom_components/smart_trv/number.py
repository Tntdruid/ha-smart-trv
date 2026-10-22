"""Night temperature per room, used while the room's night entity (e.g. a schedule) is on."""

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
    async_add_entities([NightTemperature(entry)])


class NightTemperature(RestoreNumber):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "night_temperature"
    _attr_native_min_value = TRV_MIN_TEMP
    _attr_native_max_value = TRV_MAX_TEMP
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        name = {**entry.data, **entry.options}[CONF_NAME]
        self._attr_unique_id = f"{entry.entry_id}_night_temperature"
        # Fixed English entity id, so the dashboard generator finds it in any HA language.
        self.entity_id = f"number.{slugify(name)}_night_temperature"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            self._entry.runtime_data.night_temperature = last.native_value
        # The climate entity can change it too (thermostat card at night): follow along.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id), self.async_write_ha_state
            )
        )
        async_dispatcher_send(self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id))

    @property
    def native_value(self) -> float:
        return self._entry.runtime_data.night_temperature

    async def async_set_native_value(self, value: float) -> None:
        self._entry.runtime_data.night_temperature = value
        async_dispatcher_send(self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id))

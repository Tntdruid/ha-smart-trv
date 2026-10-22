"""Diagnostic sensors that show what the controller is doing, so it can be graphed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import DOMAIN, SIGNAL_UPDATE, STATUSES


@dataclass(frozen=True, kw_only=True)
class SmartTRVSensorDescription(SensorEntityDescription):
    explanation: bool = False


def _temp(key: str, device_class: SensorDeviceClass | None = None) -> SmartTRVSensorDescription:
    return SmartTRVSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    )


SENSORS = (
    SmartTRVSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUSES,
        explanation=True,
    ),
    _temp("trv_setpoint", SensorDeviceClass.TEMPERATURE),
    _temp("trv_temperature", SensorDeviceClass.TEMPERATURE),
    # Offsets, not absolute temperatures: no temperature device class, so HA won't convert them.
    _temp("error"),
    _temp("p_term"),
    _temp("integral"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(SmartTRVSensor(entry, description) for description in SENSORS)


class SmartTRVSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    entity_description: SmartTRVSensorDescription

    def __init__(self, entry: ConfigEntry, description: SmartTRVSensorDescription) -> None:
        self.entity_description = description
        self._entry = entry
        name = {**entry.data, **entry.options}[CONF_NAME]
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # Fixed English entity ids, so the example dashboard works whatever the HA language.
        self.entity_id = f"sensor.{slugify(name)}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATE.format(self._entry.entry_id), self.async_write_ha_state
            )
        )

    @property
    def _diag(self) -> dict[str, Any]:
        return self._entry.runtime_data.diag

    @property
    def available(self) -> bool:
        return self.entity_description.key in self._diag

    @property
    def native_value(self) -> Any:
        return self._diag.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.explanation:
            return {"explanation": self._diag.get("explanation")}
        return None


"""Config flow for Smart TRV.

Only what describes the house is asked: sensors, TRVs, windows, night schedule. Control
details tune themselves (Kp/Ki), are read from the TRV (setpoint step) or are fixed; the few
that can be overridden sit in a collapsed "advanced" section.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_TUNE,
    CONF_KI,
    CONF_KP,
    CONF_NIGHT_ENTITY,
    CONF_OUTDOOR_GAIN,
    CONF_OUTDOOR_SENSOR,
    CONF_PREHEAT,
    CONF_ROOM_SENSOR,
    CONF_TRVS,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOWS,
    DEFAULT_AUTO_TUNE,
    DEFAULT_KI,
    DEFAULT_KP,
    DEFAULT_NAME,
    DEFAULT_OUTDOOR_GAIN,
    DEFAULT_PREHEAT,
    DEFAULT_WINDOW_CLOSE_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    DOMAIN,
)

ADVANCED = "advanced"


def _number(min_v: float, max_v: float, step: float, unit: str | None = None):
    config = selector.NumberSelectorConfig(
        min=min_v, max=max_v, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:  # None is rejected; the key must be left out instead
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _room_schema(defaults: dict[str, Any]) -> dict:
    return {
        vol.Required(CONF_ROOM_SENSOR, default=defaults.get(CONF_ROOM_SENSOR, vol.UNDEFINED)):
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
        vol.Required(CONF_TRVS, default=defaults.get(CONF_TRVS, vol.UNDEFINED)):
            selector.EntitySelector(selector.EntitySelectorConfig(domain="climate", multiple=True)),
        vol.Optional(CONF_WINDOWS, default=defaults.get(CONF_WINDOWS, [])):
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
        vol.Required(
            CONF_WINDOW_OPEN_DELAY,
            default=defaults.get(CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY),
        ): _number(0, 1800, 5, "s"),
        vol.Required(
            CONF_WINDOW_CLOSE_DELAY,
            default=defaults.get(CONF_WINDOW_CLOSE_DELAY, DEFAULT_WINDOW_CLOSE_DELAY),
        ): _number(0, 1800, 5, "s"),
        # suggested_value, not default: the field must be clearable in the options flow.
        vol.Optional(
            CONF_NIGHT_ENTITY, description={"suggested_value": defaults.get(CONF_NIGHT_ENTITY)}
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["schedule", "input_boolean", "binary_sensor"])
        ),
        vol.Optional(
            CONF_OUTDOOR_SENSOR, description={"suggested_value": defaults.get(CONF_OUTDOOR_SENSOR)}
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        vol.Required(CONF_PREHEAT, default=defaults.get(CONF_PREHEAT, DEFAULT_PREHEAT)):
            selector.BooleanSelector(),
        vol.Required(ADVANCED): section(
            vol.Schema(
                {
                    vol.Required(CONF_AUTO_TUNE, default=defaults.get(CONF_AUTO_TUNE, DEFAULT_AUTO_TUNE)):
                        selector.BooleanSelector(),
                    vol.Required(CONF_KP, default=defaults.get(CONF_KP, DEFAULT_KP)):
                        _number(0, 10, 0.1),
                    vol.Required(CONF_KI, default=defaults.get(CONF_KI, DEFAULT_KI)):
                        _number(0, 10, 0.1),
                    vol.Required(
                        CONF_OUTDOOR_GAIN, default=defaults.get(CONF_OUTDOOR_GAIN, DEFAULT_OUTDOOR_GAIN)
                    ): _number(0, 0.5, 0.05),
                }
            ),
            {"collapsed": True},
        ),
    }


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    """Store the advanced section's fields next to the others, as before."""
    data = dict(user_input)
    data.update(data.pop(ADVANCED, None) or {})
    return data


class SmartTRVConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            data = _flatten(user_input)
            return self.async_create_entry(title=data[CONF_NAME], data=data)

        schema = vol.Schema(
            {vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(), **_room_schema({})}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SmartTRVOptionsFlow()


class SmartTRVOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            data = _flatten(user_input)
            # A cleared field is left out of user_input; store None so it overrides entry.data.
            data.setdefault(CONF_NIGHT_ENTITY, None)
            data.setdefault(CONF_OUTDOOR_SENSOR, None)
            return self.async_create_entry(data=data)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=vol.Schema(_room_schema(current)))

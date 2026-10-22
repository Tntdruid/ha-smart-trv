"""Config flow for Smart TRV."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_INTERVAL,
    CONF_KI,
    CONF_KP,
    CONF_MAX_BOOST,
    CONF_MAX_CUT,
    CONF_NIGHT_ENTITY,
    CONF_ROOM_SENSOR,
    CONF_TRV_STEP,
    CONF_TRVS,
    CONF_WINDOWS,
    DEFAULT_INTERVAL,
    DEFAULT_KI,
    DEFAULT_KP,
    DEFAULT_MAX_BOOST,
    DEFAULT_MAX_CUT,
    DEFAULT_NAME,
    DEFAULT_TRV_STEP,
    DOMAIN,
)


def _number(min_v: float, max_v: float, step: float, unit: str | None = None):
    config = selector.NumberSelectorConfig(
        min=min_v, max=max_v, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:  # None is rejected; the key must be left out instead
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _entities_schema(defaults: dict[str, Any]) -> dict:
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
        # suggested_value, not default: the field must be clearable in the options flow.
        vol.Optional(
            CONF_NIGHT_ENTITY, description={"suggested_value": defaults.get(CONF_NIGHT_ENTITY)}
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["schedule", "input_boolean", "binary_sensor"])
        ),
    }


def _tuning_schema(defaults: dict[str, Any]) -> dict:
    return {
        vol.Required(CONF_KP, default=defaults.get(CONF_KP, DEFAULT_KP)): _number(0, 10, 0.1),
        vol.Required(CONF_KI, default=defaults.get(CONF_KI, DEFAULT_KI)): _number(0, 10, 0.1),
        vol.Required(CONF_MAX_BOOST, default=defaults.get(CONF_MAX_BOOST, DEFAULT_MAX_BOOST)):
            _number(0, 15, 0.5, "°C"),
        vol.Required(CONF_MAX_CUT, default=defaults.get(CONF_MAX_CUT, DEFAULT_MAX_CUT)):
            _number(0, 10, 0.5, "°C"),
        vol.Required(CONF_TRV_STEP, default=defaults.get(CONF_TRV_STEP, DEFAULT_TRV_STEP)):
            _number(0.1, 1, 0.1, "°C"),
        vol.Required(CONF_INTERVAL, default=defaults.get(CONF_INTERVAL, DEFAULT_INTERVAL)):
            _number(1, 30, 1, "min"),
    }


class SmartTRVConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                **_entities_schema({}),
                **_tuning_schema({}),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SmartTRVOptionsFlow()


class SmartTRVOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # A cleared field is left out of user_input; store None so it overrides entry.data.
            user_input.setdefault(CONF_NIGHT_ENTITY, None)
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema({**_entities_schema(current), **_tuning_schema(current)})
        return self.async_show_form(step_id="init", data_schema=schema)

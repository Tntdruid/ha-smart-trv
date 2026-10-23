"""Climate entity tests with a fake TV02."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

USER_INPUT = {
    "name": "Stue",
    "room_sensor": "sensor.stue_temperatur",
    "trvs": ["climate.tv02_stue"],
    "windows": ["binary_sensor.stue_vindue"],
    "kp": 3.0,
    "ki": 1.0,
    "max_boost": 6.0,
    "max_cut": 3.0,
    "trv_step": 0.5,
    "interval": 5,
    "window_open_delay": 0,  # react at once in these tests; delays are in test_window_delay.py
    "window_close_delay": 0,
}
ENTITY = "climate.stue"


@pytest.fixture
def trv_calls():
    """Record what Smart TRV sends to the TV02 instead of calling a real device."""
    calls = []

    async def record(self, service, entity_id, **data):
        calls.append((service, entity_id, data))

    with patch("custom_components.smart_trv.climate.SmartTRVClimate._call", record):
        yield calls


def last(calls, service):
    return next((d for s, _, d in reversed(calls) if s == service), None)


def set_trv(hass: HomeAssistant, state="heat", setpoint=22.0, local=23.0, preset="auto"):
    hass.states.async_set(
        "climate.tv02_stue",
        state,
        {
            "temperature": setpoint,
            "current_temperature": local,
            "preset_mode": preset,
            "preset_modes": ["auto", "manual", "holiday"],
            "hvac_modes": ["off", "heat"],
        },
    )


async def setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    hass.states.async_set("sensor.stue_temperatur", "21.5", {"device_class": "temperature"})
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    set_trv(hass)
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT, title="Stue")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_pushes_setpoint_and_manual_preset(hass: HomeAssistant, trv_calls) -> None:
    await setup_entry(hass)

    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": 22}, blocking=True
    )
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes["current_temperature"] == 21.5
    # room 0.5 below target, TRV reads 1.5 above room: setpoint must be well above 22
    assert state.attributes["trv_setpoint"] >= 23.5
    sent = last(trv_calls, "set_temperature")
    assert sent["temperature"] == state.attributes["trv_setpoint"]
    assert sent["temperature"] % 0.5 == 0
    assert last(trv_calls, "set_preset_mode") == {"preset_mode": "manual"}


async def test_window_turns_trv_off(hass: HomeAssistant, trv_calls) -> None:
    await setup_entry(hass)

    hass.states.async_set("binary_sensor.stue_vindue", "on")
    await hass.async_block_till_done()
    assert last(trv_calls, "set_hvac_mode") == {"hvac_mode": "off"}
    assert hass.states.get(ENTITY).attributes["hvac_action"] == "off"

    set_trv(hass, state="off")
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    await hass.async_block_till_done()
    assert last(trv_calls, "set_hvac_mode") == {"hvac_mode": "heat"}


async def test_sensor_unavailable_keeps_running(hass: HomeAssistant, trv_calls) -> None:
    await setup_entry(hass)

    hass.states.async_set("sensor.stue_temperatur", "unavailable")
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == "heat"
    assert state.attributes["current_temperature"] is None


async def test_reset_integral_service(hass: HomeAssistant, trv_calls) -> None:
    await setup_entry(hass)

    await hass.services.async_call("smart_trv", "reset_integral", {"entity_id": ENTITY}, blocking=True)
    await hass.async_block_till_done()
    assert "pi_integral" in hass.states.get(ENTITY).attributes

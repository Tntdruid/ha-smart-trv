"""Tuya TRV602 (Zigbee2MQTT): no hvac off, "off" is a preset, and it reports running_state."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .test_climate import ENTITY, USER_INPUT, last, trv_calls  # noqa: F401 - fixture

TRV = "climate.trv602_stue"


def set_trv602(hass: HomeAssistant, preset="auto", action="idle", local=21.0, setpoint=20.0, presets=None):
    hass.states.async_set(
        TRV,
        "heat",
        {
            "hvac_modes": ["heat"],
            "preset_modes": presets if presets is not None else ["auto", "manual", "off", "on"],
            "preset_mode": preset,
            "hvac_action": action,
            "current_temperature": local,
            "temperature": setpoint,
            "min_temp": 5,
            "max_temp": 35,
        },
    )


async def setup_trv602(hass: HomeAssistant, **trv) -> None:
    hass.states.async_set("sensor.stue_temperatur", "21.5")
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    set_trv602(hass, **trv)
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT | {"trvs": [TRV]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": 22}, blocking=True
    )
    await hass.async_block_till_done()


async def test_controls_without_hvac_modes(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    await setup_trv602(hass)
    assert last(trv_calls, "set_hvac_mode") is None  # it has no off/heat to switch
    assert last(trv_calls, "set_preset_mode") == {"preset_mode": "manual"}
    assert last(trv_calls, "set_temperature")["temperature"] > 22


async def test_window_uses_off_preset(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    await setup_trv602(hass, preset="manual")

    hass.states.async_set("binary_sensor.stue_vindue", "on")
    await hass.async_block_till_done()
    assert last(trv_calls, "set_preset_mode") == {"preset_mode": "off"}
    assert last(trv_calls, "set_hvac_mode") is None

    set_trv602(hass, preset="off")
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    await hass.async_block_till_done()
    assert last(trv_calls, "set_preset_mode") == {"preset_mode": "manual"}


async def test_window_falls_back_to_lowest_setpoint(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    await setup_trv602(hass, presets=[])
    hass.states.async_set("binary_sensor.stue_vindue", "on")
    await hass.async_block_till_done()
    assert last(trv_calls, "set_temperature") == {"temperature": 5}


async def test_status_trusts_running_state(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    # The TRV reads below our setpoint, but says it is idle: believe the TRV.
    await setup_trv602(hass, preset="manual", action="idle", local=21.0)
    assert hass.states.get("sensor.stue_status").state == "idle"

    set_trv602(hass, preset="manual", action="heating", local=21.0)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.stue_status").state == "heating"

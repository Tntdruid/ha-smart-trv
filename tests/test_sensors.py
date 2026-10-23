"""Diagnostic sensors follow the controller."""

from homeassistant.core import HomeAssistant

from .test_climate import ENTITY, setup_entry, trv_calls  # noqa: F401 - fixture


async def test_sensors_show_what_it_does(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    await setup_entry(hass)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": 22}, blocking=True
    )
    await hass.async_block_till_done()

    climate = hass.states.get(ENTITY)
    assert hass.states.get("sensor.stue_trv_setpoint").state == str(
        climate.attributes["trv_setpoint"]
    )
    assert float(hass.states.get("sensor.stue_trv_temperature").state) == 23.0
    assert float(hass.states.get("sensor.stue_error").state) == 0.5
    assert float(hass.states.get("sensor.stue_p_term").state) == 1.5
    assert hass.states.get("sensor.stue_integral").state not in ("unknown", "unavailable")

    status = hass.states.get("sensor.stue_status")
    assert status.state == "heating"  # TRV reads 23.0, setpoint is higher
    assert "0,5 °C under målet" in status.attributes["explanation"]

    hass.states.async_set("binary_sensor.stue_vindue", "on")
    await hass.async_block_till_done()
    status = hass.states.get("sensor.stue_status")
    assert status.state == "window_open"
    assert status.attributes["explanation"].startswith("Vindue åbent")


async def test_leftover_calibration_is_not_learned(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    """The user's real case: target 22.5, room 21.8, TV02 reads 16.1 (BT left -5 °C calibration)."""
    from .test_climate import set_trv

    await setup_entry(hass)
    set_trv(hass, local=16.1)
    hass.states.async_set("sensor.stue_temperatur", "21.8")
    await hass.services.async_call("smart_trv", "reset_integral", {"entity_id": ENTITY}, blocking=True)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": 22.5}, blocking=True
    )
    await hass.async_block_till_done()

    assert float(hass.states.get("sensor.stue_integral").state) >= 0
    explanation = hass.states.get("sensor.stue_status").attributes["explanation"]
    assert "5,7 °C koldere end rummet" in explanation
    assert "local_temperature_calibration" in explanation


async def test_per_trv_temperatures_with_two_trvs(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from .test_climate import USER_INPUT

    hass.states.async_set("sensor.stue_temperatur", "21.1")
    hass.states.async_set("climate.a", "heat", {"current_temperature": 22.1, "temperature": 22})
    hass.states.async_set("climate.b", "heat", {"current_temperature": 20.1, "temperature": 22})
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT | {"trvs": ["climate.a", "climate.b"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    trv = hass.states.get("sensor.stue_trv_temperature")
    assert float(trv.state) == 21.1  # the average
    assert trv.attributes["climate.a"] == 22.1 and trv.attributes["climate.b"] == 20.1
    assert "i snit 21,1 °C (22,1 °C, 20,1 °C)" in hass.states.get("sensor.stue_status").attributes["explanation"]

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


async def test_sensor_noise_does_not_move_the_valve(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    """The 'opens and closes all the time' report: noisy room readings must not chatter the TRV."""
    import random
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    await setup_trv602(hass, preset="manual", local=22.5, setpoint=23.0)
    rnd = random.Random(3)

    # Readings between control runs only update the display.
    sent_before = sum(1 for s, _, _ in trv_calls if s == "set_temperature")
    for _ in range(20):
        hass.states.async_set("sensor.stue_temperatur", f"{21.95 + rnd.uniform(-0.1, 0.1):.2f}")
        await hass.async_block_till_done()
    assert sum(1 for s, _, _ in trv_calls if s == "set_temperature") == sent_before

    # 6 hours of noisy readings every minute, controller on its 5 min timer.
    setpoints = []
    for minute in range(6 * 60):
        freezer.tick(timedelta(minutes=1))
        hass.states.async_set("sensor.stue_temperatur", f"{21.95 + rnd.uniform(-0.1, 0.1):.2f}")
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        setpoints.append(hass.states.get(ENTITY).attributes["trv_setpoint"])
    changes = sum(1 for a, b in zip(setpoints, setpoints[1:]) if a != b)
    assert changes <= 6, f"TRV setpoint changed {changes} times in 6 h"


async def test_warns_when_trv_refuses_setpoint(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    """The user's TRV602 had max_temperature 23 and stayed on 22 while Smart TRV sent 23.5."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    # No hvac_action reported, so status is guessed from the setpoints.
    hass.states.async_set("sensor.stue_temperatur", "21.2")
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    set_trv602(hass, preset="manual", local=21.6, setpoint=22.0)
    hass.states.async_set(TRV, "heat", {**hass.states.get(TRV).attributes, "hvac_action": None})
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT | {"trvs": [TRV]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": 22}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["trv_setpoint"] > 23  # what we want

    for _ in range(4):  # 20 min: past the 10 min resend; the TRV keeps reporting 22
        freezer.tick(timedelta(minutes=5))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()

    explanation = hass.states.get("sensor.stue_status").attributes["explanation"]
    assert f"{TRV} står stadig på 22,0 °C" in explanation
    assert "max_temperature" in explanation
    # Status guess must use the setpoint the TRV really has (22), not the refused 23.5+:
    # reading 22.1 above 22 means its valve is closed.
    set_trv602(hass, preset="manual", local=22.1, setpoint=22.0)
    hass.states.async_set(TRV, "heat", {**hass.states.get(TRV).attributes, "hvac_action": None})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.stue_status").state == "idle"


async def test_trv_staying_higher_is_not_a_warning(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    """Stue on 24 Oct: TRV602 showed 25.5 while Smart TRV had sent 25.0. Harmless, no warning."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    await setup_trv602(hass, preset="manual", local=21.4, setpoint=30.0)  # far above anything we send
    for _ in range(4):
        freezer.tick(timedelta(minutes=5))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
    assert "står stadig på" not in hass.states.get("sensor.stue_status").attributes["explanation"]


async def test_trv_reporting_auto_is_left_alone(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    """Stue on 24 Oct: TRV602 reports system_mode auto in preset manual. Smart TRV forced
    "heat" every 5 min and the logbook flipped Opvarmning/Auto all day."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    hass.states.async_set("sensor.stue_temperatur", "21.4")
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    attrs = {
        "hvac_modes": ["auto", "heat", "off"],
        "preset_modes": ["auto", "manual", "off", "on"],
        "preset_mode": "manual",
        "current_temperature": 21.6,
        "temperature": 25.5,
        "min_temp": 5,
        "max_temp": 35,
    }
    hass.states.async_set(TRV, "auto", attrs)
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT | {"trvs": [TRV]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for _ in range(12):  # one hour of control runs
        freezer.tick(timedelta(minutes=5))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
    assert last(trv_calls, "set_hvac_mode") is None
    assert last(trv_calls, "set_preset_mode") is None  # already manual

    hass.states.async_set("binary_sensor.stue_vindue", "on")
    await hass.async_block_till_done()
    assert last(trv_calls, "set_preset_mode") == {"preset_mode": "off"}
    assert last(trv_calls, "set_hvac_mode") is None

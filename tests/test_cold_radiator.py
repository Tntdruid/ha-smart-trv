"""The 21-22 Oct case: TRV asked for full heat all night, but the radiator stays cold."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.smart_trv.controller import PIController

from .test_climate import ENTITY, set_trv, setup_entry, trv_calls  # noqa: F401 - fixture


def test_no_learning_while_valve_is_fully_open() -> None:
    pi = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0)
    for _ in range(12 * 8):  # 8 hours, 5 min steps; TRV reads 21 (cold radiator), room 21.5
        pi.update(22.0, 21.5, 5 / 60, trv_temp=21.0)
    assert pi.valve_saturated
    assert pi.integral == 0.0

    # Same night without the TRV reading: the old behaviour winds up.
    old = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0)
    for _ in range(12 * 8):
        old.update(22.0, 21.5, 5 / 60)
    assert old.integral > 2


def test_still_learns_when_trv_is_regulating() -> None:
    pi = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0)
    for _ in range(12 * 2):  # TRV reads close to its setpoint: valve is part open, keep learning
        pi.update(22.0, 21.7, 5 / 60, trv_temp=23.5)
    assert not pi.valve_saturated
    assert pi.integral > 0.5


async def test_warns_when_radiator_stays_cold(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_entry(hass)
    set_trv(hass, local=21.0)
    hass.states.async_set("sensor.stue_temperatur", "21.5")
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": 22.0}, blocking=True
    )
    await hass.async_block_till_done()
    start = float(hass.states.get("sensor.stue_integral").state)

    for _ in range(30):  # 2.5 hours
        freezer.tick(timedelta(minutes=5))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()

    explanation = hass.states.get("sensor.stue_status").attributes["explanation"]
    assert "radiatoren bliver ikke varm" in explanation
    assert float(hass.states.get("sensor.stue_integral").state) == start  # didn't wind up

"""Away and holiday, summer with valve exercise, learning from the sun, and heating time."""

from datetime import timedelta

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.smart_trv.controller import PIController
from custom_components.smart_trv.learning import SunProfile

from .test_climate import ENTITY, USER_INPUT, set_trv, trv_calls  # noqa: F401 - fixture
from .test_smart_features import OUTDOOR, set_target, setup_room, tick

ZONE = "zone.home"
RETURN = "input_datetime.hjem_fra_ferie"


def attrs(hass):
    return hass.states.get(ENTITY).attributes


def explanation(hass) -> str:
    return hass.states.get("sensor.stue_status").attributes["explanation"]


def local(hour: float):
    return dt_util.start_of_local_day() + timedelta(hours=hour)


# ------------------------------------------------------------------- away and holiday


async def test_nobody_home_lowers_to_the_away_temperature(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    hass.states.async_set(ZONE, "2")
    await setup_room(hass, presence=ZONE)
    await set_target(hass, 22.0)

    hass.states.async_set(ZONE, "0")
    await hass.async_block_till_done()
    assert attrs(hass)["temperature"] == 22  # a quick trip out changes nothing

    await tick(hass, freezer, 35)
    assert attrs(hass)["temperature"] == 17 and attrs(hass)["away"] is True
    assert explanation(hass).startswith("🏠 Ingen hjemme")

    hass.states.async_set(ZONE, "1")
    await hass.async_block_till_done()
    assert attrs(hass)["temperature"] == 22 and attrs(hass)["away"] is False


async def test_away_temperature_can_be_changed(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    hass.states.async_set(ZONE, "0")
    await setup_room(hass, presence=ZONE)
    await tick(hass, freezer, 35)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.stue_away_temperature", "value": 15}, blocking=True
    )
    await hass.async_block_till_done()
    assert attrs(hass)["temperature"] == 15


async def test_holiday_warms_up_in_time_for_the_return(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    back = dt_util.utcnow() + timedelta(hours=10)
    hass.states.async_set(RETURN, dt_util.as_local(back).strftime("%Y-%m-%d %H:%M:%S"))
    hass.states.async_set(ZONE, "0")
    await setup_room(hass, presence=ZONE, return_time=RETURN, room="17.0")
    await set_target(hass, 22.0)
    await tick(hass, freezer, 35)
    assert attrs(hass)["temperature"] == 17 and attrs(hass)["preheating"] is False
    assert explanation(hass).startswith("🧳 Ferie")

    # 17 -> 22 °C at the default 1 °C/h takes about 6 h: preheat starts in time.
    for _ in range(9):
        await tick(hass, freezer, 30)
    assert attrs(hass)["preheating"] is True and attrs(hass)["temperature"] == 22
    assert "når I kommer hjem" in explanation(hass)

    # The return time passes before anyone is home: keep it warm.
    while dt_util.utcnow() < back + timedelta(minutes=10):
        await tick(hass, freezer, 30)
    assert attrs(hass)["temperature"] == 22 and attrs(hass)["away"] is False


async def test_no_presence_entity_means_always_home(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_room(hass)
    await set_target(hass, 22.0)
    await tick(hass, freezer, 60)
    assert attrs(hass)["temperature"] == 22 and attrs(hass)["away"] is False


# ------------------------------------------------------------------- summer


async def test_summer_turns_heating_off_and_back_on(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    freezer.move_to(local(0))
    hass.states.async_set(OUTDOOR, "20.0")
    await setup_room(hass, outdoor_sensor=OUTDOOR)
    for _ in range(46):  # 23 h of warm weather: not yet
        await tick(hass, freezer, 30)
    assert attrs(hass)["summer"] is False
    for _ in range(4):
        await tick(hass, freezer, 30)
    assert attrs(hass)["summer"] is True
    assert attrs(hass)["hvac_action"] == "off"
    assert hass.states.get("sensor.stue_status").state == "off"
    assert explanation(hass).startswith("☀️ Sommer")
    assert ("set_hvac_mode", "climate.tv02_stue", {"hvac_mode": "off"}) in trv_calls

    set_trv(hass, state="off")
    hass.states.async_set(OUTDOOR, "8.0")
    for _ in range(40):  # it turns cold: heating season again within a day
        await tick(hass, freezer, 30)
        set_trv(hass, state="off") if attrs(hass)["summer"] else None
    assert attrs(hass)["summer"] is False
    assert trv_calls[-10:] and ("set_hvac_mode", "climate.tv02_stue", {"hvac_mode": "heat"}) in trv_calls


async def test_summer_needs_an_outdoor_sensor_and_can_be_turned_off(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    hass.states.async_set(OUTDOOR, "25.0")
    await setup_room(hass, outdoor_sensor=OUTDOOR, summer_off=False)
    for _ in range(50):
        await tick(hass, freezer, 30)
    assert attrs(hass)["summer"] is False


async def test_valves_are_exercised_once_a_week_in_summer(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    freezer.move_to(local(11))
    mock_restore_cache(hass, [State(ENTITY, "heat", {
        "day_temperature": 21.0, "summer": True, "outdoor_24h": 20.0,
    })])
    hass.states.async_set(OUTDOOR, "20.0")
    await setup_room(hass, outdoor_sensor=OUTDOOR)
    opened = [c for c in trv_calls if c[0] == "set_temperature" and c[2]["temperature"] == 30]
    assert len(opened) == 1
    assert "🔧" in explanation(hass)

    await tick(hass, freezer, 15)  # exercise over: closed again
    assert trv_calls[-1] == ("set_hvac_mode", "climate.tv02_stue", {"hvac_mode": "off"})
    assert "🔧" not in explanation(hass)

    freezer.tick(timedelta(days=1))
    await tick(hass, freezer)
    assert len([c for c in trv_calls if c[0] == "set_temperature" and c[2]["temperature"] == 30]) == 1

    freezer.tick(timedelta(days=6, minutes=10))
    await tick(hass, freezer)
    assert len([c for c in trv_calls if c[0] == "set_temperature" and c[2]["temperature"] == 30]) == 2


# ------------------------------------------------------------------- sun


def test_sun_profile_turns_down_an_hour_ahead() -> None:
    sun = SunProfile()
    for _ in range(12):  # an hour at 15:00, 0.5 °C over target in full sun
        sun.learn(15.0, 0.5, 1.0, 5 / 60)
    assert sun.at(15.0) > 0.25
    assert sun.reduction(14.5, 1.0) == round(sun.at(15.0), 2)  # applied half an hour earlier
    assert sun.reduction(14.5, 0.0) == 0.0  # cloudy: nothing
    assert sun.reduction(14.5, 0.5) < sun.reduction(14.5, 1.0)
    before = sun.at(15.0)
    sun.learn(15.0, 0.5, 1.0, 5 / 60, can_cut=False)  # TRV was shut already: nothing to gain
    assert sun.at(15.0) == before
    for _ in range(100):  # then the room sits under target in the sun: turn down less
        sun.learn(15.0, -0.5, 1.0, 5 / 60)
    assert sun.at(15.0) == 0.0


def run_sunny_days(learn_sun: bool, sun_gain: float, days: int = 14) -> tuple[float, float, float]:
    """A room the sun warms 13-17 (sunny 12-17) every day, regulated by the real controller.

    Returns, over the last 4 days 10-20: mean |error|, highest and lowest error.
    """
    sun = SunProfile()
    pi = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0, step=0.5, hysteresis=0.5)
    room, rad, setpoint = 21.0, 0.3, 21.0
    history = []
    errors = []
    for day in range(days):
        for minute in range(1440):
            hour = minute / 60
            shine = 1.0 if 12 <= hour < 17 else 0.0
            trv = room + 0.5 + 2.5 * rad
            if minute % 5 == 0:
                cut = sun.reduction(hour, shine) if learn_sun else 0.0
                setpoint = pi.update(
                    21.0, room, 5 / 60, trv, -cut, learn=not (learn_sun and shine and room > 21.0)
                )
                if learn_sun and len(history) >= 6:
                    sun_then, shut_then = history[-6]
                    sun.learn(hour, room - 21.0, sun_then, 5 / 60, not shut_then)
                history.append((shine, pi.valve_saturated and pi.error < 0))
            valve = max(0.0, min(1.0, (setpoint - trv) / 0.5))
            rad += (valve - rad) / 20
            gain = sun_gain if 13 <= hour < 17 else 0.0
            room += (3.0 * rad - 0.12 * (room - 5.0) + gain) / 60
            if day >= days - 4 and 10 <= hour < 20:
                errors.append(room - 21.0)
    return sum(abs(e) for e in errors) / len(errors), max(errors), min(errors)


def test_sun_profile_keeps_a_sunny_room_closer_to_target() -> None:
    for gain in (1.0, 2.0):
        mean_off, peak_off, low_off = run_sunny_days(False, gain)
        mean_on, peak_on, low_on = run_sunny_days(True, gain)
        assert mean_on < mean_off * 0.75
        assert peak_on < peak_off
        assert low_on >= low_off - 0.02  # not by leaving the room cold


async def test_sunny_weather_turns_down_ahead_of_the_sun(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    freezer.move_to(local(14.5))  # half an hour before the sun's 15:00 heat
    profile = [0.0] * 24
    profile[15] = 1.0
    mock_restore_cache(hass, [State(ENTITY, "heat", {"day_temperature": 21.5, "sun_profile": profile})])
    hass.states.async_set("sun.sun", "above_horizon")
    hass.states.async_set("weather.forecast_home", "sunny")
    await setup_room(hass)
    assert attrs(hass)["sun_reduction"] == 1.0
    assert hass.states.get("sensor.stue_sun_reduction").state == "1.0"
    assert "− sol 1,0 °C" in explanation(hass)

    hass.states.async_set("weather.forecast_home", "cloudy")
    await tick(hass, freezer)
    assert attrs(hass)["sun_reduction"] == 0.0


async def test_sun_learning_can_be_turned_off(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    freezer.move_to(local(14.5))  # half an hour before the sun's 15:00 heat
    profile = [0.0] * 24
    profile[15] = 1.0
    mock_restore_cache(hass, [State(ENTITY, "heat", {"day_temperature": 21.5, "sun_profile": profile})])
    hass.states.async_set("sun.sun", "above_horizon")
    hass.states.async_set("weather.forecast_home", "sunny")
    await setup_room(hass, sun_learning=False)
    assert attrs(hass)["sun_reduction"] == 0.0


# ------------------------------------------------------------------- heating time


async def test_heating_time_is_counted(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    freezer.move_to(local(8))
    await setup_room(hass, trv_state=None)
    set_trv(hass, local=20.0, setpoint=24.0)  # TV02 reads under its setpoint: heating
    await set_target(hass, 22.0)
    for _ in range(12):  # an hour
        await tick(hass, freezer)
    today = float(hass.states.get("sensor.stue_heating_today").state)
    total = float(hass.states.get("sensor.stue_heating_total").state)
    assert 0.9 <= today <= 1.1 and abs(total - today) < 0.01


async def test_heating_today_starts_over_at_midnight(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    freezer.move_to(local(23.5))
    mock_restore_cache(hass, [State(ENTITY, "heat", {
        "day_temperature": 22.0, "heating_hours_today": 4.0, "heating_hours_total": 50.0,
        "heating_day": dt_util.as_local(dt_util.utcnow()).date().isoformat(),
    })])
    await setup_room(hass, trv_state=None)
    set_trv(hass, local=20.0, setpoint=24.0)
    await tick(hass, freezer)
    await tick(hass, freezer)
    assert float(hass.states.get("sensor.stue_heating_today").state) > 4.0
    for _ in range(8):  # past midnight
        await tick(hass, freezer)
    assert float(hass.states.get("sensor.stue_heating_today").state) < 0.5
    assert float(hass.states.get("sensor.stue_heating_total").state) > 50.5

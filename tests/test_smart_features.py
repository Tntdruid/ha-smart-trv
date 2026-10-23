"""Preheat, outdoor compensation, TRV monitoring and auto-tuning."""

from datetime import timedelta

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.smart_trv.learning import AutoTuner, HeatRateLearner, preheat_hours

from .test_climate import ENTITY, USER_INPUT, set_trv, trv_calls  # noqa: F401 - fixture

SCHEDULE = "schedule.christian_nat_varme"
OUTDOOR = "sensor.ude_ude_temperatur"


async def setup_room(hass: HomeAssistant, **extra) -> MockConfigEntry:
    hass.states.async_set("sensor.stue_temperatur", extra.pop("room", "21.5"))
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    if "trv_state" not in extra:
        set_trv(hass)
    extra.pop("trv_state", None)
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT | extra)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def set_target(hass: HomeAssistant, temp: float) -> None:
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": temp}, blocking=True
    )
    await hass.async_block_till_done()


async def tick(hass: HomeAssistant, freezer, minutes: int = 5) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


# ------------------------------------------------------------------- learning (pure)


def test_heat_rate_is_learned_at_full_heat() -> None:
    rate = HeatRateLearner()
    for k in range(13):  # 1 hour, 5 min steps, warming 0.6 °C/h at full heat
        rate.observe(k * 5 / 60, 19.0 + 0.6 * k * 5 / 60, full_heat=True)
    assert rate.samples >= 1 and abs(rate.rate - 0.6) < 0.05
    rate.observe(2.0, 25.0, full_heat=False)  # not at full heat: ignored
    assert abs(rate.rate - 0.6) < 0.05


def test_preheat_hours() -> None:
    assert preheat_hours(1.0, 22.5, 22.0) == 0
    assert preheat_hours(1.0, 21.0, 22.0) == 1.2  # 1 °C at 1 °C/h, +20 % margin
    assert preheat_hours(0.1, 15.0, 22.0) == 6.0  # capped


def test_auto_tuner_calms_an_oscillating_room() -> None:
    tuner = AutoTuner(kp=3.0, ki=1.0)
    change = None
    for k in range(288):  # one day of 5 min steps swinging ±0.5 °C every 2 h
        e = 0.5 if (k // 12) % 2 == 0 else -0.5
        change = tuner.observe(e, 5 / 60, steady=True) or change
    assert change and "svingede" in change
    assert tuner.kp < 3.0 and tuner.ki < 1.0


def test_auto_tuner_pushes_a_sluggish_room() -> None:
    tuner = AutoTuner(kp=1.0, ki=0.3)
    for _ in range(288):
        tuner.observe(0.3, 5 / 60, steady=True)  # sits 0.3 °C below target all day
    assert tuner.kp > 1.0 and tuner.ki > 0.3


def test_auto_tuner_leaves_a_good_room_alone() -> None:
    tuner = AutoTuner(kp=3.0, ki=1.0)
    for k in range(288):
        tuner.observe(0.05 if k % 2 else -0.05, 5 / 60, steady=True)
    assert (tuner.kp, tuner.ki) == (3.0, 1.0)


def test_auto_tuner_needs_enough_data() -> None:
    tuner = AutoTuner(kp=3.0, ki=1.0)
    for _ in range(288):
        tuner.observe(0.5, 5 / 60, steady=False)  # e.g. valve fully open all day
    assert (tuner.kp, tuner.ki) == (3.0, 1.0)


# ------------------------------------------------------------------- in Home Assistant


async def test_colder_outside_raises_trv_setpoint(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    hass.states.async_set(OUTDOOR, "20.0")
    await setup_room(hass, outdoor_sensor=OUTDOOR, outdoor_gain=0.1)
    await set_target(hass, 22.0)
    mild = hass.states.get(ENTITY).attributes
    assert mild["outdoor_ff"] == 0.2

    hass.states.async_set(OUTDOOR, "-2.0")
    await tick(hass, freezer)
    cold = hass.states.get(ENTITY).attributes
    assert cold["outdoor_ff"] == 2.4
    assert cold["trv_setpoint"] >= mild["trv_setpoint"] + 2
    assert "udetemperatur 2,4 °C" in hass.states.get("sensor.stue_status").attributes["explanation"]


async def test_outdoor_added_later_does_not_jump(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    """An integral learned without outdoor compensation already holds that load."""
    mock_restore_cache(
        hass, [State(ENTITY, "heat", {"day_temperature": 22.0, "pi_integral": 3.0})]
    )
    hass.states.async_set(OUTDOOR, "2.0")
    await setup_room(hass, outdoor_sensor=OUTDOOR, outdoor_gain=0.1, room="22.0")
    attrs = hass.states.get(ENTITY).attributes
    assert attrs["outdoor_ff"] == 2.0
    assert abs(attrs["pi_integral"] - 1.0) < 0.05  # 3.0 - 2.0


async def test_preheat_starts_early_enough(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    hass.states.async_set(SCHEDULE, "off")
    await setup_room(hass, night_entity=SCHEDULE, room="19.5")
    await set_target(hass, 22.0)  # day target
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.stue_night_temperature", "value": 19}, blocking=True
    )

    # Night ends in 5 h: too early to preheat 2.5 °C at the default 1 °C/h (needs 3 h).
    end = dt_util.utcnow() + timedelta(hours=5)
    hass.states.async_set(SCHEDULE, "on", {"next_event": end})
    await hass.async_block_till_done()
    attrs = hass.states.get(ENTITY).attributes
    assert attrs["temperature"] == 19 and attrs["preheating"] is False

    # Night ends in 2 h: preheat now, aiming for the day target.
    end = dt_util.utcnow() + timedelta(hours=2)
    hass.states.async_set(SCHEDULE, "on", {"next_event": end})
    await hass.async_block_till_done()
    attrs = hass.states.get(ENTITY).attributes
    assert attrs["preheating"] is True and attrs["temperature"] == 22
    explanation = hass.states.get("sensor.stue_status").attributes["explanation"]
    assert explanation.startswith("☀️ Forvarmer: rummet skal være 22,0 °C kl.")

    # Room warming up must not switch it back to night (latched).
    hass.states.async_set("sensor.stue_temperatur", "21.8")
    hass.states.async_set(SCHEDULE, "on", {"next_event": end})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["preheating"] is True


async def test_preheat_can_be_turned_off(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    hass.states.async_set(SCHEDULE, "off")
    await setup_room(hass, night_entity=SCHEDULE, room="19.5", preheat=False)
    await set_target(hass, 22.0)
    hass.states.async_set(SCHEDULE, "on", {"next_event": dt_util.utcnow() + timedelta(hours=1)})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["preheating"] is False


async def test_offline_trv_is_a_problem(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    await setup_room(hass)
    assert hass.states.get("binary_sensor.stue_problem").state == "off"

    hass.states.async_set("climate.tv02_stue", "unavailable")
    await hass.async_block_till_done()
    problem = hass.states.get("binary_sensor.stue_problem")
    assert problem.state == "on"
    assert problem.attributes["climate.tv02_stue"] == "offline"
    assert "⚠️ climate.tv02_stue: offline." in hass.states.get("sensor.stue_status").attributes["explanation"]


async def test_low_battery_is_found_through_the_device(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    z2m = MockConfigEntry(domain="mqtt")
    z2m.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=z2m.entry_id, identifiers={("mqtt", "tv02_stue")}
    )
    reg = er.async_get(hass)
    reg.async_get_or_create("climate", "mqtt", "tv02", device_id=device.id, suggested_object_id="tv02_stue")
    reg.async_get_or_create(
        "sensor", "mqtt", "tv02_battery", device_id=device.id,
        suggested_object_id="tv02_stue_battery", original_device_class="battery",
    )
    hass.states.async_set("sensor.tv02_stue_battery", "71")
    await setup_room(hass)
    assert hass.states.get("binary_sensor.stue_problem").state == "off"

    hass.states.async_set("sensor.tv02_stue_battery", "15")  # only the battery changes
    await hass.async_block_till_done()
    problem = hass.states.get("binary_sensor.stue_problem")
    assert problem.state == "on"
    assert problem.attributes["climate.tv02_stue"] == "lavt batteri (15 %)"


async def test_silent_trv_is_a_problem(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_room(hass)
    await tick(hass, freezer, minutes=7 * 60)  # TRV state not touched for 7 h
    problem = hass.states.get("binary_sensor.stue_problem")
    assert problem.state == "on"
    assert problem.attributes["climate.tv02_stue"].startswith("ingen kontakt i 7 t")


async def test_tuned_gains_survive_restart(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    mock_restore_cache(
        hass,
        [State(ENTITY, "heat", {"kp": 2.5, "ki": 0.8, "tuned_from": [3.0, 1.0], "last_tuning": "x"})],
    )
    await setup_room(hass)
    attrs = hass.states.get(ENTITY).attributes
    assert (attrs["kp"], attrs["ki"]) == (2.5, 0.8)


async def test_changed_settings_reset_tuned_gains(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    mock_restore_cache(
        hass, [State(ENTITY, "heat", {"kp": 2.5, "ki": 0.8, "tuned_from": [2.0, 0.5]})]
    )
    await setup_room(hass)  # configured 3.0/1.0, tuned from 2.0/0.5 -> start over
    attrs = hass.states.get(ENTITY).attributes
    assert (attrs["kp"], attrs["ki"]) == (3.0, 1.0)

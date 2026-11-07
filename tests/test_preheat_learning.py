"""Smarter preheat: radiator warm-up time, outdoor temperature and learning from each morning."""

from datetime import timedelta

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.smart_trv.learning import HeatRateLearner, PreheatTiming, preheat_hours

from .test_climate import ENTITY, trv_calls  # noqa: F401 - fixture
from .test_smart_features import SCHEDULE, set_target, setup_room, tick

STEP = 5 / 60  # h


def warm_up(learner: HeatRateLearner, t0: float, room: float, dead: float, rate: float, outdoor=None):
    """Feed 3 h of full heat: nothing for `dead` hours, then warming at `rate`."""
    t = 0.0
    while t <= 3.0:
        r = room + max(0.0, t - dead) * rate
        learner.observe(t0 + t, r, True, outdoor)
        t += STEP
    learner.observe(t0 + t, r, False, outdoor)


# ------------------------------------------------------------------- pure learning


def test_radiator_warm_up_time_is_learned_from_a_cold_start() -> None:
    learner = HeatRateLearner()
    learner.observe(0.0, 19.0, False)  # valve shut for 2 h: the radiator is cold
    warm_up(learner, 2.0, 19.0, dead=0.5, rate=0.8)
    assert learner.dead_samples == 1 and abs(learner.dead_time - 0.5) < 0.15
    assert abs(learner.rate - 0.8) < 0.05  # the wait doesn't drag the rate down


def test_warm_radiator_teaches_no_warm_up_time() -> None:
    learner = HeatRateLearner()
    learner.observe(0.0, 21.0, False)
    warm_up(learner, 0.25, 21.0, dead=0.0, rate=0.8)  # valve shut only 15 min
    assert learner.dead_samples == 0 and learner.dead_time == 0.33


def test_colder_outside_warms_slower() -> None:
    learner = HeatRateLearner()
    day = 0.0
    for outdoor, rate in [(10, 1.0), (0, 0.6), (5, 0.8), (-2, 0.52), (8, 0.92), (2, 0.68)]:
        learner.observe(day, 19.0, False)
        warm_up(learner, day + 2, 19.0, dead=0.3, rate=rate, outdoor=outdoor)
        day += 24
    assert learner.rate_at(-5) < learner.rate_at(5) < learner.rate_at(12)
    assert abs(learner.rate_at(0) - 0.6) < 0.1 and abs(learner.rate_at(10) - 1.0) < 0.1
    # The fit survives a restart.
    again = HeatRateLearner(rate=learner.rate, samples=learner.samples)
    again.load(learner.to_dict())
    assert abs(again.rate_at(0) - learner.rate_at(0)) < 0.001
    assert abs(again.dead_time - learner.dead_time) < 0.001
    assert abs(learner.dead_time - 0.3) < 0.15


def test_same_weather_every_time_uses_the_plain_rate() -> None:
    learner = HeatRateLearner()
    for k in range(4):
        learner.observe(k * 24, 19.0, False)
        warm_up(learner, k * 24 + 2, 19.0, dead=0.3, rate=0.7, outdoor=5.0)
    assert learner.rate_at(-10) == learner.rate


def test_preheat_includes_the_warm_up_time() -> None:
    assert preheat_hours(1.0, 20.0, 22.0, dead_time=0.5, factor=1.0) == 2.5


def test_timing_learns_from_late_and_early_mornings() -> None:
    timing = PreheatTiming(factor=1.0)
    assert timing.learn(2.0, short_by=0.1, early_hours=0.1, rate=1.0) is None  # on time
    assert timing.learn(2.0, short_by=0.5, early_hours=0.0, rate=1.0) == ("late", 0.5)
    assert timing.factor > 1.1  # starts earlier
    late = timing.factor
    assert timing.learn(2.0, short_by=0.0, early_hours=1.0, rate=1.0) == ("early", 1.0)
    assert timing.factor < late  # starts later
    for _ in range(30):
        timing.learn(2.0, short_by=3.0, early_hours=0.0, rate=0.5)
    assert timing.factor == 2.0  # bounded


# ------------------------------------------------------------------- in Home Assistant


async def start_preheat(hass: HomeAssistant, hours_left: float = 2.0):
    hass.states.async_set(SCHEDULE, "off")
    await setup_room(hass, night_entity=SCHEDULE, room="19.5")
    await set_target(hass, 22.0)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.stue_night_temperature", "value": 19}, blocking=True
    )
    end = dt_util.utcnow() + timedelta(hours=hours_left)
    hass.states.async_set(SCHEDULE, "on", {"next_event": end})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["preheating"] is True
    return end


async def run_until(hass, freezer, end, room_at=None) -> None:
    """Tick to just past the night end; room_at(hours_left) gives the room temperature."""
    while dt_util.utcnow() < end:
        await tick(hass, freezer)
        left = (end - dt_util.utcnow()).total_seconds() / 3600
        if room_at is not None:
            hass.states.async_set("sensor.stue_temperatur", str(room_at(left)))
        if left <= 0:
            hass.states.async_set(SCHEDULE, "off", {"next_event": end + timedelta(hours=16)})
        await hass.async_block_till_done()
    await tick(hass, freezer)


async def test_late_morning_starts_earlier_next_time(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    end = await start_preheat(hass, 3.0)
    before = hass.states.get(ENTITY).attributes["preheat_factor"]
    # Warms too slowly (no faster than a radiator could, or it looks like a shower).
    await run_until(hass, freezer, end, room_at=lambda left: min(21.5, 19.5 + (3 - left) * 0.7))
    attrs = hass.states.get(ENTITY).attributes
    assert attrs["preheating"] is False
    assert attrs["preheat_factor"] > before
    assert attrs["last_preheat"].startswith("Forvarmningen kom 0,5 °C for sent")


async def test_early_morning_starts_later_next_time(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    end = await start_preheat(hass, 3.0)
    before = hass.states.get(ENTITY).attributes["preheat_factor"]
    # Warm an hour before the night ends.
    await run_until(hass, freezer, end, room_at=lambda left: min(22.0, 19.5 + (3 - left) * 1.3))
    attrs = hass.states.get(ENTITY).attributes
    assert attrs["preheat_factor"] < before
    assert attrs["last_preheat"].startswith("Rummet var varmt")


async def test_open_window_teaches_nothing(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    end = await start_preheat(hass)
    before = hass.states.get(ENTITY).attributes["preheat_factor"]
    hass.states.async_set("binary_sensor.stue_vindue", "on")
    await hass.async_block_till_done()
    await tick(hass, freezer, 5)  # past the window delay
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    await hass.async_block_till_done()
    await run_until(hass, freezer, end, room_at=lambda left: 20.0)
    attrs = hass.states.get(ENTITY).attributes
    assert attrs["preheat_factor"] == before and attrs["last_preheat"] is None


async def test_preheat_learning_survives_restart(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    model = {"dead_time": 0.6, "sw": 0, "sx": 0, "sy": 0, "sxx": 0, "sxy": 0, "dead_samples": 3}
    mock_restore_cache(hass, [State(ENTITY, "heat", {
        "temperature": 22, "heat_rate": 0.7, "heat_rate_samples": 5,
        "preheat_factor": 1.3, "preheat_learning": model, "last_preheat": "x",
    })])
    await setup_room(hass)
    attrs = hass.states.get(ENTITY).attributes
    assert attrs["preheat_factor"] == 1.3 and attrs["preheat_lead_minutes"] == 36
    assert attrs["heat_rate"] == 0.7 and attrs["last_preheat"] == "x"


def test_night_cooling_gives_the_weather_dependence() -> None:
    learner = HeatRateLearner(rate=0.8, samples=3)
    learner._add(5.0, 0.8)  # one warm-up measured at 5 °C outside
    t, room = 0.0, 22.0
    while t < 6:  # valve shut, room 17 °C above outside, losing 0.05 °C/h per °C
        learner.observe_cooling(t, room, True, 5.0)
        room -= 0.05 * (room - 5.0) * STEP
        t += STEP
    assert learner.loss is not None and abs(learner.loss - 0.05) < 0.01
    assert learner.rate_at(-5) < 0.8 < learner.rate_at(10)
    assert abs(learner.rate_at(-5) - (0.8 - 0.5)) < 0.1


async def test_preheat_learning_has_diagnostic_sensors(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    from homeassistant.helpers import entity_registry as er

    end = await start_preheat(hass, 3.0)
    assert hass.states.get("sensor.stue_preheat_lead").state == "20"
    assert hass.states.get("sensor.stue_heat_rate").state == "1.0"
    assert hass.states.get("sensor.stue_preheat_factor").state == "1.1"
    assert hass.states.get("sensor.stue_last_preheat").state == "unknown"
    reg = er.async_get(hass)
    for key in ("preheat_lead", "heat_rate", "preheat_factor", "last_preheat"):
        assert reg.async_get(f"sensor.stue_{key}").entity_category == "diagnostic"

    await run_until(hass, freezer, end, room_at=lambda left: min(21.5, 19.5 + (3 - left) * 0.7))
    assert hass.states.get("sensor.stue_last_preheat").state.startswith("Forvarmningen kom")
    assert float(hass.states.get("sensor.stue_preheat_factor").state) > 1.1

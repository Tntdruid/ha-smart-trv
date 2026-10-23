"""Window/door delays: a door you walk through must not turn the heating off."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from .test_climate import ENTITY, USER_INPUT, last, set_trv, trv_calls  # noqa: F401 - fixture

WINDOW = "binary_sensor.stue_vindue"


async def setup_delays(hass: HomeAssistant, open_delay: int, close_delay: int) -> None:
    hass.states.async_set("sensor.stue_temperatur", "21.5")
    hass.states.async_set(WINDOW, "off")
    set_trv(hass)
    data = USER_INPUT | {"window_open_delay": open_delay, "window_close_delay": close_delay}
    entry = MockConfigEntry(domain="smart_trv", data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def wait(hass: HomeAssistant, freezer, seconds: int) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def turned_off(calls) -> bool:
    return last(calls, "set_hvac_mode") == {"hvac_mode": "off"}


async def test_turns_off_only_after_open_delay(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_delays(hass, open_delay=60, close_delay=0)

    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    assert not turned_off(trv_calls)
    explanation = hass.states.get("sensor.stue_status").attributes["explanation"]
    assert explanation.startswith("🪟 Vindue/dør åben: slukker om 60 sek.")

    await wait(hass, freezer, 30)
    assert not turned_off(trv_calls)
    await wait(hass, freezer, 31)
    assert turned_off(trv_calls)
    assert hass.states.get("sensor.stue_status").state == "window_open"


async def test_walking_through_a_door_keeps_heating(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_delays(hass, open_delay=60, close_delay=0)

    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    await wait(hass, freezer, 20)
    hass.states.async_set(WINDOW, "off")
    await hass.async_block_till_done()
    await wait(hass, freezer, 120)
    assert not turned_off(trv_calls)
    assert "slukker om" not in hass.states.get("sensor.stue_status").attributes["explanation"]


async def test_resumes_after_close_delay(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_delays(hass, open_delay=0, close_delay=30)

    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    assert turned_off(trv_calls)
    set_trv(hass, state="off")

    hass.states.async_set(WINDOW, "off")
    await hass.async_block_till_done()
    assert turned_off(trv_calls)  # still waiting
    assert "varmen starter om 30 sek." in hass.states.get("sensor.stue_status").attributes["explanation"]

    await wait(hass, freezer, 31)
    assert last(trv_calls, "set_hvac_mode") == {"hvac_mode": "heat"}


async def test_window_open_at_startup_is_off_at_once(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    hass.states.async_set("sensor.stue_temperatur", "21.5")
    hass.states.async_set(WINDOW, "on")
    set_trv(hass)
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT | {"window_open_delay": 60})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert turned_off(trv_calls)

"""Valve that doesn't shut (Soveværelse) and sudden heat/humidity from a shower (Badeværelse)."""

from datetime import timedelta

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from .test_climate import ENTITY, USER_INPUT, set_trv, trv_calls  # noqa: F401 - fixture

ROOM = "sensor.stue_temperatur"


async def setup_room(hass: HomeAssistant, room: float, trv: float, integral: float = 1.2) -> None:
    mock_restore_cache(hass, [State(ENTITY, "heat", {"day_temperature": 20.5, "pi_integral": integral})])
    hass.states.async_set(ROOM, str(room))
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    set_trv(hass, local=trv, setpoint=21.5)
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def tick(hass: HomeAssistant, freezer, minutes: int = 5) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


def explanation(hass: HomeAssistant) -> str:
    return hass.states.get("sensor.stue_status").attributes["explanation"]


# ----------------------------------------------------------------- valve doesn't shut


async def test_bedroom_valve_does_not_close(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    """Soveværelse, 30 Oct: room 20.8 over target 20.5, TRV told 21.5 but reads 23.9 for hours."""
    await setup_room(hass, room=20.8, trv=23.9)
    for _ in range(30):  # 2.5 h, the radiator stays hot
        set_trv(hass, local=23.9, setpoint=21.5)
        await tick(hass, freezer)
    assert "ventilen lukker ikke helt" in explanation(hass)


async def test_valve_that_closes_is_fine(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_room(hass, room=20.8, trv=23.9)
    for k in range(30):  # radiator cools: the TRV reading drops 23.9 -> 22.4
        set_trv(hass, local=23.9 - 0.05 * k, setpoint=21.5)
        await tick(hass, freezer)
    assert "ventilen lukker ikke helt" not in explanation(hass)


async def test_sunny_room_is_not_a_leaking_valve(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    """Sun warms room and TRV alike: the TRV isn't notably warmer than the room."""
    await setup_room(hass, room=22.5, trv=22.8, integral=-1.0)
    for _ in range(30):
        set_trv(hass, local=22.8, setpoint=19.0)
        await tick(hass, freezer)
    assert "ventilen lukker ikke helt" not in explanation(hass)


# ----------------------------------------------------------------- shower pause


async def test_sudden_heat_pauses_learning(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    """Badeværelse: shower takes the room from 21.3 to 22.2 in 10 min."""
    await setup_room(hass, room=21.3, trv=22.0, integral=0.5)
    await tick(hass, freezer)
    for value in ("21.6", "21.9", "22.2"):
        freezer.tick(timedelta(minutes=3))
        hass.states.async_set(ROOM, value)
        await hass.async_block_till_done()
    assert explanation(hass).startswith("🚿 Pludselig varme eller fugt")

    frozen = hass.states.get(ENTITY).attributes["pi_integral"]
    for _ in range(10):  # 50 min: room above target, but nothing is learned from it
        await tick(hass, freezer)
    assert hass.states.get(ENTITY).attributes["pi_integral"] == frozen

    # Past the 60 min pause, with the room back near target and the TRV regulating again:
    # learning resumes.
    hass.states.async_set(ROOM, "20.7")
    set_trv(hass, local=21.0, setpoint=20.5)
    for _ in range(4):
        await tick(hass, freezer)
    assert "🚿" not in explanation(hass)
    assert hass.states.get(ENTITY).attributes["pi_integral"] != frozen


async def test_normal_heating_is_not_a_shower(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_room(hass, room=20.0, trv=21.0, integral=0.5)
    for k in range(12):  # 1 °C/h, the fastest a radiator realistically manages
        hass.states.async_set(ROOM, f"{20.0 + k * 1.0 / 12:.2f}")
        await tick(hass, freezer)
    assert "🚿" not in explanation(hass)


async def test_humidity_jump_on_the_room_sensor_device(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    """The SHT4x reports humidity too: a shower shows there before the room warms."""
    esphome = MockConfigEntry(domain="esphome")
    esphome.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=esphome.entry_id, identifiers={("esphome", "bad")}
    )
    reg = er.async_get(hass)
    reg.async_get_or_create("sensor", "esphome", "bad_t", device_id=device.id, suggested_object_id="stue_temperatur")
    reg.async_get_or_create(
        "sensor", "esphome", "bad_h", device_id=device.id,
        suggested_object_id="stue_fugt", original_device_class="humidity",
    )
    hass.states.async_set("sensor.stue_fugt", "55")
    await setup_room(hass, room=21.3, trv=22.0, integral=0.5)
    assert "🚿" not in explanation(hass)

    for value in ("60", "65"):
        freezer.tick(timedelta(minutes=4))
        hass.states.async_set("sensor.stue_fugt", value)
        await hass.async_block_till_done()
    assert explanation(hass).startswith("🚿 Pludselig varme eller fugt")


# ----------------------------------------------------------------- wood stove


async def light_stove(hass, freezer) -> float:
    """From 20.5 to 25 °C in an hour (day target 20.5), like the living room on 8 Nov."""
    room = 20.5
    for _ in range(12):
        room += 0.375
        hass.states.async_set(ROOM, str(room))
        await tick(hass, freezer)
    return room


async def cool_to(hass, freezer, start: float, end: float, hours: float) -> None:
    steps = int(hours * 12)
    for k in range(1, steps + 1):
        hass.states.async_set(ROOM, str(round(start + (end - start) * k / steps, 2)))
        await tick(hass, freezer)


def heat_source(hass) -> bool:
    return hass.states.get("binary_sensor.stue_heat_source").state == "on"


async def test_stove_pauses_learning_all_the_way_down(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_room(hass, room=20.5, trv=20.0, integral=1.2)
    assert not heat_source(hass)
    room = await light_stove(hass, freezer)
    assert heat_source(hass)
    text = explanation(hass)
    assert text.startswith("🔥 Ekstra varmekilde (fx brændeovn)") and "🚿" not in text
    integral = hass.states.get(ENTITY).attributes["pi_integral"]

    # 8 hours cooling down: far past the old 60 min pause.
    await cool_to(hass, freezer, room, 20.8, 8)
    assert heat_source(hass)
    assert hass.states.get(ENTITY).attributes["pi_integral"] == integral

    # Back at the target and staying there: learning again.
    await cool_to(hass, freezer, 20.8, 20.6, 1)
    assert not heat_source(hass)
    assert "🔥" not in explanation(hass)


async def test_shower_is_not_a_stove(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    esp = MockConfigEntry(domain="esphome")
    esp.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=esp.entry_id, identifiers={("esphome", "sht4x")}
    )
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "sensor", "esphome", "t", device_id=device.id, suggested_object_id="stue_temperatur"
    )
    reg.async_get_or_create(
        "sensor", "esphome", "h", device_id=device.id, original_device_class="humidity",
        suggested_object_id="stue_fugt",
    )
    hass.states.async_set("sensor.stue_fugt", "50")
    await setup_room(hass, room=20.5, trv=20.0)
    await tick(hass, freezer)
    hass.states.async_set("sensor.stue_fugt", "75")
    hass.states.async_set(ROOM, "21.3")  # 0.8 above the target, but humid
    await tick(hass, freezer)
    assert not heat_source(hass)
    assert "🚿" in explanation(hass)


async def test_sudden_heat_below_the_target_is_not_a_stove(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    await setup_room(hass, room=19.6, trv=20.0)
    await tick(hass, freezer)
    hass.states.async_set(ROOM, "20.3")
    await tick(hass, freezer)
    assert not heat_source(hass)


async def test_heat_source_survives_restart(hass: HomeAssistant, trv_calls, freezer) -> None:  # noqa: F811
    mock_restore_cache(hass, [State(ENTITY, "heat", {
        "day_temperature": 20.5, "pi_integral": 1.2, "heat_source": True,
    })])
    hass.states.async_set(ROOM, "24.0")
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    set_trv(hass, local=20.0, setpoint=21.5)
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer)
    assert heat_source(hass)


async def test_shower_without_humidity_sensor_fades_and_is_not_a_stove(
    hass: HomeAssistant, trv_calls, freezer  # noqa: F811
) -> None:
    await setup_room(hass, room=20.5, trv=20.0)
    await tick(hass, freezer)
    for room in ("20.8", "21.1", "21.4"):  # 0.9 warmer, then it stays there
        hass.states.async_set(ROOM, room)
        await tick(hass, freezer)
    for _ in range(14):
        await tick(hass, freezer)
    assert not heat_source(hass)

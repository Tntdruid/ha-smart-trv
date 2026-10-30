"""Night temperature per room, switched by the user's schedule.christian_nat_varme."""

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .test_climate import ENTITY, USER_INPUT, flow_input, set_trv, trv_calls  # noqa: F401 - fixture

SCHEDULE = "schedule.christian_nat_varme"
NUMBER = "number.stue_night_temperature"


async def setup_with_schedule(hass: HomeAssistant) -> MockConfigEntry:
    hass.states.async_set("sensor.stue_temperatur", "21.5")
    hass.states.async_set("binary_sensor.stue_vindue", "off")
    hass.states.async_set(SCHEDULE, "off")
    set_trv(hass)
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT | {"night_entity": SCHEDULE})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def set_target(hass: HomeAssistant, temp: float) -> None:
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": temp}, blocking=True
    )
    await hass.async_block_till_done()


async def test_schedule_switches_to_night_temperature(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    await setup_with_schedule(hass)
    await set_target(hass, 22.0)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": NUMBER, "value": 18.0}, blocking=True
    )
    await hass.async_block_till_done()
    day_setpoint = hass.states.get(ENTITY).attributes["trv_setpoint"]
    assert hass.states.get(ENTITY).attributes["temperature"] == 22.0

    hass.states.async_set(SCHEDULE, "on")
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.attributes["temperature"] == 18.0
    assert state.attributes["night_active"] is True
    assert state.attributes["trv_setpoint"] < day_setpoint
    assert hass.states.get("sensor.stue_status").attributes["explanation"].startswith("🌙")

    # Turning the thermostat at night changes the night temperature, not the day one.
    await set_target(hass, 18.5)
    assert float(hass.states.get(NUMBER).state) == 18.5
    assert hass.states.get(ENTITY).attributes["day_temperature"] == 22.0

    hass.states.async_set(SCHEDULE, "off")
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.attributes["temperature"] == 22.0
    assert state.attributes["night_active"] is False


async def test_without_schedule_night_is_ignored(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    hass.states.async_set("sensor.stue_temperatur", "21.5")
    set_trv(hass)
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await set_target(hass, 22.0)
    assert hass.states.get(ENTITY).attributes["night_active"] is False
    assert hass.states.get(NUMBER) is not None


async def test_options_can_clear_schedule(hass: HomeAssistant, hass_client, trv_calls) -> None:  # noqa: F811
    entry = await setup_with_schedule(hass)
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    resp = await client.post(
        "/api/config/config_entries/options/flow", json={"handler": entry.entry_id}
    )
    flow = await resp.json()
    fields = {f["name"]: f for f in flow["data_schema"]}
    assert fields["night_entity"]["description"]["suggested_value"] == SCHEDULE

    options = flow_input(USER_INPUT, drop_name=True)  # night_entity left out = cleared
    resp = await client.post(
        f"/api/config/config_entries/options/flow/{flow['flow_id']}", json=options
    )
    assert (await resp.json())["type"] == "create_entry"
    await hass.async_block_till_done()

    hass.states.async_set(SCHEDULE, "on")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["night_active"] is False

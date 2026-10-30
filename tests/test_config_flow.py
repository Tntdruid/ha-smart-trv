"""Config/options flow tests, run through the same HTTP API the frontend uses."""

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .test_climate import USER_INPUT, flow_input, setup_entry


async def test_flow_loads_and_creates_entry(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()

    resp = await client.post("/api/config/config_entries/flow", json={"handler": "smart_trv"})
    assert resp.status == 200, await resp.text()
    flow = await resp.json()
    assert flow["step_id"] == "user"

    resp = await client.post(
        f"/api/config/config_entries/flow/{flow['flow_id']}", json=flow_input(USER_INPUT)
    )
    assert resp.status == 200, await resp.text()
    result = await resp.json()
    assert result["type"] == "create_entry"
    assert result["title"] == "Stue"


async def test_options_flow_loads(hass: HomeAssistant, hass_client) -> None:
    entry = await setup_entry(hass)
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()

    resp = await client.post(
        "/api/config/config_entries/options/flow", json={"handler": entry.entry_id}
    )
    assert resp.status == 200, await resp.text()
    flow = await resp.json()

    resp = await client.post(
        f"/api/config/config_entries/options/flow/{flow['flow_id']}",
        json=flow_input(USER_INPUT | {"ki": 0.5}, drop_name=True),
    )
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["ki"] == 0.5


async def test_form_only_asks_about_the_house(hass: HomeAssistant, hass_client) -> None:
    """Control details are not settings any more; Kp/Ki etc. sit in a collapsed section."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    resp = await client.post("/api/config/config_entries/flow", json={"handler": "smart_trv"})
    fields = {f["name"]: f for f in (await resp.json())["data_schema"]}
    for removed in ("max_boost", "max_cut", "trv_step", "interval", "kp", "ki"):
        assert removed not in fields
    assert fields["advanced"]["type"] == "expandable"
    assert fields["advanced"]["expanded"] is False
    assert {f["name"] for f in fields["advanced"]["schema"]} == {"auto_tune", "kp", "ki", "outdoor_gain"}


async def test_old_stored_max_boost_is_ignored(hass: HomeAssistant) -> None:
    """The user had set max_boost 2; it must not limit the controller any more."""
    from unittest.mock import patch

    hass.states.async_set("sensor.stue_temperatur", "18.0")
    hass.states.async_set("climate.tv02_stue", "heat", {"current_temperature": 18.5, "temperature": 20})
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT | {"max_boost": 2.0})
    entry.add_to_hass(hass)
    with patch("custom_components.smart_trv.climate.SmartTRVClimate._call"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await hass.services.async_call(
            "climate", "set_temperature", {"entity_id": "climate.stue", "temperature": 22}, blocking=True
        )
        await hass.async_block_till_done()
    assert hass.states.get("climate.stue").attributes["trv_setpoint"] > 24  # not capped at 22 + 2

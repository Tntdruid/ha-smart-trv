"""Config/options flow tests, run through the same HTTP API the frontend uses."""

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .test_climate import USER_INPUT, setup_entry


async def test_flow_loads_and_creates_entry(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()

    resp = await client.post("/api/config/config_entries/flow", json={"handler": "smart_trv"})
    assert resp.status == 200, await resp.text()
    flow = await resp.json()
    assert flow["step_id"] == "user"

    resp = await client.post(
        f"/api/config/config_entries/flow/{flow['flow_id']}", json=USER_INPUT
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
        json={k: v for k, v in USER_INPUT.items() if k != "name"} | {"ki": 0.5},
    )
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["ki"] == 0.5

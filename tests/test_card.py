"""The integration serves the Smart TRV card and loads it on every dashboard."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.smart_trv import CARD_URL

from .test_climate import setup_entry, trv_calls  # noqa: F401 - fixture


async def test_card_is_served(hass: HomeAssistant, hass_client, trv_calls) -> None:  # noqa: F811
    assert await async_setup_component(hass, "http", {})
    await setup_entry(hass)
    client = await hass_client()

    resp = await client.get(CARD_URL)
    assert resp.status == 200
    body = await resp.text()
    assert 'customElements.define("smart-trv-card"' in body


async def test_card_is_auto_loaded_when_frontend_runs(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    hass.config.components.add("frontend")  # the real frontend needs the hass_frontend package
    with patch("homeassistant.components.frontend.add_extra_js_url") as add:
        await setup_entry(hass)
    add.assert_called_once()
    url = add.call_args.args[1]
    assert url.startswith(f"{CARD_URL}?v=")

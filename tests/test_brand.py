"""Home Assistant serves our own icon instead of "icon not available"."""

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_custom_components
from homeassistant.setup import async_setup_component

BRAND = Path(__file__).parents[1] / "custom_components" / "smart_trv" / "brand"


async def test_brand_icons_are_served(hass: HomeAssistant, hass_client) -> None:
    integration = (await async_get_custom_components(hass))["smart_trv"]
    assert integration.has_branding

    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    for image in ("icon.png", "icon@2x.png", "dark_icon.png", "dark_icon@2x.png"):
        resp = await client.get(f"/api/brands/integration/smart_trv/{image}")
        assert resp.status == 200, image
        assert await resp.read() == (BRAND / image).read_bytes(), image
    # No separate logo: HA falls back to the icon.
    resp = await client.get("/api/brands/integration/smart_trv/logo.png")
    assert await resp.read() == (BRAND / "icon.png").read_bytes()

"""The explanation follows Home Assistant's language: Danish for da, English otherwise."""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smart_trv.diagnostics_text import language

from .test_climate import ENTITY, setup_entry, trv_calls  # noqa: F401 - fixture


def test_language_choice() -> None:
    assert language("da") == "da"
    assert language("da-DK") == "da"
    assert language("en") == "en"
    assert language("de") == "en"  # no German texts: English
    assert language(None) == "en"


async def _explanation(hass: HomeAssistant, lang: str) -> str:
    hass.config.language = lang
    await setup_entry(hass)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": ENTITY, "temperature": 22}, blocking=True
    )
    await hass.async_block_till_done()
    return hass.states.get("sensor.stue_status").attributes["explanation"]


@pytest.mark.real_language
async def test_english(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    text = await _explanation(hass, "en")
    assert text.startswith("The room is 0.5 °C below target (21.5 °C of 22.0 °C).")
    assert "Learned offset" in text


@pytest.mark.real_language
async def test_danish(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    text = await _explanation(hass, "da")
    assert text.startswith("Rummet er 0,5 °C under målet (21,5 °C af 22,0 °C).")
    assert "Lært offset" in text


@pytest.mark.real_language
async def test_problem_text_follows_language(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    hass.config.language = "en"
    await setup_entry(hass)
    hass.states.async_set("climate.tv02_stue", "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.stue_problem").attributes["climate.tv02_stue"] == "offline"
    assert "⚠️ climate.tv02_stue: offline." in hass.states.get("sensor.stue_status").attributes["explanation"]

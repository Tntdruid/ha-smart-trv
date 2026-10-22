"""The dashboard generator template finds the real entities, whatever they are called."""

import os
from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .test_climate import USER_INPUT, setup_entry, trv_calls  # noqa: F401 - fixture

GENERATOR = Path(__file__).parents[1] / "dashboard" / "generate_dashboard.jinja"


def render(hass: HomeAssistant) -> str:
    return Template(GENERATOR.read_text(encoding="utf-8"), hass).async_render(parse_result=False)


def entity_ids(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "entity" and isinstance(value, str):
                yield value
            elif key == "entity_id" and isinstance(value, list):
                yield from value
            else:
                yield from entity_ids(value)
    elif isinstance(node, list):
        for item in node:
            yield from entity_ids(item)


async def test_no_rooms(hass: HomeAssistant) -> None:
    assert "No Smart TRV found" in render(hass)


async def test_generates_view_per_room(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    await setup_entry(hass)  # "Stue"
    other = MockConfigEntry(domain="smart_trv", data=USER_INPUT | {"name": "Smart TRV"}, title="x")
    other.add_to_hass(hass)
    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()

    dashboard = yaml.safe_load(render(hass))
    views = dashboard["views"]
    assert sorted(v["title"] for v in views) == ["Smart TRV", "Stue"]

    ids = list(entity_ids(dashboard))
    assert "climate.smart_trv" in ids and "sensor.smart_trv_status" in ids
    assert "sensor.stue_integral" in ids
    missing = [e for e in ids if hass.states.get(e) is None]
    assert not missing, missing

    stue = next(v for v in views if v["title"] == "Stue")
    markdown = next(c for s in stue["sections"] for c in s["cards"] if c["type"] == "markdown")
    assert markdown["content"] == (
        "**{{ state_translated('sensor.stue_status') }}**\n\n"
        "{{ state_attr('sensor.stue_status', 'explanation') }}"
    )



async def test_users_room_name(hass: HomeAssistant, trv_calls) -> None:  # noqa: F811
    hass.states.async_set("sensor.stue_temperatur", "21.5")
    entry = MockConfigEntry(domain="smart_trv", data=USER_INPUT | {"name": "Stue Varme Test"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    text = render(hass)
    if out := os.environ.get("SMART_TRV_WRITE_DASHBOARD"):
        Path(out).write_text(text + "\n", encoding="utf-8")
    ids = list(entity_ids(yaml.safe_load(text)))
    assert "climate.stue_varme_test" in ids
    assert "sensor.stue_varme_test_status" in ids
    assert not [e for e in ids if hass.states.get(e) is None]

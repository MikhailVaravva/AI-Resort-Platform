"""Integration test: build a Home Assistant package from the real reference project."""

import collections
from pathlib import Path

import yaml

from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.generators.ha_package import HomeAssistantPackage
from ai_resort_platform.generators.ha_yaml import package_to_yaml, write_package
from ai_resort_platform.homeassistant.builder import build_package

REFERENCE_VILLA = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "Reference-Villa"
    / "reference_villa.knxproj"
)


def _build() -> HomeAssistantPackage:
    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    return build_package(project)


def test_reference_villa_domain_distribution():
    package = _build()

    counts = collections.Counter(e.domain for e in package.entities)
    assert counts == {"switch": 12, "light": 13, "sensor": 8, "cover": 1}


def test_reference_villa_no_unique_id_collisions():
    package = _build()

    ids = (
        [e.unique_id for e in package.entities]
        + [s.unique_id for s in package.scenes]
        + [s.unique_id for s in package.scripts]
    )
    assert len(ids) == len(set(ids))


def test_reference_villa_scenes_and_scripts():
    package = _build()

    assert len(package.scenes) == 6
    assert len(package.scripts) == 6
    assert {s.scene_number for s in package.scenes} == {1, 2, 3, 4, 5, 6}
    assert all(s.address == "1/1/150" for s in package.scenes)


def test_reference_villa_scene_control_is_not_a_generic_entity():
    """The DPST-18-1 control point (1/1/150) only appears as each Scene's
    `address`, never as its own switch/sensor entity."""
    package = _build()

    addresses_in_entities = {v for e in package.entities for v in e.config.values()}
    assert "1/1/150" not in addresses_in_entities


def test_reference_villa_curtain_merged_into_one_cover():
    package = _build()

    covers = [e for e in package.entities if e.domain == "cover"]
    assert len(covers) == 1
    assert covers[0].config == {
        "move_long_address": "1/1/30",
        "stop_address": "1/1/31",
        "position_address": "1/1/32",
        "position_state_address": "1/1/33",
    }


def test_reference_villa_scaling_counter_does_not_become_a_light():
    """Regression: "Audio Play mode" uses dpt_main=5 (like brightness) but
    dpt_sub=10, not 1 - it must stay a sensor."""
    package = _build()
    by_name = {e.name: e for e in package.entities}

    assert by_name["Audio Play mode"].domain == "sensor"
    assert by_name["Audio Play mode"].config["type"] == "value1Ucount"


def test_reference_villa_dimmable_light_with_colour_temperature():
    package = _build()
    by_name = {e.name: e for e in package.entities}

    g1 = by_name["G1"]
    assert g1.domain == "light"
    assert g1.config == {
        "address": "1/1/0",
        "state_address": "1/1/1",
        "brightness_address": "1/1/2",
        "brightness_state_address": "1/1/3",
        "color_temperature_address": "1/1/4",
        "color_temperature_state_address": "1/1/5",
    }


def test_reference_villa_package_yaml_round_trips_via_existing_generator():
    """Confirms the existing generators/ha_yaml.py serialization is reused as-is."""
    package = _build()

    data = yaml.safe_load(package_to_yaml(package))

    assert set(data.keys()) == {"switch", "light", "sensor", "cover", "scene", "script"}
    assert len(data["light"]) == 13
    assert len(data["scene"]) == 6
    assert len(data["script"]) == 6


def test_reference_villa_writes_a_valid_yaml_file(tmp_path):
    package = _build()
    path = tmp_path / "hot_stone_villa.yaml"

    write_package(package, path)

    assert yaml.safe_load(path.read_text(encoding="utf-8"))


def test_reference_villa_package_is_stable_across_rebuilds():
    project = ETSProject.open(REFERENCE_VILLA, password="12345")

    first = build_package(project)
    second = build_package(project)

    assert [e.unique_id for e in first.entities] == [e.unique_id for e in second.entities]
    assert first == second

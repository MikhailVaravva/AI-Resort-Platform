"""Integration test: build a Home Assistant package from the real reference project."""

import collections
from pathlib import Path

import yaml

from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.generators.ha_package import HomeAssistantPackage
from ai_resort_platform.generators.ha_yaml import (
    dashboard_to_yaml,
    package_to_yaml,
    write_dashboard,
    write_package,
)
from ai_resort_platform.homeassistant.builder import (
    build_audio_module_package,
    build_dashboard,
    build_package,
)

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


def test_reference_villa_dashboard_covers_every_domain_present():
    package = _build()

    dashboard = build_dashboard(package)
    view = dashboard.views[0]
    card_titles = {c.title for c in view.cards}

    assert card_titles == {"Lights", "Sensors", "Switches", "Covers", "Scenes", "Scripts"}

    total_entities_in_cards = sum(len(c.entities) for c in view.cards)
    assert total_entities_in_cards == len(package.entities) + len(package.scenes) + len(
        package.scripts
    )


def test_reference_villa_dashboard_yaml_round_trips():
    package = _build()
    dashboard = build_dashboard(package)

    data = yaml.safe_load(dashboard_to_yaml(dashboard))

    assert data["title"] == "Villa A1"
    assert len(data["views"]) == 1


def test_reference_villa_writes_a_dashboard_file(tmp_path):
    package = _build()
    dashboard = build_dashboard(package)
    path = tmp_path / "villa_a1_dashboard.yaml"

    write_dashboard(dashboard, path)

    assert yaml.safe_load(path.read_text(encoding="utf-8"))


def test_reference_villa_audio_module_package_excludes_touch_panel_mirrors():
    """Verified against the real reference project: the BAB Audio Module
    (device "Audio Module A1") only owns 8 of the ~15 "Audio ..." group
    addresses - the rest (e.g. "Audio Volume status", "Audio Mute status",
    "Audio Play mode") are wired solely to the KNX Smart Touch S3 touch
    panel's own communication objects, not the module's."""
    project = ETSProject.open(REFERENCE_VILLA, password="12345")

    package = build_audio_module_package(project)

    by_id = {e.unique_id: e for e in package.entities}
    assert set(by_id) == {
        "villa_a1_audio_power",
        "villa_a1_audio_absolut_volume",
        "villa_a1_audio_mute",
        "villa_a1_audio_play_pause",
        "villa_a1_audio_next_prev",
        "villa_a1_audio_track_name_string88591",
        "villa_a1_audio_playlist_select_major_5_x",
    }
    assert by_id["villa_a1_audio_power"].config == {
        "address": "1/1/202",
        "state_address": "1/1/203",
    }
    # Wired only to the touch panel in the real project, so no state_address
    # is available on the module-scoped package for these:
    assert by_id["villa_a1_audio_mute"].config == {"address": "1/1/220"}
    assert by_id["villa_a1_audio_play_pause"].config == {"address": "1/1/222"}


def test_reference_villa_audio_module_package_yaml_round_trips():
    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    package = build_audio_module_package(project)

    data = yaml.safe_load(package_to_yaml(package))

    assert set(data.keys()) == {"switch", "light", "sensor"}

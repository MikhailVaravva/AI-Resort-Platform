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
    assert counts == {
        "switch": 12,
        "light": 3,
        "sensor": 14,
        "cover": 1,
        "date": 1,
        "button": 1,
        "number": 1,
    }


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
    assert by_name["Audio Play mode"].config["type"] == "pulse"


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

    assert set(data.keys()) == {"knx", "script", "media_player", "template"}
    assert set(data["knx"].keys()) == {
        "switch",
        "light",
        "sensor",
        "cover",
        "scene",
        "date",
        "button",
        "number",
    }
    assert len(data["knx"]["light"]) == 3
    assert len(data["knx"]["scene"]) == 6
    assert len(data["script"]) == 6
    assert len(data["media_player"]) == 1


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

    assert card_titles == {
        "Lights",
        "Sensors",
        "Switches",
        "Covers",
        "Scenes",
        "Scripts",
        "Dates",
        "Numbers",
        "Buttons",
        "Villa A1 Audio",
    }

    total_entities_in_cards = sum(len(c.entities) for c in view.cards)
    # -1: "Audio Absolut volume" has entity_category set (internal KNX
    # plumbing for the media_player's volume slider, see
    # _apply_audio_module_semantics) and is deliberately excluded from
    # every domain card.
    assert total_entities_in_cards == len(package.entities) - 1 + len(package.scenes) + len(
        package.scripts
    )
    lights_card = next(c for c in view.cards if c.title == "Lights")
    assert "light.audio_absolut_volume" not in lights_card.entities


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
        "villa_a1_audio_absolut_volume_percent",
        "villa_a1_audio_mute",
        "villa_a1_audio_play_pause",
        "villa_a1_audio_next_prev",
        "villa_a1_audio_track_name_latin_1",
        "villa_a1_audio_playlist_select_1byte_unsigned",
    }
    assert by_id["villa_a1_audio_power"].config == {
        "address": "1/1/202",
        "state_address": "1/1/203",
    }
    # Wired only to the touch panel in the real project, so no state_address
    # is available on the module-scoped package for these:
    assert by_id["villa_a1_audio_mute"].config == {"address": "1/1/220"}
    assert by_id["villa_a1_audio_play_pause"].config == {"address": "1/1/222"}
    # Rebuilt as a writable `light` (borrowing "Audio Power"'s address) so
    # the media_player can actually control volume, not just observe it -
    # see _apply_audio_module_semantics.
    assert by_id["villa_a1_audio_absolut_volume_percent"].domain == "light"
    assert by_id["villa_a1_audio_absolut_volume_percent"].config == {
        "address": "1/1/202",
        "brightness_address": "1/1/211",
        "entity_category": "config",
    }
    # DPST-1-7 "step": a momentary pulse, not a persistent switch state.
    assert by_id["villa_a1_audio_next_prev"].domain == "button"
    # Rebuilt as a writable `number` (its communication object is
    # genuinely read/write, verified) so select_source can work.
    assert by_id["villa_a1_audio_playlist_select_1byte_unsigned"].domain == "number"
    assert by_id["villa_a1_audio_playlist_select_1byte_unsigned"].config == {
        "address": "1/1/239",
        "type": "1byte_unsigned",
    }


def test_reference_villa_audio_module_package_yaml_round_trips():
    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    package = build_audio_module_package(project)

    data = yaml.safe_load(package_to_yaml(package))

    assert set(data.keys()) == {"knx", "media_player", "template"}
    assert set(data["knx"].keys()) == {"switch", "sensor", "light", "button", "number"}
    assert len(data["media_player"]) == 1


def test_reference_villa_media_player_maps_every_requested_field():
    package = _build()

    assert len(package.media_players) == 1
    media_player = package.media_players[0]
    assert media_player.unique_id == "villa_a1_audio_module"
    assert media_player.name == "Villa A1 Audio"

    commands = media_player.commands
    assert commands["turn_on"]["target"] == {"entity_id": "switch.audio_power"}
    assert commands["turn_off"]["target"] == {"entity_id": "switch.audio_power"}
    assert commands["media_play"]["target"] == {"entity_id": "switch.audio_play_pause"}
    assert commands["media_pause"]["target"] == {"entity_id": "switch.audio_play_pause"}
    assert commands["media_next_track"] == {
        "action": "button.press",
        "target": {"entity_id": "button.audio_next_prev"},
    }
    assert commands["volume_mute"] == {
        "action": "switch.toggle",
        "target": {"entity_id": "switch.audio_mute"},
    }
    assert commands["volume_set"] == {
        "action": "light.turn_on",
        "target": {"entity_id": "light.audio_absolut_volume"},
        "data": {"brightness_pct": "{{ [0, [100, (volume_level * 100) | round(0)] | min] | max }}"},
    }
    assert commands["select_source"] == {
        "action": "number.set_value",
        "target": {"entity_id": "number.audio_playlist_select"},
        "data": {"value": "{{ source }}"},
    }

    assert media_player.attributes == {
        "is_volume_muted": "switch.audio_mute",
        "volume_level": "sensor.villa_a1_audio_volume",
        "media_title": "sensor.audio_track_name",
        "source": "number.audio_playlist_select",
    }
    assert "state" not in media_player.attributes
    # Off vs idle vs playing needs both "Audio Power" and "Audio
    # Play/Pause" together - neither switch's own state alone is a valid
    # media_player state.
    assert "switch.audio_power" in media_player.state_template
    assert "switch.audio_play_pause" in media_player.state_template


def test_reference_villa_volume_level_sensor():
    package = _build()

    assert len(package.template_sensors) == 1
    sensor = package.template_sensors[0]
    assert sensor.unique_id == "villa_a1_audio_volume"
    assert sensor.name == "Villa A1 Audio Volume"
    assert "light.audio_absolut_volume" in sensor.state
    assert "brightness" in sensor.state
    assert "255" in sensor.state


def test_reference_villa_volume_level_sensor_yaml_structure():
    package = _build()

    data = yaml.safe_load(package_to_yaml(package))

    assert data["template"] == [
        {
            "sensor": [
                {
                    "name": "Villa A1 Audio Volume",
                    "unique_id": "villa_a1_audio_volume",
                    "state": package.template_sensors[0].state,
                }
            ]
        }
    ]


def test_reference_villa_dashboard_has_a_media_control_card_for_the_media_player():
    package = _build()
    dashboard = build_dashboard(package)
    view = dashboard.views[0]

    cards_by_title = {c.title: c for c in view.cards}
    card = cards_by_title["Villa A1 Audio"]
    assert card.card_type == "media-control"
    assert card.entity == "media_player.villa_a1_audio"


def test_reference_villa_welcome_automation_is_opt_in():
    """No welcome automation without explicit playlist indices - nothing
    in ETSProject can supply them."""
    package = _build()

    assert package.automations == ()


def test_reference_villa_welcome_automation():
    project = ETSProject.open(REFERENCE_VILLA, password="12345")

    package = build_package(project, welcome_playlist=1, background_playlist=2)

    assert len(package.automations) == 1
    automation = package.automations[0]
    assert automation.unique_id == "villa_a1_welcome"
    assert automation.name == "Villa A1 Welcome"
    assert automation.triggers == ({"trigger": "state", "entity_id": "switch.guest", "to": "on"},)
    assert automation.actions[0] == {
        "action": "media_player.turn_on",
        "target": {"entity_id": "media_player.villa_a1_audio"},
    }
    assert automation.actions[1] == {
        "action": "media_player.select_source",
        "target": {"entity_id": "media_player.villa_a1_audio"},
        "data": {"source": "1"},
    }
    assert automation.actions[4] == {"delay": "00:05:00"}
    assert automation.actions[5] == {
        "action": "media_player.select_source",
        "target": {"entity_id": "media_player.villa_a1_audio"},
        "data": {"source": "2"},
    }


def test_reference_villa_welcome_automation_yaml_structure():
    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    package = build_package(project, welcome_playlist=1, background_playlist=2)

    data = yaml.safe_load(package_to_yaml(package))

    assert len(data["automation"]) == 1
    automation = data["automation"][0]
    assert automation["alias"] == "Villa A1 Welcome"
    assert "triggers" in automation
    assert "actions" in automation
    assert "trigger" not in automation
    assert "action" not in automation

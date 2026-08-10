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
    # sensor is 13, not 14: "Audio Volume" (1/1/212) is folded into
    # "Audio Absolut volume" as brightness_state_address (see
    # _apply_audio_module_semantics), not a separate sensor anymore.
    # button is 2, not 1: "Audio Previous" is added alongside "Audio
    # Next/Prev", the other documented value (0) of the same group
    # address 1/1/226 (see _apply_audio_module_semantics).
    assert counts == {
        "switch": 12,
        "light": 3,
        "sensor": 13,
        "cover": 1,
        "date": 1,
        "button": 2,
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

    # "automation" is present even without welcome_playlist/
    # background_playlist: the departure automation (Guest -> off =>
    # Standby, see _build_departure_automation) has no playlist
    # dependency, unlike the welcome automation.
    assert set(data.keys()) == {"knx", "script", "media_player", "template", "automation"}
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
    # Villa-wide view + one per-room view (the reference project has a
    # single room, "Villa A1") - see _build_areas.
    assert len(data["views"]) == 2


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
        # The other documented value (0, "previous") of the same group
        # address as "villa_a1_audio_next_prev" - see
        # _apply_audio_module_semantics.
        "villa_a1_audio_next_prev_previous",
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
    assert by_id["villa_a1_audio_next_prev_previous"].domain == "button"
    assert by_id["villa_a1_audio_next_prev_previous"].config == {
        "address": "1/1/226",
        "payload": "0",
    }
    # Rebuilt as a writable `number` (its communication object is
    # genuinely read/write, verified) so select_source can work.
    assert by_id["villa_a1_audio_playlist_select_1byte_unsigned"].domain == "number"
    assert by_id["villa_a1_audio_playlist_select_1byte_unsigned"].config == {
        "address": "1/1/239",
        "type": "1byte_unsigned",
    }


def test_reference_villa_audio_module_package_has_a_media_player():
    """The device-scoped package builds a full media_player.

    It did not while Power was taken from "Audio Power Convert"
    (1/1/240/241), which is the touch panel's logic and has no
    communication object on the Audio Module, so the device-scoped filter
    always dropped it. Power is now "Audio Power" (1/1/202, the module's
    own Standby object), which the module does own - see
    _build_audio_media_player."""
    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    package = build_audio_module_package(project)

    (media_player,) = package.media_players
    assert media_player.commands["turn_on"]["target"] == {"entity_id": "switch.audio_power"}

    data = yaml.safe_load(package_to_yaml(package))

    assert set(data.keys()) == {"knx", "template", "media_player"}
    assert set(data["knx"].keys()) == {"switch", "sensor", "light", "button", "number"}


def test_reference_villa_media_player_maps_every_requested_field():
    package = _build()

    assert len(package.media_players) == 1
    media_player = package.media_players[0]
    assert media_player.unique_id == "villa_a1_audio_module"
    assert media_player.name == "Villa A1 Audio"

    commands = media_player.commands
    # Power is "Audio Power" (1/1/202/1/1/203) - the module's own Standby
    # object, the only power object its documentation defines. "Audio
    # Power Convert" (1/1/240/241) is the touch panel's logic and must not
    # be driven from here.
    assert commands["turn_on"]["target"] == {"entity_id": "switch.audio_power"}
    assert commands["turn_off"]["target"] == {"entity_id": "switch.audio_power"}
    assert "audio_power_convert" not in str(commands)
    assert commands["media_play"]["target"] == {"entity_id": "switch.audio_play_pause"}
    assert commands["media_pause"]["target"] == {"entity_id": "switch.audio_play_pause"}
    assert commands["media_next_track"] == {
        "action": "button.press",
        "target": {"entity_id": "button.audio_next_prev"},
    }
    # Same group address as media_next_track (1/1/226), payload 0 - BAB's
    # documented "previous" value for this object.
    assert commands["media_previous_track"] == {
        "action": "button.press",
        "target": {"entity_id": "button.audio_previous"},
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
    # Off vs paused vs playing needs both "Audio Power" (1/1/202) and
    # "Audio Play/Pause" together - neither switch's own state alone is a
    # valid media_player state. Quoted so the assertion can't be satisfied
    # by "audio_power_convert", which merely starts with the same text.
    assert "'switch.audio_power'" in media_player.state_template
    assert "audio_power_convert" not in media_player.state_template
    assert "switch.audio_play_pause" in media_player.state_template


def test_reference_villa_media_player_pauses_rather_than_idles():
    """HA hides the transport buttons unless the state is playing/paused.

    The frontend gates previous/next on the state, not only on the
    supported-features flags, so an `idle` player that advertises
    NEXT_TRACK/PREVIOUS_TRACK still renders a lone play button. `paused`
    is also the truthful state: the module keeps a playlist loaded.
    """
    (media_player,) = _build().media_players

    assert "paused" in media_player.state_template
    assert "idle" not in media_player.state_template
    # The two commands whose buttons the state was hiding.
    assert "media_next_track" in media_player.commands
    assert "media_previous_track" in media_player.commands


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


def test_reference_villa_areas_group_entities_by_ets_room():
    """Not real Home Assistant Areas (there is no YAML mechanism for
    those at all) - just the ETS-room grouping build_dashboard uses for
    its per-room views. The reference project's single room, "Villa A1",
    owns every device, so it should own every non-internal entity/scene.
    Also verifies the RoomArea carries the room's real ETS Building/Floor
    (Building -> BuildingPart -> Floor -> Room), not just its entities."""
    package = _build()

    assert len(package.areas) == 1
    area = package.areas[0]
    assert area.room == "Villa A1"
    # Verified against the reference project's own location tree.
    assert area.floor == "1"
    assert area.building == "Villa A"
    villa_a1 = set(area.entity_ids)

    assert "light.audio_absolut_volume" not in villa_a1  # internal - excluded
    assert "switch.guest" in villa_a1
    assert "light.g1" in villa_a1
    assert all(f"scene.scene_{n}" in villa_a1 for n in range(1, 7))
    assert len(villa_a1) == len(package.entities) - 1 + len(package.scenes)


def test_reference_villa_dashboard_has_one_view_per_room():
    """The reference project's only room happens to be named "Villa A1" -
    the same as the villa-wide view's own title - so both views share a
    `title`. Lovelace disambiguates by `view_id` (`path`), not `title`,
    so the two views must still have distinct, non-empty view_ids (see
    DashboardView/build_dashboard)."""
    package = _build()
    dashboard = build_dashboard(package)

    view_titles = [v.title for v in dashboard.views]
    assert view_titles == ["Villa A1", "Villa A1"]

    view_ids = [v.view_id for v in dashboard.views]
    assert all(view_ids)  # every view has a real, non-empty id
    assert len(set(view_ids)) == len(view_ids)  # and none of them collide
    assert dashboard.views[0].view_id == "overview"

    room_view = dashboard.views[1]
    assert len(room_view.cards) == 1
    assert room_view.cards[0].title == "Villa A1"
    assert set(room_view.cards[0].entities) == set(package.areas[0].entity_ids)


def test_reference_villa_welcome_automation_is_opt_in():
    """No welcome automation without explicit playlist indices - nothing
    in ETSProject can supply them. The departure automation (Guest -> off
    => Standby) still builds, since it has no playlist dependency at all
    (see _build_departure_automation)."""
    package = _build()

    assert [a.unique_id for a in package.automations] == ["villa_a1_departure"]


def test_reference_villa_welcome_automation():
    project = ETSProject.open(REFERENCE_VILLA, password="12345")

    package = build_package(project, welcome_playlist=1, background_playlist=2)

    # 2, not 1: the departure automation (Guest -> off => Standby, see
    # _build_departure_automation) always builds alongside it here, since
    # the reference project has both a "Guest" switch and "Audio Power".
    assert len(package.automations) == 2
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

    departure = package.automations[1]
    assert departure.unique_id == "villa_a1_departure"
    assert departure.name == "Villa A1 Departure"
    assert departure.triggers == ({"trigger": "state", "entity_id": "switch.guest", "to": "off"},)
    assert departure.actions == (
        {"action": "switch.turn_off", "target": {"entity_id": "switch.audio_power"}},
    )


def test_reference_villa_welcome_automation_yaml_structure():
    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    package = build_package(project, welcome_playlist=1, background_playlist=2)

    data = yaml.safe_load(package_to_yaml(package))

    assert len(data["automation"]) == 2
    automation = data["automation"][0]
    assert automation["alias"] == "Villa A1 Welcome"
    assert "triggers" in automation
    assert "actions" in automation
    assert "trigger" not in automation
    assert "action" not in automation
    assert data["automation"][1]["alias"] == "Villa A1 Departure"


def test_reference_villa_has_no_equalizer_without_explicit_addresses():
    """1/1/200 and 1/1/201 are configured in the module but absent from the
    ETS project, so the default build cannot and must not invent them."""
    assert _build().selects == ()


def test_reference_villa_equalizer_is_built_when_addresses_are_supplied():
    from ai_resort_platform.homeassistant.builder import (
        AUDIO_EQUALIZER_PRESETS,
        AudioEqualizerAddresses,
    )

    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    package = build_package(
        project,
        audio_equalizer=AudioEqualizerAddresses(address="1/1/200", state_address="1/1/201"),
    )

    (select,) = package.selects
    assert select.name == "Villa A1 Audio Equalizer"
    assert select.address == "1/1/200"
    assert select.state_address == "1/1/201"
    assert select.options == AUDIO_EQUALIZER_PRESETS

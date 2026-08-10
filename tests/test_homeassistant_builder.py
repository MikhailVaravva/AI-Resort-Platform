import pytest

from ai_resort_platform.ets.devices import Device
from ai_resort_platform.ets.group_addresses import GroupAddress
from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.ets.rooms import Room
from ai_resort_platform.homeassistant.builder import (
    build_audio_module_package,
    build_dashboard,
    build_package,
)


def _project(group_addresses: tuple[GroupAddress, ...]) -> ETSProject:
    return ETSProject(
        name="Hot Stone VILLA", guid="guid-1", tool_version="6.4.0", group_addresses=group_addresses
    )


def test_dimmable_light_with_switch_and_colour_temperature():
    gas = (
        GroupAddress(id="1", address="1/1/0", name="A1 G1 on/off", dpt_main=1, dpt_sub=1),
        GroupAddress(id="2", address="1/1/1", name="A1 G1 Switch status", dpt_main=1, dpt_sub=1),
        GroupAddress(
            id="3", address="1/1/2", name="A1 G1 Brightness Absolut", dpt_main=5, dpt_sub=1
        ),
        GroupAddress(
            id="4", address="1/1/4", name="A1 G1 Colour Temperature", dpt_main=7, dpt_sub=600
        ),
    )
    package = build_package(_project(gas))

    assert len(package.entities) == 1
    light = package.entities[0]
    assert light.domain == "light"
    assert light.config == {
        "address": "1/1/0",
        "state_address": "1/1/1",
        "brightness_address": "1/1/2",
        "color_temperature_address": "1/1/4",
    }


def test_scaling_dpt_not_used_as_brightness_stays_a_sensor():
    """Regression: dpt_main=5 alone (not the exact (5, 1) brightness pair)
    must not be misclassified as a light - e.g. a play-mode counter."""
    gas = (
        GroupAddress(id="1", address="1/1/243", name="A1 Audio Play mode", dpt_main=5, dpt_sub=10),
    )

    package = build_package(_project(gas))

    assert len(package.entities) == 1
    assert package.entities[0].domain == "sensor"
    assert package.entities[0].config == {"type": "pulse", "state_address": "1/1/243"}


def test_date_dpt_becomes_the_date_platform_not_a_sensor():
    """DPST-11-1 has no valid HA KNX sensor.type (DPT main-type 11 isn't in
    the documented Value types table) - it has its own dedicated `date`
    platform instead."""
    gas = (GroupAddress(id="1", address="1/1/42", name="A1 Date", dpt_main=11, dpt_sub=1),)

    package = build_package(_project(gas))

    assert len(package.entities) == 1
    assert package.entities[0].domain == "date"
    assert package.entities[0].config == {"address": "1/1/42"}


def test_command_only_dpst_1_7_becomes_a_button_not_a_switch():
    """DPST-1-7 "step" is a momentary directional pulse, not a persistent
    on/off state - a device receiving it performs one step and doesn't
    "stay" in the sent value. No sensor.type exists for DPT main-type 1
    either (see _DPT_LABELS), so `button` is the only valid domain."""
    gas = (GroupAddress(id="1", address="1/1/226", name="A1 Step", dpt_main=1, dpt_sub=7),)

    package = build_package(_project(gas))

    assert len(package.entities) == 1
    assert package.entities[0].domain == "button"
    assert package.entities[0].config == {"address": "1/1/226"}


def test_dpst_1_7_with_a_status_ga_stays_a_switch():
    """If a DPST-1-7 point ever DID have real status feedback, that would
    mean it behaves as a persistent state after all - the switch-merge
    path (see _build_entities_for) should still win over the button
    reclassification."""
    gas = (
        GroupAddress(id="1", address="1/1/226", name="A1 Step", dpt_main=1, dpt_sub=7),
        GroupAddress(id="2", address="1/1/227", name="A1 Step status", dpt_main=1, dpt_sub=7),
    )

    package = build_package(_project(gas))

    assert len(package.entities) == 1
    assert package.entities[0].domain == "switch"
    assert package.entities[0].config == {"address": "1/1/226", "state_address": "1/1/227"}


def test_plain_switch_is_not_a_light():
    gas = (GroupAddress(id="1", address="1/1/20", name="A1 Stone Power", dpt_main=1, dpt_sub=1),)

    package = build_package(_project(gas))

    assert package.entities[0].domain == "switch"
    assert package.entities[0].config == {"address": "1/1/20"}


def test_switch_with_only_status_becomes_binary_sensor():
    gas = (GroupAddress(id="1", address="1/1/29", name="A1 Contact status", dpt_main=1, dpt_sub=1),)

    package = build_package(_project(gas))

    assert package.entities[0].domain == "binary_sensor"
    assert package.entities[0].config == {"state_address": "1/1/29"}


def test_curtain_group_addresses_merge_into_one_cover():
    gas = (
        GroupAddress(
            id="1", address="1/1/30", name="A1 Curtain Open/Closed", dpt_main=1, dpt_sub=9
        ),
        GroupAddress(id="2", address="1/1/31", name="A1 Curtain Stop", dpt_main=1, dpt_sub=7),
        GroupAddress(id="3", address="1/1/32", name="A1 Curtain position", dpt_main=5, dpt_sub=1),
        GroupAddress(
            id="4", address="1/1/33", name="A1 Curtain position status", dpt_main=5, dpt_sub=1
        ),
    )
    package = build_package(_project(gas))

    assert len(package.entities) == 1
    cover = package.entities[0]
    assert cover.domain == "cover"
    assert cover.config == {
        "move_long_address": "1/1/30",
        "stop_address": "1/1/31",
        "position_address": "1/1/32",
        "position_state_address": "1/1/33",
    }


def test_command_and_status_with_mismatched_wording_still_merge():
    """The "value"/"status" naming quirk is still resolved into one
    entity_key regardless of the DPT - here there's no DPT-1.x switch
    key, so per the KNX `light` platform's required `address` field
    (confirmed against a real Home Assistant instance), this becomes a
    read-only `sensor` rather than an unbuildable `light`.

    Deliberately not a DMX channel: those are now collected into a single
    light with individual_colors (see _build_dmx_lights), which would make
    this about that instead of about the naming quirk.
    """
    gas = (
        GroupAddress(
            id="1", address="1/1/160", name="A1 Terrace Level value", dpt_main=5, dpt_sub=1
        ),
        GroupAddress(
            id="2", address="1/1/161", name="A1 Terrace Level status", dpt_main=5, dpt_sub=1
        ),
    )
    package = build_package(_project(gas))

    assert len(package.entities) == 1
    assert package.entities[0].domain == "sensor"
    assert package.entities[0].config == {"type": "percent", "state_address": "1/1/161"}


def test_multi_dpt_non_light_entity_fans_out_to_one_sensor_per_dpt():
    gas = (
        GroupAddress(id="1", address="1/1/40", name="A1 Multi Sensor", dpt_main=9, dpt_sub=1),
        GroupAddress(
            id="2", address="1/1/41", name="A1 Multi Sensor status", dpt_main=9, dpt_sub=7
        ),
    )
    package = build_package(_project(gas))

    assert len(package.entities) == 2
    assert all(e.domain == "sensor" for e in package.entities)
    types = {e.config["type"] for e in package.entities}
    assert types == {"temperature", "humidity"}


def test_command_and_status_sharing_different_dpt1_subtypes_merge_into_one_switch():
    """DPT main-type 1 has no valid HA KNX `sensor.type` at all (see
    homeassistant/builder.py:_DPT_LABELS), so a command/status pair that
    happens to use different DPT-1 sub-types (verified against the
    reference project: "Audio Play/Pause" command is DPST-1-10 "start",
    its status is DPST-1-1 "switch") must still merge into one `switch`
    entity - otherwise it can only become invalid HA config."""
    gas = (
        GroupAddress(id="1", address="1/1/222", name="A1 Audio Play/Pause", dpt_main=1, dpt_sub=10),
        GroupAddress(
            id="2", address="1/1/223", name="A1 Audio Play/Pause status", dpt_main=1, dpt_sub=1
        ),
    )
    package = build_package(_project(gas))

    assert len(package.entities) == 1
    assert package.entities[0].domain == "switch"
    assert package.entities[0].config == {"address": "1/1/222", "state_address": "1/1/223"}


def test_no_unique_id_collisions():
    gas = tuple(
        GroupAddress(id=str(i), address=f"1/1/{i}", name=f"A1 Thing {i}", dpt_main=1, dpt_sub=1)
        for i in range(30)
    )
    package = build_package(_project(gas))

    ids = [e.unique_id for e in package.entities]
    assert len(ids) == len(set(ids))


def test_build_package_is_deterministic():
    gas = (GroupAddress(id="1", address="1/1/20", name="A1 Stone Power", dpt_main=1, dpt_sub=1),)
    project = _project(gas)

    assert build_package(project) == build_package(project)


def test_empty_project_produces_no_entities():
    package = build_package(_project(()))

    assert package.entities == ()


def test_unique_id_is_scoped_to_the_room_not_the_whole_project():
    """Matches the old DigitalTwin builder: ids are prefixed by the villa's
    room name ("Villa A1"), not the whole ETS project name ("Hot Stone
    VILLA") - required for compatibility with existing HA installations."""
    gas = (GroupAddress(id="1", address="1/1/20", name="A1 Stone Power", dpt_main=1, dpt_sub=1),)
    project = ETSProject(
        name="Hot Stone VILLA",
        guid="guid-1",
        tool_version="6.4.0",
        rooms=(Room(id="BP-15", name="Villa A1"),),
        group_addresses=gas,
    )

    package = build_package(project)

    assert package.villa_name == "Villa A1"
    assert package.entities[0].unique_id == "villa_a1_stone_power"


def test_build_dashboard_groups_entities_by_domain():
    gas = (
        GroupAddress(id="1", address="1/1/0", name="A1 G1 on/off", dpt_main=1, dpt_sub=1),
        GroupAddress(
            id="2", address="1/1/2", name="A1 G1 Brightness Absolut", dpt_main=5, dpt_sub=1
        ),
        GroupAddress(id="3", address="1/1/20", name="A1 Stone Power", dpt_main=1, dpt_sub=1),
    )
    package = build_package(_project(gas))
    dashboard = build_dashboard(package)

    assert len(dashboard.views) == 1
    view = dashboard.views[0]
    assert view.title == "Hot Stone VILLA"
    cards_by_title = {c.title: c for c in view.cards}
    # Real HA entity_ids, derived from `name` alone (not our internal,
    # villa-prefixed unique_id - unique_id isn't a supported KNX option,
    # see generators/ha_yaml.py).
    assert cards_by_title["Lights"].entities == ("light.g1",)
    assert cards_by_title["Switches"].entities == ("switch.stone_power",)


def test_scenes_produce_scene_entity_and_activation_script():
    gas = (
        GroupAddress(id="1", address="1/1/150", name="A1 Scene Control", dpt_main=18, dpt_sub=1),
        GroupAddress(
            id="2", address="1/1/151", name="A1 Scene 1 1bit value", dpt_main=1, dpt_sub=1
        ),
        GroupAddress(
            id="3", address="1/1/152", name="A1 Scene 2 1bit value", dpt_main=1, dpt_sub=1
        ),
    )
    package = build_package(_project(gas))

    assert len(package.scenes) == 2
    scenes_by_number = {s.scene_number: s for s in package.scenes}
    assert scenes_by_number[1].address == "1/1/150"
    assert scenes_by_number[1].unique_id == "hot_stone_villa_scene_1"
    assert scenes_by_number[2].address == "1/1/150"

    assert len(package.scripts) == 2
    scripts_by_id = {s.unique_id: s for s in package.scripts}
    script = scripts_by_id["hot_stone_villa_activate_scene_1"]
    assert script.sequence == (
        {"service": "scene.turn_on", "target": {"entity_id": "scene.hot_stone_villa_scene_1"}},
    )


def test_scene_control_group_address_does_not_become_a_generic_entity():
    gas = (
        GroupAddress(id="1", address="1/1/150", name="A1 Scene Control", dpt_main=18, dpt_sub=1),
        GroupAddress(
            id="2", address="1/1/151", name="A1 Scene 1 1bit value", dpt_main=1, dpt_sub=1
        ),
    )
    package = build_package(_project(gas))

    assert package.entities == ()


def test_scene_control_without_matching_scenes_produces_nothing():
    gas = (
        GroupAddress(id="1", address="1/1/150", name="A1 Scene Control", dpt_main=18, dpt_sub=1),
    )

    package = build_package(_project(gas))

    assert package.scenes == ()
    assert package.scripts == ()
    assert package.entities == ()


def test_audio_module_package_only_includes_group_addresses_wired_to_the_module():
    """A group address belongs to the module because it shares one of the
    module's own communication objects - not because its name contains
    "Audio". "Audio Mute status" here is wired only to a different device
    (mirroring the real reference project's touch panel), so it must not
    appear."""
    audio_module = Device(
        individual_address="1.1.5",
        name="Audio Module A1",
        communication_object_ids=("1.1.5/O-1",),
    )
    touch_panel = Device(
        individual_address="1.1.4",
        name="KNX Smart Touch S3",
        communication_object_ids=("1.1.4/O-9",),
    )
    gas = (
        GroupAddress(
            id="1",
            address="1/1/220",
            name="A1 Audio Mute",
            dpt_main=1,
            dpt_sub=3,
            communication_object_ids=("1.1.5/O-1",),
        ),
        GroupAddress(
            id="2",
            address="1/1/221",
            name="A1 Audio Mute status",
            dpt_main=1,
            dpt_sub=3,
            communication_object_ids=("1.1.4/O-9",),
        ),
    )
    project = ETSProject(
        name="Hot Stone VILLA",
        guid="guid-1",
        tool_version="6.4.0",
        devices=(audio_module, touch_panel),
        group_addresses=gas,
    )

    package = build_audio_module_package(project)

    assert len(package.entities) == 1
    assert package.entities[0].config == {"address": "1/1/220"}


def _audio_module_gas() -> tuple[GroupAddress, ...]:
    return (
        # "Audio Power" (1/1/202) is the module's Standby object and the
        # only power object its documentation defines - the media_player
        # drives this one (see _build_audio_media_player).
        GroupAddress(id="1", address="1/1/202", name="A1 Audio Power", dpt_main=1, dpt_sub=1),
        # "Audio Power Convert" is the touch panel's logic, kept here only
        # so the tests prove the media_player leaves it alone.
        GroupAddress(
            id="8", address="1/1/240", name="A1 Audio Power Convert", dpt_main=1, dpt_sub=1
        ),
        GroupAddress(id="2", address="1/1/222", name="A1 Audio Play/Pause", dpt_main=1, dpt_sub=10),
        GroupAddress(id="3", address="1/1/226", name="A1 Audio Next/Prev", dpt_main=1, dpt_sub=7),
        GroupAddress(
            id="4", address="1/1/211", name="A1 Audio Absolut volume", dpt_main=5, dpt_sub=1
        ),
        GroupAddress(
            id="9", address="1/1/212", name="A1 Audio Volume status", dpt_main=5, dpt_sub=1
        ),
        GroupAddress(id="5", address="1/1/220", name="A1 Audio Mute", dpt_main=1, dpt_sub=3),
        GroupAddress(id="6", address="1/1/231", name="A1 Audio Track name", dpt_main=16, dpt_sub=1),
        GroupAddress(
            id="7", address="1/1/239", name="A1 Audio Playlist Select", dpt_main=5, dpt_sub=None
        ),
    )


def test_audio_module_semantics_reclassify_volume_and_playlist_entities():
    """ "Audio Absolut volume" and "Audio Playlist Select" are both wired
    to genuinely read/write communication objects (verified against the
    reference project), not status-only readouts - so they become a
    writable `light` (borrowing "Audio Power"'s address, since `light`
    requires one) and a writable `number`, not read-only `sensor`."""
    package = build_package(_project(_audio_module_gas()))
    by_name = {e.name: e for e in package.entities}

    volume = by_name["Audio Absolut volume"]
    assert volume.domain == "light"
    assert volume.config == {
        "address": "1/1/202",
        "brightness_address": "1/1/211",
        "brightness_state_address": "1/1/212",
        # Internal KNX plumbing for the media_player's volume slider (see
        # _build_audio_media_player) - not meant to show up in a "Lights"
        # list of its own.
        "entity_category": "config",
    }
    assert "Audio Volume" not in by_name  # folded into the light above

    playlist = by_name["Audio Playlist Select"]
    assert playlist.domain == "number"
    assert playlist.config == {"address": "1/1/239", "type": "1byte_unsigned"}

    next_track = by_name["Audio Next/Prev"]
    assert next_track.domain == "button"
    assert "payload" not in next_track.config  # unchanged: still the default (1, "next")

    # BAB documents 1/1/226 as bidirectional (EIS1: 0=previous,1=next) -
    # "Audio Previous" is the other half, same address, explicit payload 0.
    previous_track = by_name["Audio Previous"]
    assert previous_track.domain == "button"
    assert previous_track.config == {"address": "1/1/226", "payload": "0"}


def test_volume_light_has_no_brightness_state_address_when_status_ga_is_absent():
    gas = tuple(ga for ga in _audio_module_gas() if ga.name != "A1 Audio Volume status")

    package = build_package(_project(gas))
    volume = next(e for e in package.entities if e.name == "Audio Absolut volume")

    assert "brightness_state_address" not in volume.config


def test_dashboard_excludes_entity_category_entities_from_domain_cards():
    """ "Audio Absolut volume" is a real `light` (needed for the
    media_player's volume slider to actually write, see
    _apply_audio_module_semantics) but only an internal KNX
    implementation detail - it shouldn't show up in the "Lights" card
    next to entities a resident would actually want to toggle by hand."""
    package = build_package(_project(_audio_module_gas()))

    dashboard = build_dashboard(package)
    view = dashboard.views[0]
    cards_by_title = {c.title: c for c in view.cards}

    # "Audio Absolut volume" is the only `light` in this fixture, so once
    # it's excluded there's nothing left to put in a "Lights" card at all.
    assert "Lights" not in cards_by_title


def test_areas_group_entities_by_room_not_by_villa():
    """Not real Home Assistant Areas (there is no YAML mechanism to
    create one or assign an entity to it, for any integration) - just an
    ETS-room grouping build_dashboard uses for its per-room views.
    Verified with two rooms on different floors, since the real
    reference project only has one room - nothing here is specific to
    that villa's layout. Also verifies each RoomArea carries its own
    Building/Floor names straight from ETS's Room, not just entities."""
    device_a = Device(individual_address="1.1.1", name="A", communication_object_ids=("1.1.1/O-1",))
    device_b = Device(individual_address="1.1.2", name="B", communication_object_ids=("1.1.2/O-1",))
    room_a = Room(
        id="R-1", name="Room A", floor="Ground", building="Main House", device_ids=("1.1.1",)
    )
    room_b = Room(id="R-2", name="Room B", floor="1", building="Main House", device_ids=("1.1.2",))
    gas = (
        GroupAddress(
            id="1",
            address="1/1/20",
            name="A1 Stone Power",
            dpt_main=1,
            dpt_sub=1,
            communication_object_ids=("1.1.1/O-1",),
        ),
        GroupAddress(
            id="2",
            address="1/1/21",
            name="A1 Other Power",
            dpt_main=1,
            dpt_sub=1,
            communication_object_ids=("1.1.2/O-1",),
        ),
        # Fans out to both devices at once (a real KNX group address can
        # be linked to communication objects in different rooms) - should
        # land in both rooms' areas, not just one guessed "primary" room.
        GroupAddress(
            id="3",
            address="1/1/99",
            name="A1 Shared",
            dpt_main=1,
            dpt_sub=1,
            communication_object_ids=("1.1.1/O-1", "1.1.2/O-1"),
        ),
    )
    project = ETSProject(
        name="Hot Stone VILLA",
        guid="guid-1",
        tool_version="6.4.0",
        devices=(device_a, device_b),
        rooms=(room_a, room_b),
        group_addresses=gas,
    )

    package = build_package(project)

    areas_by_room_id = {a.room_id: a for a in package.areas}
    area_a = areas_by_room_id["R-1"]
    area_b = areas_by_room_id["R-2"]

    assert set(area_a.entity_ids) == {"switch.stone_power", "switch.shared"}
    assert set(area_b.entity_ids) == {"switch.other_power", "switch.shared"}

    assert area_a.room == "Room A"
    assert area_a.floor == "Ground"
    assert area_a.building == "Main House"
    assert area_b.room == "Room B"
    assert area_b.floor == "1"
    assert area_b.building == "Main House"


def test_media_player_is_built_when_every_source_entity_is_present():
    package = build_package(_project(_audio_module_gas()))

    assert len(package.media_players) == 1
    media_player = package.media_players[0]
    assert media_player.unique_id == "hot_stone_villa_audio_module"
    assert media_player.name == "Hot Stone VILLA Audio"
    assert media_player.commands == {
        # "Audio Power" (1/1/202, the module's own Standby object), never
        # "Audio Power Convert" - see _build_audio_media_player.
        "turn_on": {
            "action": "switch.turn_on",
            "target": {"entity_id": "switch.audio_power"},
        },
        "turn_off": {
            "action": "switch.turn_off",
            "target": {"entity_id": "switch.audio_power"},
        },
        "media_play": {
            "action": "switch.turn_on",
            "target": {"entity_id": "switch.audio_play_pause"},
        },
        "media_pause": {
            "action": "switch.turn_off",
            "target": {"entity_id": "switch.audio_play_pause"},
        },
        # "Audio Next/Prev" is a `button` (DPST-1-7 "step" is a momentary
        # pulse, not a persistent switch state - see _TRIGGER_DPTS).
        "media_next_track": {
            "action": "button.press",
            "target": {"entity_id": "button.audio_next_prev"},
        },
        # "Audio Previous" (see _apply_audio_module_semantics) - same
        # group address as "Audio Next/Prev", payload 0, the other half
        # of BAB's documented "Media Server - Title +/-" object.
        "media_previous_track": {
            "action": "button.press",
            "target": {"entity_id": "button.audio_previous"},
        },
        "volume_mute": {
            "action": "switch.toggle",
            "target": {"entity_id": "switch.audio_mute"},
        },
        # "Audio Absolut volume" is rebuilt as a `light` (see
        # _apply_audio_module_semantics) so this can actually write, not
        # just observe.
        "volume_set": {
            "action": "light.turn_on",
            "target": {"entity_id": "light.audio_absolut_volume"},
            "data": {
                "brightness_pct": "{{ [0, [100, (volume_level * 100) | round(0)] | min] | max }}"
            },
        },
        # "Audio Playlist Select" is rebuilt as a `number` (writable).
        "select_source": {
            "action": "number.set_value",
            "target": {"entity_id": "number.audio_playlist_select"},
            "data": {"value": "{{ source }}"},
        },
    }
    assert media_player.attributes == {
        "is_volume_muted": "switch.audio_mute",
        # Reads the converted 0.0-1.0 value from the template sensor
        # (see _build_volume_level_sensor), not the light's raw 0-255
        # brightness directly.
        "volume_level": "sensor.hot_stone_villa_audio_volume",
        "media_title": "sensor.audio_track_name",
        "source": "number.audio_playlist_select",
    }
    assert "state" not in media_player.attributes
    # Quoted so the assertion can't be satisfied by
    # "audio_power_convert", which merely starts with the same text.
    assert "'switch.audio_power'" in media_player.state_template
    assert "audio_power_convert" not in media_player.state_template
    assert "switch.audio_play_pause" in media_player.state_template


def test_volume_level_sensor_converts_brightness_to_0_1_scale():
    package = build_package(_project(_audio_module_gas()))

    assert len(package.template_sensors) == 1
    sensor = package.template_sensors[0]
    assert sensor.unique_id == "hot_stone_villa_audio_volume"
    assert sensor.name == "Hot Stone VILLA Audio Volume"
    assert "light.audio_absolut_volume" in sensor.state
    assert "brightness" in sensor.state


@pytest.mark.parametrize(
    ("brightness", "expected"),
    [(0, 0.0), (128, 128 / 255), (255, 1.0)],
)
def test_volume_level_sensor_conversion_math(brightness, expected):
    """The exact conversion math the template performs, evaluated in
    Python rather than by Home Assistant's Jinja engine - the template
    itself is verified against a real Home Assistant instance
    separately."""
    raw = brightness / 255
    clamped = max(0.0, min(1.0, raw))
    assert clamped == expected


def test_volume_level_sensor_is_not_built_without_a_volume_entity():
    gas = tuple(ga for ga in _audio_module_gas() if ga.name != "A1 Audio Absolut volume")

    package = build_package(_project(gas))

    assert package.template_sensors == ()


def test_media_player_is_not_built_when_a_source_entity_is_missing():
    gas = tuple(ga for ga in _audio_module_gas() if ga.name != "A1 Audio Mute")

    package = build_package(_project(gas))

    assert package.media_players == ()


def _guest_ga() -> GroupAddress:
    return GroupAddress(id="8", address="1/1/50", name="A1 Guest", dpt_main=1, dpt_sub=3)


def test_welcome_automation_is_built_when_playlists_are_supplied():
    gas = _audio_module_gas() + (_guest_ga(),)
    project = _project(gas)

    package = build_package(project, welcome_playlist=1, background_playlist=2)

    # 2, not 1: "Guest" -> off also builds the departure automation (see
    # _build_departure_automation) - independent of the playlist indices.
    assert len(package.automations) == 2
    automation = package.automations[0]
    assert automation.unique_id == "hot_stone_villa_welcome"
    assert automation.name == "Hot Stone VILLA Welcome"
    # `from` guards against an HA restart's unavailable -> on transition
    # starting check-in by itself.
    assert automation.triggers == (
        {"trigger": "state", "entity_id": "switch.guest", "from": "off", "to": "on"},
    )
    assert automation.actions == (
        {
            "action": "media_player.turn_on",
            "target": {"entity_id": "media_player.hot_stone_villa_audio"},
        },
        # The playlist index goes to its own entity, not through the
        # player's `source` - see _build_welcome_automation.
        {
            "action": "number.set_value",
            "target": {"entity_id": "number.audio_playlist_select"},
            "data": {"value": 1},
        },
        {
            "action": "media_player.media_play",
            "target": {"entity_id": "media_player.hot_stone_villa_audio"},
        },
        {
            "action": "media_player.volume_set",
            "target": {"entity_id": "media_player.hot_stone_villa_audio"},
            "data": {"volume_level": 0.5},
        },
        {"delay": "00:05:00"},
        {
            "action": "number.set_value",
            "target": {"entity_id": "number.audio_playlist_select"},
            "data": {"value": 2},
        },
    )


def test_welcome_automation_is_not_built_without_both_playlist_indices():
    """Only the welcome automation is playlist-gated - the departure
    automation (Guest -> off => Standby, see _build_departure_automation)
    has no playlist dependency at all, so it still builds."""
    gas = _audio_module_gas() + (_guest_ga(),)
    project = _project(gas)

    departure_only = ("hot_stone_villa_departure",)
    assert tuple(a.unique_id for a in build_package(project).automations) == departure_only
    assert (
        tuple(a.unique_id for a in build_package(project, welcome_playlist=1).automations)
        == departure_only
    )
    assert (
        tuple(a.unique_id for a in build_package(project, background_playlist=2).automations)
        == departure_only
    )


def test_welcome_automation_is_not_built_without_a_guest_switch():
    package = build_package(
        _project(_audio_module_gas()), welcome_playlist=1, background_playlist=2
    )

    assert package.automations == ()


def test_welcome_automation_respects_custom_volume_and_delay():
    gas = _audio_module_gas() + (_guest_ga(),)
    project = _project(gas)

    package = build_package(
        project,
        welcome_playlist=1,
        background_playlist=2,
        welcome_volume_percent=30,
        welcome_to_background_delay="00:10:00",
    )

    automation = package.automations[0]
    assert automation.actions[3]["data"] == {"volume_level": 0.3}
    assert automation.actions[4] == {"delay": "00:10:00"}


def test_departure_automation_puts_audio_module_into_standby():
    """ "Guest" -> off sends the module's Standby command GA (1/1/202,
    "Audio Power") directly rather than through the media_player, and
    never touches "Audio Power Convert" (1/1/240), which belongs to the
    touch panel."""
    gas = _audio_module_gas() + (_guest_ga(),)
    project = _project(gas)

    # No playlist indices at all - the departure automation has no
    # playlist dependency, unlike the welcome one.
    package = build_package(project)

    assert len(package.automations) == 1
    automation = package.automations[0]
    assert automation.unique_id == "hot_stone_villa_departure"
    assert automation.name == "Hot Stone VILLA Departure"
    # `from` guards against an HA restart's unavailable -> off transition
    # silencing the villa - observed happening on the live installation.
    assert automation.triggers == (
        {"trigger": "state", "entity_id": "switch.guest", "from": "on", "to": "off"},
    )
    assert automation.actions == (
        {"action": "switch.turn_off", "target": {"entity_id": "switch.audio_power"}},
    )


def test_departure_automation_is_not_built_without_a_guest_switch():
    package = build_package(_project(_audio_module_gas()))

    assert package.automations == ()

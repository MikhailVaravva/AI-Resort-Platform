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
    gas = (
        GroupAddress(
            id="1", address="1/1/160", name="A1 DMX Terrace Red value", dpt_main=5, dpt_sub=1
        ),
        GroupAddress(
            id="2", address="1/1/161", name="A1 DMX Terrace Red status", dpt_main=5, dpt_sub=1
        ),
    )
    package = build_package(_project(gas))

    assert len(package.entities) == 1
    assert package.entities[0].config == {
        "brightness_address": "1/1/160",
        "brightness_state_address": "1/1/161",
    }


def test_multi_dpt_non_light_entity_fans_out_to_one_sensor_per_dpt():
    gas = (
        GroupAddress(id="1", address="1/1/222", name="A1 Audio Play/Pause", dpt_main=1, dpt_sub=10),
        GroupAddress(
            id="2", address="1/1/223", name="A1 Audio Play/Pause status", dpt_main=1, dpt_sub=1
        ),
    )
    package = build_package(_project(gas))

    assert len(package.entities) == 2
    assert all(e.domain == "sensor" for e in package.entities)
    ids = {e.unique_id for e in package.entities}
    # DPT main-type 1 has no valid HA KNX sensor.type at all (see
    # homeassistant/builder.py:_DPT_LABELS) - both fall back to the numeric
    # label. These two entities are not valid HA config as `sensor`; fixing
    # that requires a domain change, out of scope for this grouping test.
    assert ids == {
        "hot_stone_villa_audio_play_pause_1_10",
        "hot_stone_villa_audio_play_pause_1_1",
    }


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
        GroupAddress(
            id="1", address="1/1/2", name="A1 G1 Brightness Absolut", dpt_main=5, dpt_sub=1
        ),
        GroupAddress(id="2", address="1/1/20", name="A1 Stone Power", dpt_main=1, dpt_sub=1),
    )
    package = build_package(_project(gas))
    dashboard = build_dashboard(package)

    assert len(dashboard.views) == 1
    view = dashboard.views[0]
    assert view.title == "Hot Stone VILLA"
    cards_by_title = {c.title: c for c in view.cards}
    assert cards_by_title["Lights"].entities == ("light.hot_stone_villa_g1",)
    assert cards_by_title["Switches"].entities == ("switch.hot_stone_villa_stone_power",)


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

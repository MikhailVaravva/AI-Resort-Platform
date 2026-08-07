from ai_resort_platform.digital_twin.models import Capability, Entity, Scene, Villa
from ai_resort_platform.generators.ha_builder import build_dashboard, build_package


def _villa(entities=(), scenes=()) -> Villa:
    return Villa(
        id="villa-1", name="Villa X1", villa_type="Villa X", entities=entities, scenes=scenes
    )


def test_dimmable_entity_becomes_light():
    entity = Entity(
        id="e-1",
        name="G1",
        capabilities=(
            Capability(kind="switch", command_group_address="1/1/0", status_group_address="1/1/1"),
            Capability(kind="scaling", command_group_address="1/1/2"),
        ),
    )
    package = build_package(_villa(entities=(entity,)))

    assert len(package.entities) == 1
    light = package.entities[0]
    assert light.domain == "light"
    assert light.unique_id == "villa_x1_g1"
    assert light.config == {
        "address": "1/1/0",
        "state_address": "1/1/1",
        "brightness_address": "1/1/2",
    }


def test_brightness_only_entity_becomes_light_without_switch_address():
    entity = Entity(
        id="e-1",
        name="DMX Red",
        capabilities=(Capability(kind="scaling", command_group_address="1/1/5"),),
    )
    package = build_package(_villa(entities=(entity,)))

    assert package.entities[0].domain == "light"
    assert package.entities[0].config == {"brightness_address": "1/1/5"}


def test_plain_switch_entity_is_not_a_light():
    """Regression: a bare on/off Entity must not be misclassified as a light
    just because it has a "switch" capability."""
    entity = Entity(
        id="e-1",
        name="Stone Power",
        capabilities=(Capability(kind="switch", command_group_address="1/1/20"),),
    )
    package = build_package(_villa(entities=(entity,)))

    assert len(package.entities) == 1
    assert package.entities[0].domain == "switch"
    assert package.entities[0].config == {"address": "1/1/20"}


def test_switch_with_only_status_becomes_binary_sensor():
    entity = Entity(
        id="e-1",
        name="Contact",
        capabilities=(Capability(kind="switch", status_group_address="1/1/29"),),
    )
    package = build_package(_villa(entities=(entity,)))

    assert package.entities[0].domain == "binary_sensor"
    assert package.entities[0].config == {"state_address": "1/1/29"}


def test_unclassifiable_single_capability_becomes_sensor():
    entity = Entity(
        id="e-1",
        name="Humidity",
        capabilities=(Capability(kind="valueHumidity", command_group_address="1/1/41"),),
    )
    package = build_package(_villa(entities=(entity,)))

    entity_out = package.entities[0]
    assert entity_out.domain == "sensor"
    assert entity_out.name == "Humidity"
    assert entity_out.config == {"type": "valueHumidity", "state_address": "1/1/41"}


def test_multi_capability_non_light_entity_fans_out_to_one_sensor_per_capability():
    """Nothing should be silently dropped when an Entity doesn't fit a single domain."""
    entity = Entity(
        id="e-1",
        name="Audio Play/Pause",
        capabilities=(
            Capability(kind="start", command_group_address="1/1/222"),
            Capability(kind="switch", status_group_address="1/1/223"),
        ),
    )
    package = build_package(_villa(entities=(entity,)))

    assert len(package.entities) == 2
    ids = {e.unique_id for e in package.entities}
    assert ids == {"villa_x1_audio_play_pause_start", "villa_x1_audio_play_pause_switch"}
    assert all(e.domain == "sensor" for e in package.entities)


def test_curtain_entities_merge_into_one_cover():
    entities = (
        Entity(
            id="e-1",
            name="Curtain Open/Closed",
            capabilities=(Capability(kind="openClose", command_group_address="1/1/30"),),
        ),
        Entity(
            id="e-2",
            name="Curtain Stop",
            capabilities=(Capability(kind="step", command_group_address="1/1/31"),),
        ),
        Entity(
            id="e-3",
            name="Curtain position",
            capabilities=(
                Capability(
                    kind="scaling", command_group_address="1/1/32", status_group_address="1/1/33"
                ),
            ),
        ),
    )
    package = build_package(_villa(entities=entities))

    assert len(package.entities) == 1
    cover = package.entities[0]
    assert cover.domain == "cover"
    assert cover.name == "Curtain"
    assert cover.config == {
        "move_long_address": "1/1/30",
        "stop_address": "1/1/31",
        "position_address": "1/1/32",
        "position_state_address": "1/1/33",
    }


def test_no_unique_id_collisions_across_many_entities():
    entities = tuple(
        Entity(
            id=f"e-{i}",
            name=f"Thing {i}",
            capabilities=(Capability(kind="switch", command_group_address=f"1/1/{i}"),),
        )
        for i in range(20)
    )
    package = build_package(_villa(entities=entities))

    ids = [e.unique_id for e in package.entities]
    assert len(ids) == len(set(ids))


def test_build_package_is_deterministic():
    entity = Entity(
        id="e-1",
        name="G1",
        capabilities=(Capability(kind="switch", command_group_address="1/1/0"),),
    )
    villa = _villa(entities=(entity,))

    first = build_package(villa)
    second = build_package(villa)

    assert first == second


def test_numbered_scene_produces_scene_entity_and_activation_script():
    scenes = (
        Scene(id="s-0", name="Scene Control", control_group_address="1/1/150"),
        Scene(
            id="s-1",
            name="Scene 1",
            number=1,
            control_group_address="1/1/150",
            status_group_address="1/1/151",
        ),
    )
    package = build_package(_villa(scenes=scenes))

    assert len(package.scenes) == 1
    scene = package.scenes[0]
    assert scene.unique_id == "villa_x1_scene_1"
    assert scene.address == "1/1/150"
    assert scene.scene_number == 1

    assert len(package.scripts) == 1
    script = package.scripts[0]
    assert script.unique_id == "villa_x1_activate_scene_1"
    assert script.sequence == (
        {"service": "scene.turn_on", "target": {"entity_id": "scene.villa_x1_scene_1"}},
    )


def test_scene_control_without_number_produces_no_scene_or_script():
    scenes = (Scene(id="s-0", name="Scene Control", control_group_address="1/1/150"),)
    package = build_package(_villa(scenes=scenes))

    assert package.scenes == ()
    assert package.scripts == ()


def test_automations_are_always_empty():
    """No automation-worthy signal exists in raw KNX wiring data - see
    generators/ha_package.py:HaAutomation."""
    package = build_package(_villa())

    assert package.automations == ()


def test_build_dashboard_groups_entities_by_domain():
    entities = (
        Entity(
            id="e-1",
            name="G1",
            capabilities=(Capability(kind="scaling", command_group_address="1/1/2"),),
        ),
        Entity(
            id="e-2",
            name="Stone Power",
            capabilities=(Capability(kind="switch", command_group_address="1/1/20"),),
        ),
    )
    package = build_package(_villa(entities=entities))
    dashboard = build_dashboard(package)

    assert len(dashboard.views) == 1
    view = dashboard.views[0]
    assert view.title == "Villa X1"
    cards_by_title = {c.title: c for c in view.cards}
    assert cards_by_title["Lights"].entities == ("light.villa_x1_g1",)
    assert cards_by_title["Switches"].entities == ("switch.villa_x1_stone_power",)

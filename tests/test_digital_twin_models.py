from ai_resort_platform.digital_twin.models import (
    Capability,
    Device,
    Entity,
    Resort,
    Room,
    Scene,
    Villa,
)


def test_resort_defaults_to_no_villas():
    resort = Resort(name="Empty Resort")

    assert resort.villas == ()


def test_villa_holds_its_own_collections():
    capability = Capability(kind="switch", command_group_address="1/1/0")
    entity = Entity(id="e-1", name="G1", capabilities=(capability,))
    device = Device(id="d-1", name="Actuator", individual_address="1.1.1")
    room = Room(id="r-1", name="Bedroom", devices=(device,), entities=(entity,))
    scene = Scene(id="s-1", name="Scene Control", control_group_address="1/1/30")

    villa = Villa(
        id="v-1",
        name="Villa A1",
        villa_type="Villa A",
        rooms=(room,),
        devices=(device,),
        entities=(entity,),
        scenes=(scene,),
    )

    assert villa.rooms == (room,)
    assert villa.devices == (device,)
    assert villa.entities == (entity,)
    assert villa.scenes == (scene,)


def test_capability_defaults_to_no_addresses():
    capability = Capability(kind="switch")

    assert capability.command_group_address is None
    assert capability.status_group_address is None


def test_scene_defaults_to_no_number():
    scene = Scene(id="s-1", name="Scene Control")

    assert scene.number is None
    assert scene.control_group_address is None
    assert scene.status_group_address is None

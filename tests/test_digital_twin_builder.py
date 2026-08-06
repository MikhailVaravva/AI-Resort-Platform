from ai_resort_platform.digital_twin.builder import build_resort
from ai_resort_platform.models import project as pm


def _make_project() -> pm.ProjectModel:
    group_addresses = (
        # G1 entity: two capabilities (switch, scaling), each distinguished by DPT.
        pm.GroupAddress(
            id="ga-1",
            address="1/1/0",
            name="X1 G1 on/off",
            datapoint_type="switch",
            communication_object_ids=("co-1",),
        ),
        pm.GroupAddress(
            id="ga-2",
            address="1/1/1",
            name="X1 G1 Switch status",
            datapoint_type="switch",
            communication_object_ids=("co-1",),
        ),
        pm.GroupAddress(
            id="ga-3",
            address="1/1/2",
            name="X1 G1 Brightness Absolut",
            datapoint_type="scaling",
            communication_object_ids=("co-1",),
        ),
        # Standalone command+status pair, no G-token.
        pm.GroupAddress(
            id="ga-4",
            address="1/1/10",
            name="X1 Curtain position",
            datapoint_type="scaling",
            communication_object_ids=("co-2",),
        ),
        pm.GroupAddress(
            id="ga-5",
            address="1/1/11",
            name="X1 Curtain position status",
            datapoint_type="scaling",
            communication_object_ids=("co-2",),
        ),
        # Standalone, command only.
        pm.GroupAddress(
            id="ga-6",
            address="1/1/20",
            name="X1 All Off",
            datapoint_type="switch",
            communication_object_ids=("co-2",),
        ),
        # Scene control + two numbered scenes.
        pm.GroupAddress(
            id="ga-7",
            address="1/1/30",
            name="X1 Scene Control",
            datapoint_type="sceneControl",
            communication_object_ids=("co-1",),
        ),
        pm.GroupAddress(
            id="ga-8",
            address="1/1/31",
            name="X1 Scene 1 1bit value",
            datapoint_type="switch",
            communication_object_ids=("co-1",),
        ),
        pm.GroupAddress(
            id="ga-9",
            address="1/1/32",
            name="X1 Scene 2 1bit value",
            datapoint_type="switch",
            communication_object_ids=("co-2",),
        ),
    )
    devices = (
        pm.Device(
            id="di-1",
            name="Actuator",
            individual_address="1.1.1",
            manufacturer="ACME",
            product_name="Actuator 8x",
            serial_number="SN1",
            communication_object_ids=("co-1", "co-2"),
        ),
    )
    rooms = (
        pm.Room(
            id="room-1",
            name="Villa X1",
            floor="1",
            building="Villa X",
            device_ids=("di-1",),
        ),
    )
    communication_objects = (
        pm.CommunicationObject(id="co-1", name="CO1", device_id="di-1"),
        pm.CommunicationObject(id="co-2", name="CO2", device_id="di-1"),
    )
    return pm.ProjectModel(
        project_name="Test Resort",
        rooms=rooms,
        devices=devices,
        group_addresses=group_addresses,
        communication_objects=communication_objects,
    )


def test_build_resort_name():
    resort = build_resort(_make_project())

    assert resort.name == "Test Resort"


def test_build_resort_creates_one_villa_per_project_room():
    resort = build_resort(_make_project())

    assert len(resort.villas) == 1
    villa = resort.villas[0]
    assert villa.id == "room-1"
    assert villa.name == "Villa X1"
    assert villa.villa_type == "Villa X"


def test_villa_includes_its_devices():
    resort = build_resort(_make_project())
    villa = resort.villas[0]

    assert len(villa.devices) == 1
    device = villa.devices[0]
    assert device.id == "di-1"
    assert device.name == "Actuator"
    assert device.individual_address == "1.1.1"
    assert device.manufacturer == "ACME"
    assert device.product_name == "Actuator 8x"
    assert device.serial_number == "SN1"


def test_g_token_group_becomes_one_entity_with_two_capabilities():
    resort = build_resort(_make_project())
    villa = resort.villas[0]
    entities_by_id = {e.id: e for e in villa.entities}

    entity = entities_by_id["room-1:G1"]
    assert entity.name == "G1"
    capabilities_by_kind = {c.kind: c for c in entity.capabilities}
    assert set(capabilities_by_kind) == {"switch", "scaling"}

    switch = capabilities_by_kind["switch"]
    assert switch.command_group_address == "1/1/0"
    assert switch.status_group_address == "1/1/1"

    brightness = capabilities_by_kind["scaling"]
    assert brightness.command_group_address == "1/1/2"
    assert brightness.status_group_address is None


def test_standalone_command_and_status_pair_become_one_entity():
    resort = build_resort(_make_project())
    villa = resort.villas[0]
    entities_by_id = {e.id: e for e in villa.entities}

    entity = entities_by_id["room-1:Curtain position"]
    assert len(entity.capabilities) == 1
    capability = entity.capabilities[0]
    assert capability.kind == "scaling"
    assert capability.command_group_address == "1/1/10"
    assert capability.status_group_address == "1/1/11"


def test_standalone_command_without_status_becomes_single_capability_entity():
    resort = build_resort(_make_project())
    villa = resort.villas[0]
    entities_by_id = {e.id: e for e in villa.entities}

    entity = entities_by_id["room-1:All Off"]
    assert len(entity.capabilities) == 1
    capability = entity.capabilities[0]
    assert capability.command_group_address == "1/1/20"
    assert capability.status_group_address is None


def test_scene_group_addresses_are_not_also_built_as_entities():
    resort = build_resort(_make_project())
    villa = resort.villas[0]

    assert len(villa.entities) == 3  # G1, Curtain position, All Off - not the 3 scene GAs


def test_scenes_are_extracted_with_control_and_numbered_status_points():
    resort = build_resort(_make_project())
    villa = resort.villas[0]
    scenes_by_number = {s.number: s for s in villa.scenes}

    assert len(villa.scenes) == 3

    control = scenes_by_number[None]
    assert control.control_group_address == "1/1/30"
    assert control.status_group_address is None

    scene_1 = scenes_by_number[1]
    assert scene_1.control_group_address == "1/1/30"
    assert scene_1.status_group_address == "1/1/31"

    scene_2 = scenes_by_number[2]
    assert scene_2.control_group_address == "1/1/30"
    assert scene_2.status_group_address == "1/1/32"


def test_build_resort_with_no_rooms_produces_no_villas():
    project = pm.ProjectModel(project_name="Empty")

    resort = build_resort(project)

    assert resort.villas == ()

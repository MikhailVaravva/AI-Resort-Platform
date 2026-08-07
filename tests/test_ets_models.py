import pytest

from ai_resort_platform.ets.communication_objects import CommunicationObject, Flags
from ai_resort_platform.ets.devices import Device, Product
from ai_resort_platform.ets.group_addresses import DatapointType, GroupAddress
from ai_resort_platform.ets.project import Area, ETSProject, Line, Topology
from ai_resort_platform.ets.rooms import Building, Floor, Room


def test_group_address_defaults():
    ga = GroupAddress(id="GA-1", address="1/1/0", name="G1 on/off")

    assert ga.description == ""
    assert ga.dpt_main is None
    assert ga.data_secure is False
    assert ga.communication_object_ids == ()


def test_datapoint_type_sub_defaults_to_none():
    dpt = DatapointType(main=1)

    assert dpt.sub is None


def test_building_holds_its_fields():
    building = Building(id="BP-1", name="Hot Stone")

    assert building.id == "BP-1"
    assert building.name == "Hot Stone"


def test_floor_defaults_to_no_building():
    floor = Floor(id="BP-10", name="1")

    assert floor.building is None


def test_product_defaults_to_none_fields():
    product = Product()

    assert product.manufacturer is None
    assert product.hardware_name is None
    assert product.order_number is None


def test_device_defaults():
    device = Device(individual_address="1.1.1", name="Actuator")

    assert device.manufacturer is None
    assert device.communication_object_ids == ()


def test_room_defaults():
    room = Room(id="BP-15", name="Villa A1")

    assert room.floor is None
    assert room.building is None
    assert room.device_ids == ()


def test_flags_default_to_false():
    flags = Flags()

    assert flags.read is False
    assert flags.write is False
    assert flags.communication is False


def test_communication_object_holds_its_flags():
    co = CommunicationObject(
        id="1.1.1/O-1",
        name="Switch",
        number=1,
        device_address="1.1.1",
        flags=Flags(write=True, communication=True),
    )

    assert co.flags.write is True
    assert co.flags.read is False


def test_line_and_area_defaults():
    line = Line(address=1)
    area = Area(address=1, lines=(line,))

    assert line.name == ""
    assert line.device_ids == ()
    assert area.lines == (line,)


def test_topology_defaults_to_no_areas():
    assert Topology().areas == ()


def test_topology_lines_flattens_every_area():
    line_a = Line(address=1, device_ids=("1.1.1",))
    line_b = Line(address=1, device_ids=("2.1.1",))
    topology = Topology(areas=(Area(address=1, lines=(line_a,)), Area(address=2, lines=(line_b,))))

    assert topology.lines == (line_a, line_b)


def _sample_project() -> ETSProject:
    device = Device(
        individual_address="1.1.1", name="Actuator", manufacturer="ACME", hardware_name="Hw1"
    )
    building = Building(id="BP-1", name="Hot Stone")
    floor = Floor(id="BP-10", name="1", building="Villa A")
    room = Room(id="BP-15", name="Villa A1")
    ga = GroupAddress(id="GA-1", address="1/1/0", name="G1 on/off", dpt_main=1, dpt_sub=1)
    co = CommunicationObject(id="1.1.1/O-1", name="Switch", number=1, device_address="1.1.1")
    topology = Topology(areas=(Area(address=1, lines=(Line(address=1, device_ids=("1.1.1",)),)),))

    return ETSProject(
        name="Hot Stone VILLA",
        guid="31f9b2d9-7433-48d6-b127-1fea6c0c66b4",
        tool_version="6.4.8718.0",
        devices=(device,),
        buildings=(building,),
        floors=(floor,),
        rooms=(room,),
        group_addresses=(ga,),
        communication_objects=(co,),
        topology=topology,
    )


def test_ets_project_holds_its_collections():
    project = _sample_project()

    assert len(project.devices) == 1
    assert len(project.buildings) == 1
    assert len(project.floors) == 1
    assert len(project.rooms) == 1
    assert len(project.group_addresses) == 1
    assert len(project.communication_objects) == 1
    assert len(project.topology.areas) == 1


def test_ets_project_datapoint_types_deduplicates_and_skips_missing_dpt():
    project = _sample_project()
    ga_no_dpt = GroupAddress(id="GA-2", address="1/1/1", name="No DPT")
    project = ETSProject(
        name=project.name,
        guid=project.guid,
        tool_version=project.tool_version,
        group_addresses=project.group_addresses + (ga_no_dpt, project.group_addresses[0]),
    )

    assert project.datapoint_types == (DatapointType(main=1, sub=1),)


def test_ets_project_manufacturers_deduplicates_and_sorts():
    device_a = Device(individual_address="1.1.1", name="A", manufacturer="Zeta")
    device_b = Device(individual_address="1.1.2", name="B", manufacturer="Acme")
    device_c = Device(individual_address="1.1.3", name="C", manufacturer="Zeta")
    project = ETSProject(
        name="x", guid="g", tool_version="v", devices=(device_a, device_b, device_c)
    )

    assert project.manufacturers == ("Acme", "Zeta")


def test_ets_project_products_deduplicates():
    device_a = Device(
        individual_address="1.1.1", name="A", manufacturer="Acme", hardware_name="Hw1"
    )
    device_b = Device(
        individual_address="1.1.2", name="B", manufacturer="Acme", hardware_name="Hw1"
    )
    project = ETSProject(name="x", guid="g", tool_version="v", devices=(device_a, device_b))

    assert project.products == (
        Product(manufacturer="Acme", hardware_name="Hw1", order_number=None),
    )


def test_ets_project_device_lookup_by_address_then_name():
    project = _sample_project()

    assert project.device("1.1.1").name == "Actuator"
    assert project.device("Actuator").individual_address == "1.1.1"


def test_ets_project_device_lookup_missing_raises_key_error():
    project = _sample_project()

    with pytest.raises(KeyError):
        project.device("nope")


def test_ets_project_room_lookup():
    project = _sample_project()

    assert project.room("Villa A1").id == "BP-15"


def test_ets_project_group_address_lookup():
    project = _sample_project()

    assert project.group_address("1/1/0").name == "G1 on/off"

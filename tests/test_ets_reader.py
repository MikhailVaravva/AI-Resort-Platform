"""Integration tests: open the real reference project via xknxproject."""

from pathlib import Path

import pytest

from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.ets.reader import EtsProjectError, EtsProjectPasswordError

REFERENCE_VILLA = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "Reference-Villa"
    / "reference_villa.knxproj"
)
PASSWORD = "12345"


def test_reference_villa_fixture_exists():
    assert REFERENCE_VILLA.exists(), "examples/Reference-Villa/reference_villa.knxproj is missing"


def test_open_reads_project_info():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert project.name == "Hot Stone VILLA"
    assert project.guid == "31f9b2d9-7433-48d6-b127-1fea6c0c66b4"
    assert project.tool_version == "6.4.8718.0"


def test_open_reads_all_devices():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert len(project.devices) == 7
    assert {d.individual_address for d in project.devices} == {
        "1.1.1",
        "1.1.2",
        "1.1.3",
        "1.1.4",
        "1.1.5",
        "1.1.6",
        "1.1.7",
    }


def test_open_reads_the_villa_room():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert len(project.rooms) == 1
    room = project.rooms[0]
    assert room.name == "Villa A1"
    assert room.floor == "1"
    assert room.building == "Villa A"
    assert len(room.device_ids) == 7


def test_open_reads_all_group_addresses():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert len(project.group_addresses) == 62
    addresses = [ga.address for ga in project.group_addresses]
    assert len(addresses) == len(set(addresses))


def test_open_reads_a_known_group_address_with_real_dpt():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)
    by_address = {ga.address: ga for ga in project.group_addresses}

    ga = by_address["1/1/0"]
    assert ga.name == "A1 G1 on/off"
    assert ga.dpt_main == 1
    assert ga.dpt_sub == 1


def test_open_reads_communication_objects():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert len(project.communication_objects) == 121


def test_open_reads_real_topology_area_and_line_naming():
    """Confirms the resort's addressing convention: Area = villa type
    ("Tipe A"), Line = specific villa instance ("A1") - previously only
    inferred from Semantic Export, now read directly."""
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    area1 = next(a for a in project.topology.areas if a.address == 1)
    assert area1.name == "Tipe A"

    line1 = next(line for line in area1.lines if line.address == 1)
    assert line1.name == "A1"
    assert set(line1.device_ids) == {d.individual_address for d in project.devices}


def test_open_reads_buildings_and_floors():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert len(project.buildings) == 1
    assert project.buildings[0].name == "Hot Stone"

    assert len(project.floors) == 1
    floor = project.floors[0]
    assert floor.name == "1"
    assert floor.building == "Villa A"


def test_open_reads_datapoint_types():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert len(project.datapoint_types) == 14
    dpts = {(d.main, d.sub) for d in project.datapoint_types}
    assert (1, 1) in dpts  # switch, from GA 1/1/0


def test_open_reads_manufacturers():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert project.manufacturers == ("BAB TECHNOLOGIE GmbH", "GVS")


def test_open_reads_products():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert len(project.products) == 5
    names = {p.hardware_name for p in project.products}
    assert "KNX Smart Touch S3" in names


def test_open_topology_lines_flattens_across_areas():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    assert len(project.topology.lines) == 21
    populated = [line for line in project.topology.lines if line.device_ids]
    assert len(populated) == 1
    assert populated[0].name == "A1"


def test_device_lookup_by_individual_address():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    device = project.device("1.1.1")
    assert device.name == "Binary Input for floating contact,4/8/16-Fold"


def test_device_lookup_by_name():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    device = project.device("Binary Input for floating contact,4/8/16-Fold")
    assert device.individual_address == "1.1.1"


def test_device_lookup_missing_raises_key_error():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    with pytest.raises(KeyError):
        project.device("does-not-exist")


def test_room_lookup_by_name():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    room = project.room("Villa A1")
    assert len(room.device_ids) == 7


def test_room_lookup_missing_raises_key_error():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    with pytest.raises(KeyError):
        project.room("does-not-exist")


def test_group_address_lookup_by_address():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    ga = project.group_address("1/1/0")
    assert ga.name == "A1 G1 on/off"


def test_group_address_lookup_missing_raises_key_error():
    project = ETSProject.open(REFERENCE_VILLA, password=PASSWORD)

    with pytest.raises(KeyError):
        project.group_address("9/9/9")


def test_open_with_wrong_password_raises_password_error():
    with pytest.raises(EtsProjectPasswordError):
        ETSProject.open(REFERENCE_VILLA, password="wrong-password")


def test_open_with_no_password_raises_password_error():
    with pytest.raises(EtsProjectPasswordError):
        ETSProject.open(REFERENCE_VILLA)


def test_open_missing_file_raises_error():
    with pytest.raises(EtsProjectError):
        ETSProject.open("does-not-exist.knxproj", password="12345")

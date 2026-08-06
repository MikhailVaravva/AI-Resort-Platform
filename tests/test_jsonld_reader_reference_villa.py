"""Integration tests against the real reference project (Villa A1, semantic export)."""

from pathlib import Path

from ai_resort_platform.readers.jsonld_reader import JsonLdImporter

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
REFERENCE_VILLA = _EXAMPLES_DIR / "Reference-Villa" / "reference_villa.jsonld"


def test_reference_villa_fixture_exists():
    assert REFERENCE_VILLA.exists(), "examples/Reference-Villa/reference_villa.jsonld is missing"


def test_reference_villa_project_name():
    project = JsonLdImporter().import_project(REFERENCE_VILLA)

    assert project.project_name == "Hot Stone"


def test_reference_villa_room():
    project = JsonLdImporter().import_project(REFERENCE_VILLA)

    assert len(project.rooms) == 1
    room = project.rooms[0]
    assert room.name == "Villa A1"
    assert room.floor == "1"
    assert room.building == "Villa A"
    assert len(room.device_ids) == 7


def test_reference_villa_device_individual_addresses():
    project = JsonLdImporter().import_project(REFERENCE_VILLA)

    addresses = {device.individual_address for device in project.devices}

    assert addresses == {"1.1.1", "1.1.2", "1.1.3", "1.1.4", "1.1.5", "1.1.6", "1.1.7"}


def test_reference_villa_group_address_count_and_uniqueness():
    project = JsonLdImporter().import_project(REFERENCE_VILLA)

    assert len(project.group_addresses) == 62
    addresses = [ga.address for ga in project.group_addresses]
    assert len(addresses) == len(set(addresses)), "group addresses must be unique after decoding"


def test_reference_villa_known_group_address():
    project = JsonLdImporter().import_project(REFERENCE_VILLA)
    by_address = {ga.address: ga for ga in project.group_addresses}

    ga = by_address["1/1/0"]
    assert ga.name == "A1 G1 on/off"
    assert ga.datapoint_type == "switch"
    assert ga.security == "Auto"


def test_reference_villa_communication_objects_reference_real_devices():
    project = JsonLdImporter().import_project(REFERENCE_VILLA)
    device_ids = {device.id for device in project.devices}

    linked = [co for co in project.communication_objects if co.device_id is not None]
    assert linked, "expected at least one communication object linked to a device"
    assert all(co.device_id in device_ids for co in linked)


def test_reference_villa_group_addresses_reference_real_communication_objects():
    project = JsonLdImporter().import_project(REFERENCE_VILLA)
    co_ids = {co.id for co in project.communication_objects}

    for ga in project.group_addresses:
        for co_id in ga.communication_object_ids:
            assert co_id in co_ids, f"{ga.address} references unknown communication object {co_id}"

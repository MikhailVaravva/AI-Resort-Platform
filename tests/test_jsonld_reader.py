from pathlib import Path

import pytest

from ai_resort_platform.readers.base import ProjectImportError
from ai_resort_platform.readers.jsonld_reader import JsonLdImporter

FIXTURE = Path(__file__).parent / "fixtures" / "sample_semantic_export.jsonld"


def test_source_name_is_jsonld():
    assert JsonLdImporter.source_name == "jsonld"


def test_import_project_reads_project_name():
    project = JsonLdImporter().import_project(FIXTURE)

    assert project.project_name == "Test Site"


def test_import_project_reads_installation_metadata():
    project = JsonLdImporter().import_project(FIXTURE)

    assert project.tool_version == "ETS 6.4.1 (Build 8718)"
    assert project.installation_state == "Tested"


def test_import_project_parses_rooms():
    project = JsonLdImporter().import_project(FIXTURE)

    assert len(project.rooms) == 1
    room = project.rooms[0]
    assert room.name == "Villa X1"
    assert room.floor == "1"
    assert room.building == "Villa X"
    assert room.device_ids == ("prj:DI-1",)


def test_import_project_parses_devices():
    project = JsonLdImporter().import_project(FIXTURE)

    assert len(project.devices) == 1
    device = project.devices[0]
    assert device.name == "Test Actuator"
    assert device.individual_address == "1.1.1"
    assert device.serial_number == "0012345"
    assert device.manufacturer == "Test Manufacturer"
    assert device.product_name == "Test Actuator Product"
    assert device.order_number == "TA-001"
    assert device.parameters == {}
    assert set(device.communication_object_ids) == {"prj:CO-1", "prj:DI-1_unlinked_O-9"}


def test_import_project_parses_group_addresses():
    project = JsonLdImporter().import_project(FIXTURE)

    assert len(project.group_addresses) == 1
    ga = project.group_addresses[0]
    assert ga.address == "1/1/0"
    assert ga.name == "X1 Light on/off"
    assert ga.description == "Test light"
    assert ga.datapoint_type == "switch"
    assert ga.security == "Auto"
    assert ga.readable is False
    assert ga.writable is True
    assert ga.communication_object_ids == ("prj:CO-1",)


def test_import_project_parses_communication_objects_linked_via_channel():
    project = JsonLdImporter().import_project(FIXTURE)
    by_id = {co.id: co for co in project.communication_objects}

    co = by_id["prj:CO-1"]
    assert co.name == "Output 1"
    assert co.device_id == "prj:DI-1"
    assert co.channel_id == "prj:CH-1"
    assert co.channel_name == "1 Bit"
    assert co.flags == "CWTU"
    assert co.datapoint_type == "switch"
    assert co.readable is False
    assert co.writable is True


def test_import_project_resolves_communication_object_not_grouped_by_any_channel():
    project = JsonLdImporter().import_project(FIXTURE)
    by_id = {co.id: co for co in project.communication_objects}

    co = by_id["prj:DI-1_unlinked_O-9"]
    assert co.device_id == "prj:DI-1"
    assert co.channel_id is None
    assert co.channel_name is None


def test_import_project_collects_datapoint_types():
    project = JsonLdImporter().import_project(FIXTURE)

    assert project.datapoint_types == ("switch",)


def test_import_project_missing_file_raises():
    with pytest.raises(ProjectImportError):
        JsonLdImporter().import_project(Path("does-not-exist.jsonld"))


def test_import_project_invalid_json_raises(tmp_path):
    bad_file = tmp_path / "broken.jsonld"
    bad_file.write_text("not json", encoding="utf-8")

    with pytest.raises(ProjectImportError):
        JsonLdImporter().import_project(bad_file)

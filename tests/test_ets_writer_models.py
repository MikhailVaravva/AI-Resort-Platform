from ai_resort_platform.clone_engine.models import ValidationResult
from ai_resort_platform.generators.ets.models import (
    ChangeKind,
    ObjectChange,
    ProjectChangeSet,
    SerializedProject,
    WriteResult,
)


def test_object_change_fields_default_to_empty_dict():
    change = ObjectChange(
        object_kind="group_address", change_kind=ChangeKind.UPDATE, object_id="ga-1"
    )

    assert change.fields == {}


def test_object_change_holds_only_changed_fields():
    change = ObjectChange(
        object_kind="group_address",
        change_kind=ChangeKind.UPDATE,
        object_id="ga-1",
        fields={"address": "1/2/0"},
    )

    assert change.change_kind is ChangeKind.UPDATE
    assert change.fields == {"address": "1/2/0"}


def test_project_change_set_defaults_to_no_changes():
    change_set = ProjectChangeSet(base_project_guid="31f9b2d9-7433-48d6-b127-1fea6c0c66b4")

    assert change_set.changes == ()


def test_project_change_set_holds_its_changes():
    change = ObjectChange(object_kind="room", change_kind=ChangeKind.UPDATE, object_id="r-1")
    change_set = ProjectChangeSet(base_project_guid="guid", changes=(change,))

    assert change_set.changes == (change,)


def test_serialized_project_defaults_to_no_fragments():
    change_set = ProjectChangeSet(base_project_guid="guid")

    serialized = SerializedProject(change_set=change_set)

    assert serialized.xml_fragments == {}


def test_write_result_defaults_to_no_output_path():
    result = WriteResult(validation=ValidationResult())

    assert result.output_path is None

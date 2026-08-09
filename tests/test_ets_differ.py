from ai_resort_platform.generators.ets.differ import (
    PARAMETER_FIELD_PREFIX,
    ModelProjectDiffer,
)
from ai_resort_platform.generators.ets.models import ChangeKind
from ai_resort_platform.models.project import (
    CommunicationObject,
    Device,
    GroupAddress,
    ProjectModel,
    Room,
)

GUID = "31f9b2d9-7433-48d6-b127-1fea6c0c66b4"


def differ() -> ModelProjectDiffer:
    return ModelProjectDiffer(base_project_guid=GUID)


def project(**kwargs: object) -> ProjectModel:
    return ProjectModel(project_name="Hot Stone VILLA", **kwargs)  # type: ignore[arg-type]


def test_identical_projects_produce_no_changes():
    ga = GroupAddress(id="ga-1", address="1/1/202", name="Audio Power")
    snapshot = project(group_addresses=(ga,))

    change_set = differ().diff(snapshot, snapshot)

    assert change_set.changes == ()
    assert change_set.base_project_guid == GUID


def test_unchanged_object_alongside_a_changed_one_produces_no_change():
    untouched = GroupAddress(id="ga-1", address="1/1/202", name="Audio Power")
    before = GroupAddress(id="ga-2", address="1/1/220", name="Audio Mute")
    after = GroupAddress(id="ga-2", address="1/2/0", name="Audio Mute")

    change_set = differ().diff(
        project(group_addresses=(untouched, before)),
        project(group_addresses=(untouched, after)),
    )

    assert [c.object_id for c in change_set.changes] == ["ga-2"]


def test_update_carries_only_the_changed_field():
    before = GroupAddress(id="ga-1", address="1/1/202", name="Audio Power")
    after = GroupAddress(id="ga-1", address="1/2/0", name="Audio Power")

    (change,) = (
        differ().diff(project(group_addresses=(before,)), project(group_addresses=(after,))).changes
    )

    assert change.object_kind == "group_address"
    assert change.change_kind is ChangeKind.UPDATE
    assert change.object_id == "ga-1"
    assert change.fields == {"address": "1/2/0"}


def test_create_describes_the_new_object_in_full():
    created = GroupAddress(id="ga-9", address="1/1/240", name="New", writable=True)

    (change,) = differ().diff(project(), project(group_addresses=(created,))).changes

    assert change.change_kind is ChangeKind.CREATE
    assert change.fields["address"] == "1/1/240"
    assert change.fields["name"] == "New"
    # ETS XML booleans are lowercase, and False is still stated on a CREATE.
    assert change.fields["writable"] == "true"
    assert change.fields["readable"] == "false"
    # datapoint_type/security are None on this object and say nothing.
    assert "datapoint_type" not in change.fields
    assert "security" not in change.fields


def test_delete_names_the_object_and_carries_no_fields():
    removed = Room(id="r-1", name="Bedroom")

    (change,) = differ().diff(project(rooms=(removed,)), project()).changes

    assert change.object_kind == "room"
    assert change.change_kind is ChangeKind.DELETE
    assert change.object_id == "r-1"
    assert change.fields == {}


def test_id_tuples_are_encoded_as_a_comma_separated_list():
    before = Room(id="r-1", name="Bedroom", device_ids=("d-1",))
    after = Room(id="r-1", name="Bedroom", device_ids=("d-1", "d-2"))

    (change,) = differ().diff(project(rooms=(before,)), project(rooms=(after,))).changes

    assert change.fields == {"device_ids": "d-1,d-2"}


def test_a_value_becoming_none_is_not_an_instruction_to_clear_it():
    """Section 12: an absent value means 'not captured', never 'delete it'."""
    before = Device(id="d-1", name="Dimmer", individual_address="1.1.1", serial_number="ABC123")
    after = Device(id="d-1", name="Dimmer", individual_address="1.1.1", serial_number=None)

    change_set = differ().diff(project(devices=(before,)), project(devices=(after,)))

    assert change_set.changes == ()


def test_changed_parameters_are_namespaced_and_emitted_one_at_a_time():
    before = Device(
        id="d-1",
        name="Dimmer",
        individual_address="1.1.1",
        parameters={"ramp_time": "2s", "mode": "dim"},
    )
    after = Device(
        id="d-1",
        name="Dimmer",
        individual_address="1.1.1",
        parameters={"ramp_time": "5s", "mode": "dim"},
    )

    (change,) = differ().diff(project(devices=(before,)), project(devices=(after,))).changes

    # "mode" is unchanged and must not be restated.
    assert change.fields == {f"{PARAMETER_FIELD_PREFIX}ramp_time": "5s"}


def test_a_parameter_named_like_an_attribute_does_not_collide_with_it():
    before = Device(id="d-1", name="Dimmer", individual_address="1.1.1")
    after = Device(
        id="d-1", name="Hallway Dimmer", individual_address="1.1.1", parameters={"name": "internal"}
    )

    (change,) = differ().diff(project(devices=(before,)), project(devices=(after,))).changes

    assert change.fields == {
        "name": "Hallway Dimmer",
        f"{PARAMETER_FIELD_PREFIX}name": "internal",
    }


def test_emptied_parameters_never_produce_a_change():
    """Section 12: the Writer must never read an empty dict as 'no parameters'."""
    before = Device(
        id="d-1", name="Dimmer", individual_address="1.1.1", parameters={"ramp_time": "2s"}
    )
    after = Device(id="d-1", name="Dimmer", individual_address="1.1.1", parameters={})

    assert differ().diff(project(devices=(before,)), project(devices=(after,))).changes == ()


def test_communication_objects_are_never_diffed():
    """Section 9: they are product-defined, not authored by this platform."""
    device = Device(id="d-1", name="D", individual_address="1.1.1")
    before = project(
        devices=(device,),
        communication_objects=(CommunicationObject(id="co-1", name="Switch", flags="CWTU"),),
    )
    after = project(
        devices=(device,),
        communication_objects=(
            CommunicationObject(id="co-1", name="Renamed", flags="CRT"),
            CommunicationObject(id="co-2", name="Brand new"),
        ),
    )

    assert differ().diff(before, after).changes == ()


def test_group_address_connections_are_diffed_even_though_objects_are_not():
    before = GroupAddress(id="ga-1", address="1/1/202", name="Power")
    after = GroupAddress(
        id="ga-1", address="1/1/202", name="Power", communication_object_ids=("co-1",)
    )

    (change,) = (
        differ().diff(project(group_addresses=(before,)), project(group_addresses=(after,))).changes
    )

    assert change.fields == {"communication_object_ids": "co-1"}


def test_changes_are_ordered_by_kind_then_updates_before_deletes():
    before = project(
        rooms=(Room(id="r-1", name="Old"),),
        devices=(Device(id="d-gone", name="D", individual_address="1.1.9"),),
        group_addresses=(GroupAddress(id="ga-1", address="1/1/1", name="GA"),),
    )
    after = project(
        rooms=(Room(id="r-1", name="New"),),
        devices=(Device(id="d-new", name="D", individual_address="1.1.8"),),
        group_addresses=(GroupAddress(id="ga-1", address="1/1/2", name="GA"),),
    )

    change_set = differ().diff(before, after)

    assert [(c.object_kind, c.change_kind, c.object_id) for c in change_set.changes] == [
        ("room", ChangeKind.UPDATE, "r-1"),
        ("device", ChangeKind.CREATE, "d-new"),
        ("device", ChangeKind.DELETE, "d-gone"),
        ("group_address", ChangeKind.UPDATE, "ga-1"),
    ]


def test_diffing_is_reproducible_for_the_same_snapshots():
    before = project(rooms=(Room(id="r-1", name="Old"), Room(id="r-2", name="Keep")))
    after = project(rooms=(Room(id="r-1", name="New"), Room(id="r-2", name="Keep")))

    assert differ().diff(before, after) == differ().diff(before, after)

from ai_resort_platform.clone_engine.models import (
    AddressMapping,
    CloneMapping,
    CloneProfile,
    CloneResult,
    ConflictKind,
    DeviceMapping,
    GroupAddressMapping,
    RoomMapping,
    SceneMapping,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from ai_resort_platform.digital_twin.models import Villa


def test_clone_profile_fields():
    profile = CloneProfile(
        source_villa_id="v-1", target_villa_name="Villa A2", target_villa_code="A2"
    )

    assert profile.source_villa_id == "v-1"
    assert profile.target_villa_name == "Villa A2"
    assert profile.target_villa_code == "A2"


def test_address_mapping_is_format_agnostic_for_individual_and_group_addresses():
    individual = AddressMapping(source_address="1.1.5", target_address="1.2.5")
    group = AddressMapping(source_address="1/1/0", target_address="1/2/0")

    assert individual.target_address == "1.2.5"
    assert group.target_address == "1/2/0"


def test_device_mapping_holds_its_individual_address_mapping():
    mapping = DeviceMapping(
        source_device_id="d-1",
        target_device_id="d-1-clone",
        individual_address=AddressMapping(source_address="1.1.5", target_address="1.2.5"),
    )

    assert mapping.individual_address.target_address == "1.2.5"


def test_group_address_mapping_holds_its_address_mapping():
    mapping = GroupAddressMapping(
        source_group_address_id="ga-1",
        target_group_address_id="ga-1-clone",
        address=AddressMapping(source_address="1/1/0", target_address="1/2/0"),
    )

    assert mapping.address.target_address == "1/2/0"


def test_room_mapping_defaults_to_no_devices():
    mapping = RoomMapping(source_room_id="r-1", target_room_id="r-1-clone", target_name="Bedroom")

    assert mapping.device_ids == ()


def test_scene_mapping_preserves_number_by_default():
    mapping = SceneMapping(source_scene_id="s-1", target_scene_id="s-1-clone", number=3)

    assert mapping.number == 3
    assert mapping.control_address is None
    assert mapping.status_address is None


def test_clone_mapping_defaults_to_empty_collections():
    profile = CloneProfile(
        source_villa_id="v-1", target_villa_name="Villa A2", target_villa_code="A2"
    )
    mapping = CloneMapping(profile=profile)

    assert mapping.device_mappings == ()
    assert mapping.group_address_mappings == ()
    assert mapping.room_mappings == ()
    assert mapping.scene_mappings == ()


def test_validation_result_is_valid_when_no_errors():
    result = ValidationResult(
        issues=(
            ValidationIssue(rule="minor_issue", severity=ValidationSeverity.WARNING, message="hm"),
        )
    )

    assert result.is_valid


def test_validation_result_is_invalid_when_any_error_present():
    result = ValidationResult(
        issues=(
            ValidationIssue(rule="ok", severity=ValidationSeverity.WARNING, message="fine"),
            ValidationIssue(rule="bad", severity=ValidationSeverity.ERROR, message="not fine"),
        )
    )

    assert not result.is_valid


def test_validation_result_with_no_issues_is_valid():
    assert ValidationResult().is_valid


def test_conflict_kind_has_four_members():
    assert {k.value for k in ConflictKind} == {
        "individual_address_collision",
        "group_address_collision",
        "villa_identity_collision",
        "internal_address_collision",
    }


def test_clone_result_defaults_to_no_villa_or_mapping():
    result = CloneResult(validation=ValidationResult())

    assert result.villa is None
    assert result.mapping is None


def test_clone_result_can_hold_a_successful_outcome():
    profile = CloneProfile(
        source_villa_id="v-1", target_villa_name="Villa A2", target_villa_code="A2"
    )
    mapping = CloneMapping(profile=profile)
    villa = Villa(id="v-1-clone", name="Villa A2")

    result = CloneResult(validation=ValidationResult(), mapping=mapping, villa=villa)

    assert result.villa is villa
    assert result.mapping is mapping

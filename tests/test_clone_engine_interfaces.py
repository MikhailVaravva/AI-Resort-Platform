import pytest

from ai_resort_platform.clone_engine.engine import (
    AddressAllocator,
    CloneEngine,
    CloneValidator,
    ConflictDetector,
)
from ai_resort_platform.clone_engine.models import (
    CloneMapping,
    CloneProfile,
    CloneResult,
    ValidationResult,
)
from ai_resort_platform.digital_twin.models import Resort


@pytest.mark.parametrize(
    "abstract_class",
    [AddressAllocator, CloneValidator, ConflictDetector, CloneEngine],
)
def test_clone_engine_interfaces_cannot_be_instantiated_directly(abstract_class):
    with pytest.raises(TypeError):
        abstract_class()


class _DummyAddressAllocator(AddressAllocator):
    def allocate_individual_address(self, source_address: str, profile: CloneProfile) -> str:
        return source_address

    def allocate_group_address(self, source_address: str, profile: CloneProfile) -> str:
        return source_address


class _DummyValidator(CloneValidator):
    def validate_profile(self, profile: CloneProfile, resort: Resort) -> ValidationResult:
        return ValidationResult()


class _DummyConflictDetector(ConflictDetector):
    def detect_conflicts(self, resort: Resort, mapping: CloneMapping) -> ValidationResult:
        return ValidationResult()


class _DummyCloneEngine(CloneEngine):
    def clone(self, resort: Resort, profile: CloneProfile) -> CloneResult:
        return CloneResult(validation=ValidationResult())


def test_concrete_address_allocator_implements_contract():
    allocator = _DummyAddressAllocator()
    profile = CloneProfile(
        source_villa_id="v-1", target_villa_name="Villa A2", target_villa_code="A2"
    )

    assert allocator.allocate_individual_address("1.1.5", profile) == "1.1.5"
    assert allocator.allocate_group_address("1/1/0", profile) == "1/1/0"


def test_concrete_validator_implements_contract():
    validator = _DummyValidator()
    profile = CloneProfile(
        source_villa_id="v-1", target_villa_name="Villa A2", target_villa_code="A2"
    )

    result = validator.validate_profile(profile, Resort(name="Resort"))

    assert result.is_valid


def test_concrete_conflict_detector_implements_contract():
    detector = _DummyConflictDetector()
    profile = CloneProfile(
        source_villa_id="v-1", target_villa_name="Villa A2", target_villa_code="A2"
    )

    result = detector.detect_conflicts(Resort(name="Resort"), CloneMapping(profile=profile))

    assert result.is_valid


def test_concrete_clone_engine_implements_contract():
    engine = _DummyCloneEngine()
    profile = CloneProfile(
        source_villa_id="v-1", target_villa_name="Villa A2", target_villa_code="A2"
    )

    result = engine.clone(Resort(name="Resort"), profile)

    assert isinstance(result, CloneResult)

from dataclasses import dataclass, field
from enum import Enum

from ai_resort_platform.digital_twin.models import Villa


@dataclass(frozen=True, slots=True)
class CloneProfile:
    """Describes one villa to produce by cloning a reference villa.

    Only identity/target intent lives here. *How* source addresses become
    target addresses is an AddressAllocator's job (a pluggable strategy) -
    keeping that out of the profile means the same profile shape works
    under any addressing convention the resort chooses.
    """

    source_villa_id: str
    target_villa_name: str
    # e.g. "A2" - replaces "A1" in cloned names ("A1 G1 on/off" -> "A2 G1 on/off")
    target_villa_code: str


@dataclass(frozen=True, slots=True)
class AddressMapping:
    """One source-address -> target-address correspondence.

    The same shape is used for individual addresses ("1.1.5" -> "1.2.5")
    and group addresses ("1/1/0" -> "1/2/0") - both are just address
    strings, and nothing here needs to know which kind it is.
    """

    source_address: str
    target_address: str


@dataclass(frozen=True, slots=True)
class DeviceMapping:
    """Source device -> cloned device, plus its individual-address remap."""

    source_device_id: str
    target_device_id: str
    individual_address: AddressMapping


@dataclass(frozen=True, slots=True)
class GroupAddressMapping:
    """Source group address -> cloned group address.

    Only the address and identity are remapped here. Communication-object
    links, DPTs, security mode etc. are copied verbatim from the source by
    whatever builds the cloned Villa - they don't change between clones.
    """

    source_group_address_id: str
    target_group_address_id: str
    address: AddressMapping


@dataclass(frozen=True, slots=True)
class RoomMapping:
    """Source room -> cloned room.

    digital_twin.Room is currently always empty (see digital_twin/models.py)
    since no source data has sub-villa room granularity yet - so
    CloneMapping.room_mappings is correspondingly empty until it does. This
    type exists now so that stays a data fact, not an architecture change,
    once such a source is available.
    """

    source_room_id: str
    target_room_id: str
    target_name: str
    device_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SceneMapping:
    """Source scene -> cloned scene.

    Scene *numbers* are preserved by default (a scene's meaning is
    positional, not addressed) - only the control/status group addresses
    are remapped, via the same GroupAddressMapping already computed for
    those group addresses.
    """

    source_scene_id: str
    target_scene_id: str
    number: int | None
    control_address: AddressMapping | None = None
    status_address: AddressMapping | None = None


@dataclass(frozen=True, slots=True)
class CloneMapping:
    """The complete source -> target mapping produced for one CloneProfile.

    This is the data a CloneEngine hands to whatever materializes the
    cloned Villa - itself out of scope for this step (see module docstring
    in engine.py).
    """

    profile: CloneProfile
    device_mappings: tuple[DeviceMapping, ...] = field(default_factory=tuple)
    group_address_mappings: tuple[GroupAddressMapping, ...] = field(default_factory=tuple)
    room_mappings: tuple[RoomMapping, ...] = field(default_factory=tuple)
    scene_mappings: tuple[SceneMapping, ...] = field(default_factory=tuple)


class ValidationSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One finding from CloneValidator or ConflictDetector.

    `rule` is a short, stable, machine-matchable name (e.g.
    "duplicate_group_address", "empty_target_villa_code") - free-form
    rather than a closed enum, since the set of validation rules is
    expected to grow; `ConflictKind` below IS a closed enum, because
    address-collision kinds are structurally fixed by the KNX addressing
    model itself.
    """

    rule: str
    severity: ValidationSeverity
    message: str
    context: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity is ValidationSeverity.ERROR for issue in self.issues)


class ConflictKind(Enum):
    """The closed set of address-collision kinds a ConflictDetector checks for."""

    INDIVIDUAL_ADDRESS_COLLISION = "individual_address_collision"
    GROUP_ADDRESS_COLLISION = "group_address_collision"
    VILLA_IDENTITY_COLLISION = "villa_identity_collision"
    INTERNAL_ADDRESS_COLLISION = "internal_address_collision"


@dataclass(frozen=True, slots=True)
class CloneResult:
    """The outcome of CloneEngine.clone().

    `villa` and `mapping` are None when `validation.is_valid` is False -
    a failed clone attempt never returns a partially-built Villa.
    """

    validation: ValidationResult
    mapping: CloneMapping | None = None
    villa: Villa | None = None

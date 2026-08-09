from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ai_resort_platform.clone_engine.models import ValidationResult


class ChangeKind(Enum):
    """What kind of edit one ObjectChange represents."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class ObjectChange:
    """One change to a single ETS object, identified by its stable id.

    `object_id` is the id the Reader captured for this object
    (GroupAddress.id, Device.id, ...) for UPDATE/DELETE; for CREATE it is
    the id IdentityStrategy minted for the new object - see
    generators/ets/writer.py.

    `fields` holds only the attributes that actually change (e.g.
    {"address": "1/2/0"} for a renumber). Anything not listed here is left
    exactly as the base project had it - see docs/ets-writer-architecture.md
    section 1 ("patch, don't regenerate").
    """

    object_kind: str  # "group_address" | "device" | "room" | "scene"
    change_kind: ChangeKind
    object_id: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProjectChangeSet:
    """Every change to apply to one base .knxproj in a single write."""

    base_project_guid: str
    changes: tuple[ObjectChange, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SerializedProject:
    """The output of the Serialization pipeline: ETS-shaped fragments ready
    for the Update pipeline to merge into a base .knxproj.

    Design-only placeholder shape - see docs/ets-writer-architecture.md
    section 4. `xml_fragments` maps an object id to the serialized XML text
    that should replace/create that object's element.
    """

    change_set: ProjectChangeSet
    xml_fragments: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WriteResult:
    """The outcome of EtsWriter.write().

    `output_path` is None whenever `validation.is_valid` is False - a
    failed write never produces a partial/corrupt output file.
    """

    validation: ValidationResult
    output_path: Path | None = None

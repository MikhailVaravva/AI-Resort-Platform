"""The first concrete ProjectDiffer - stage 1 of the Serialization pipeline.

This is the one pipeline stage that is *not* blocked on the open schema
questions in docs/ets-writer-architecture.md section 18: it compares two
ProjectModel snapshots and never looks at project.xml, so it is equally
correct under either implementation strategy in section 19 (direct XML
patching or an ETS App). EtsSerializer and EtsWriter stay unimplemented
until that choice is made.

Three design rules from the architecture doc are load-bearing here:

- Section 4: an object present in both snapshots with no field differences
  produces no ObjectChange at all. "Preserve everything not intentionally
  modified" is therefore a consequence of the diff rather than a rule every
  caller has to remember.
- Section 9: communication objects are never diffed. They are defined by a
  device's application program, not authored by this platform; what we
  actually control is which group addresses connect to them, which is
  carried by the `communication_object_ids` fields on Device and
  GroupAddress.
- Section 12: an absent value is not an instruction to delete. The
  importers leave unknown fields as None and Device.parameters empty, so
  emitting a change for those would tell the Writer to erase real ETS
  configuration we simply never saw.

Section 12's rule is applied to every field, not only to parameters: a
field that changes from a value to None produces no change. The
consequence is that this differ cannot express an *intentional* clear
("remove this device's serial number"). Doing so needs an explicit
sentinel in ObjectChange.fields, which is a change to the Step 6 design
rather than something to invent here.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ai_resort_platform.generators.ets.models import (
    ChangeKind,
    ObjectChange,
    ProjectChangeSet,
)
from ai_resort_platform.generators.ets.writer import ProjectDiffer
from ai_resort_platform.models.project import Device, ProjectModel


class _Identified(Protocol):
    """Structural type for the model objects this differ can compare."""

    @property
    def id(self) -> str: ...


# Extra fields an object kind contributes beyond its plain attributes,
# given (original_or_None, updated). Only devices have one, for parameters.
type _ExtraFields[T] = Callable[[T | None, T], dict[str, str]]

# Diffed field names per object kind, listed explicitly rather than derived
# from the dataclass so that adding a field to models/project.py does not
# silently start emitting an untested kind of ObjectChange.
_ROOM_FIELDS = ("name", "floor", "building", "device_ids")
# Device.parameters is deliberately absent here - it goes through
# _changed_parameters instead, under section 12's rule.
_DEVICE_FIELDS = (
    "name",
    "individual_address",
    "serial_number",
    "manufacturer",
    "product_name",
    "order_number",
    "communication_object_ids",
)
_GROUP_ADDRESS_FIELDS = (
    "address",
    "name",
    "description",
    "datapoint_type",
    "security",
    "readable",
    "writable",
    "communication_object_ids",
)

PARAMETER_FIELD_PREFIX = "parameter:"
"""Prefix marking a Device.parameters entry inside ObjectChange.fields.

Parameters are namespaced rather than merged into the flat field dict so a
parameter that happens to be named "name" cannot collide with the device's
own name attribute.
"""


def _encode(value: object) -> str | None:
    """Render a model field as the string ObjectChange.fields carries.

    Returns None for a value that must not produce a change at all - see
    the module docstring on section 12.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # ETS XML attributes are lowercase booleans, not Python's "True".
        return "true" if value else "false"
    if isinstance(value, tuple):
        return ",".join(value)
    return str(value)


def _index[T: _Identified](objects: Iterable[T]) -> dict[str, T]:
    return {obj.id: obj for obj in objects}


def _changed_fields(original: object, updated: object, names: Sequence[str]) -> dict[str, str]:
    changed: dict[str, str] = {}
    for name in names:
        new_value = getattr(updated, name)
        if getattr(original, name) == new_value:
            continue
        encoded = _encode(new_value)
        if encoded is None:
            continue
        changed[name] = encoded
    return changed


def _created_fields(created: object, names: Sequence[str]) -> dict[str, str]:
    """Every known field of a new object - a CREATE describes it in full."""
    fields: dict[str, str] = {}
    for name in names:
        encoded = _encode(getattr(created, name))
        if encoded is not None:
            fields[name] = encoded
    return fields


def _changed_parameters(original: Device | None, updated: Device) -> dict[str, str]:
    """Parameter changes, one value at a time (section 12).

    Only parameters present in `updated` are ever emitted. A parameter the
    original had and the update does not is treated as "not captured",
    never as "delete it" - the importers cannot currently populate
    parameters at all, so an empty dict carries no intent.
    """
    previous = original.parameters if original is not None else {}
    return {
        f"{PARAMETER_FIELD_PREFIX}{key}": value
        for key, value in updated.parameters.items()
        if previous.get(key) != value
    }


@dataclass(frozen=True, slots=True)
class ModelProjectDiffer(ProjectDiffer):
    """Diffs two ProjectModel snapshots by object id.

    `base_project_guid` is the ProjectGuid of the .knxproj being patched.
    It is supplied here rather than read from the models because
    ProjectModel does not carry it, and because per section 7 editing an
    existing project never changes it - the value is a property of the
    base archive, not of either snapshot.
    """

    base_project_guid: str

    def diff(self, original: ProjectModel, updated: ProjectModel) -> ProjectChangeSet:
        changes = [
            *_diff_kind("room", original.rooms, updated.rooms, _ROOM_FIELDS),
            *_diff_kind(
                "device",
                original.devices,
                updated.devices,
                _DEVICE_FIELDS,
                extra_fields=_changed_parameters,
            ),
            *_diff_kind(
                "group_address",
                original.group_addresses,
                updated.group_addresses,
                _GROUP_ADDRESS_FIELDS,
            ),
        ]
        return ProjectChangeSet(base_project_guid=self.base_project_guid, changes=tuple(changes))


def _diff_kind[T: _Identified](
    object_kind: str,
    original: Sequence[T],
    updated: Sequence[T],
    names: Sequence[str],
    extra_fields: _ExtraFields[T] | None = None,
) -> list[ObjectChange]:
    """CREATEs and UPDATEs in `updated` order, then DELETEs in `original` order.

    The order is fixed so that the same pair of snapshots always produces
    the same changeset; the Update pipeline locates each element by id and
    does not otherwise depend on it.
    """
    original_by_id = _index(original)
    updated_by_id = _index(updated)
    changes: list[ObjectChange] = []

    for obj in updated:
        previous = original_by_id.get(obj.id)
        if previous is None:
            fields = _created_fields(obj, names)
        else:
            fields = _changed_fields(previous, obj, names)
        if extra_fields is not None:
            fields.update(extra_fields(previous, obj))
        if previous is not None and not fields:
            # Section 4: no differences means no ObjectChange at all.
            continue
        changes.append(
            ObjectChange(
                object_kind=object_kind,
                change_kind=ChangeKind.CREATE if previous is None else ChangeKind.UPDATE,
                object_id=obj.id,
                fields=fields,
            )
        )

    changes.extend(
        ObjectChange(
            object_kind=object_kind,
            change_kind=ChangeKind.DELETE,
            object_id=obj.id,
        )
        for obj in original
        if obj.id not in updated_by_id
    )
    return changes

import re

from ai_resort_platform.digital_twin.models import (
    Capability,
    Device,
    Entity,
    Resort,
    Scene,
    Villa,
)
from ai_resort_platform.models import project as pm

_VILLA_CODE_PREFIX = re.compile(r"^[A-Z]\d+\s+")
# Source names pair a command GA with its status GA inconsistently - sometimes
# "X status", sometimes "X, status" (stray comma) - both must strip to "X".
_STATUS_SUFFIX = re.compile(r"[,\s]+status$", re.IGNORECASE)
# "value" is a low-information trailing word some command GAs use that their
# paired status GA omits (e.g. "Red value" / "Red status") - strip it from
# both so the pair lands on the same entity key.
_VALUE_SUFFIX = re.compile(r"\s+value$", re.IGNORECASE)
_TRAILING_NOISE = re.compile(r"[,\s]+$")
_GROUP_TOKEN = re.compile(r"\bG(\d+)\b", re.IGNORECASE)
_SCENE_NUMBER = re.compile(r"\bscene\s+(\d+)\b", re.IGNORECASE)

_SCENE_CONTROL_DPT = "sceneControl"


def build_resort(project: pm.ProjectModel) -> Resort:
    """Build a digital twin Resort from a ProjectModel.

    Each ProjectModel.Room becomes one Villa: in the reference project (and,
    per its own naming - "Villa A1" - in ETS's semantic export generally) a
    "loc:Room" node is the deployed villa unit itself, not a room within a
    building. Actual sub-villa rooms (see digital_twin.models.Room) are left
    empty until a source with that granularity is available.
    """
    devices_by_id = {device.id: device for device in project.devices}
    gas_by_communication_object = _index_group_addresses_by_communication_object(project)

    villas = tuple(
        _build_villa(room, project, devices_by_id, gas_by_communication_object)
        for room in project.rooms
    )
    return Resort(name=project.project_name, villas=villas)


def _index_group_addresses_by_communication_object(
    project: pm.ProjectModel,
) -> dict[str, list[pm.GroupAddress]]:
    index: dict[str, list[pm.GroupAddress]] = {}
    for ga in project.group_addresses:
        for communication_object_id in ga.communication_object_ids:
            index.setdefault(communication_object_id, []).append(ga)
    return index


def _build_villa(
    room: pm.Room,
    project: pm.ProjectModel,
    devices_by_id: dict[str, pm.Device],
    gas_by_communication_object: dict[str, list[pm.GroupAddress]],
) -> Villa:
    devices = [
        devices_by_id[device_id] for device_id in room.device_ids if device_id in devices_by_id
    ]
    device_ids = {device.id for device in devices}

    communication_objects = [
        co for co in project.communication_objects if co.device_id in device_ids
    ]
    group_address_ids = {
        ga.id for co in communication_objects for ga in gas_by_communication_object.get(co.id, [])
    }
    villa_group_addresses = [ga for ga in project.group_addresses if ga.id in group_address_ids]

    scenes, remaining_group_addresses = _extract_scenes(room.id, villa_group_addresses)
    entities = _build_entities(room.id, remaining_group_addresses)

    return Villa(
        id=room.id,
        name=room.name,
        villa_type=room.building,
        devices=tuple(_build_device(device) for device in devices),
        entities=entities,
        scenes=scenes,
    )


def _build_device(device: pm.Device) -> Device:
    return Device(
        id=device.id,
        name=device.name,
        individual_address=device.individual_address,
        manufacturer=device.manufacturer,
        product_name=device.product_name,
        serial_number=device.serial_number,
    )


def _strip_villa_code(name: str) -> str:
    """Strip a leading villa code ("A1 ", "B4 ", ...) from a group address name."""
    return _VILLA_CODE_PREFIX.sub("", name, count=1)


def _extract_scenes(
    villa_id: str, group_addresses: list[pm.GroupAddress]
) -> tuple[tuple[Scene, ...], list[pm.GroupAddress]]:
    """Pull scene-related group addresses out into Scene objects.

    Detected by the "sceneControl" datapoint type (the recall/store control
    point) and by a "Scene N" name pattern (per-scene status points). This is
    a naming/DPT heuristic, not derived from ETS parameters - see
    digital_twin.models.Scene.
    """
    control_gas = [ga for ga in group_addresses if ga.datapoint_type == _SCENE_CONTROL_DPT]
    control_ga = control_gas[0] if control_gas else None
    control_address = control_ga.address if control_ga else None
    consumed_ids = {ga.id for ga in control_gas}

    scenes: list[Scene] = []
    if control_ga is not None:
        scenes.append(
            Scene(
                id=f"{villa_id}:{control_ga.id}",
                name=_strip_villa_code(control_ga.name),
                control_group_address=control_address,
            )
        )

    remaining: list[pm.GroupAddress] = []
    for ga in group_addresses:
        if ga.id in consumed_ids:
            continue
        match = _SCENE_NUMBER.search(_strip_villa_code(ga.name))
        if match is None:
            remaining.append(ga)
            continue
        scenes.append(
            Scene(
                id=f"{villa_id}:{ga.id}",
                name=_strip_villa_code(ga.name),
                number=int(match.group(1)),
                control_group_address=control_address,
                status_group_address=ga.address,
            )
        )

    return tuple(scenes), remaining


def _build_entities(villa_id: str, group_addresses: list[pm.GroupAddress]) -> tuple[Entity, ...]:
    """Group group addresses into Entities/Capabilities.

    Grouping is a best-effort, name-based heuristic (the source project has
    no explicit "entity" concept):
    - a "G<N>" token (e.g. "G1") is treated as an explicit entity marker;
    - everything else keeps its own name (after stripping a trailing
      "status"/"value" suffix, to pair a command GA with its status GA) as
      a single-capability entity, rather than risk merging unrelated
      functions together.

    Within one entity, capabilities are distinguished by KNX datapoint type,
    which is reliable here: every group of GAs sharing an entity key uses a
    distinct datapoint type per capability (verified against the reference
    project). Some real GA pairs still don't merge (e.g. "Audio Absolut
    volume" vs "Audio Volume status" share no common wording at all) - that
    is a known limitation of matching on names, not something this fixes.
    """
    entity_names: dict[str, str] = {}
    slots: dict[str, dict[str, dict[str, pm.GroupAddress]]] = {}

    for ga in group_addresses:
        remainder = _strip_villa_code(ga.name)
        is_status = bool(_STATUS_SUFFIX.search(remainder))
        base = _STATUS_SUFFIX.sub("", remainder) if is_status else remainder
        base = _VALUE_SUFFIX.sub("", base)
        base = _TRAILING_NOISE.sub("", base).strip()

        group_match = _GROUP_TOKEN.search(base)
        entity_key = f"G{group_match.group(1)}" if group_match else base
        entity_names.setdefault(entity_key, entity_key if group_match else base)

        kind = ga.datapoint_type or "unknown"
        role = "status" if is_status else "command"
        slots.setdefault(entity_key, {}).setdefault(kind, {})[role] = ga

    entities = []
    for entity_key, kinds in slots.items():
        capabilities = tuple(
            Capability(
                kind=kind,
                command_group_address=_address_of(roles.get("command")),
                status_group_address=_address_of(roles.get("status")),
            )
            for kind, roles in kinds.items()
        )
        entities.append(
            Entity(
                id=f"{villa_id}:{entity_key}",
                name=entity_names[entity_key],
                capabilities=capabilities,
            )
        )

    return tuple(entities)


def _address_of(ga: pm.GroupAddress | None) -> str | None:
    return ga.address if ga is not None else None

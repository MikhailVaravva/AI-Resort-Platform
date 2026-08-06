import json
from pathlib import Path
from typing import Any

from ai_resort_platform.models.project import (
    CommunicationObject,
    Device,
    GroupAddress,
    ProjectModel,
    Room,
)
from ai_resort_platform.readers.base import ProjectImporter, ProjectImportError


def _as_list(value: Any) -> list[Any]:
    """JSON-LD collapses single-item lists to a bare value - undo that."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _node_types(node: dict[str, Any]) -> list[str]:
    return _as_list(node.get("@type"))


def _ref_id(value: Any) -> str | None:
    """Extract the @id from a {"@id": "..."} reference, if present."""
    if isinstance(value, dict):
        ref = value.get("@id")
        return ref if isinstance(ref, str) else None
    return None


def _ref_ids(value: Any) -> tuple[str, ...]:
    return tuple(ref for ref in (_ref_id(v) for v in _as_list(value)) if ref is not None)


def _literal(value: Any) -> Any:
    """Unwrap a JSON-LD {"@value": ..., "@type": ...} literal, if wrapped."""
    if isinstance(value, dict) and "@value" in value:
        return value["@value"]
    return value


def _bool_literal(value: Any) -> bool:
    return str(_literal(value)) == "True"


def _strip_namespace(value: str | None) -> str | None:
    if value is None:
        return None
    return value.split(":", 1)[1] if ":" in value else value


def _decode_group_address(raw: int) -> str:
    """Standard 3-level KNX group address encoding: 5/3/8 bits."""
    main = raw >> 11
    middle = (raw >> 8) & 0x07
    sub = raw & 0xFF
    return f"{main}/{middle}/{sub}"


def _decode_individual_address(raw: int) -> str:
    """KNX individual address as encoded by ETS semantic export: area*1000 + line*100 + device."""
    area, remainder = divmod(raw, 1000)
    line, device = divmod(remainder, 100)
    return f"{area}.{line}.{device}"


class JsonLdImporter(ProjectImporter):
    """Reads an ETS "Semantic Export" (JSON-LD) file into a ProjectModel.

    This is the primary project source (see readers/base.py). The semantic
    export is an official ETS6 feature (File -> Export -> Json Linked Data),
    not subject to the project archive's password protection, and intended
    by KNX Association for third-party/IoT tool consumption.
    """

    source_name = "jsonld"

    def import_project(self, path: Path) -> ProjectModel:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError as exc:
            raise ProjectImportError(f"{path}: file not found") from exc
        except json.JSONDecodeError as exc:
            raise ProjectImportError(f"{path}: not valid JSON ({exc})") from exc

        graph = data.get("@graph")
        if not isinstance(graph, list):
            raise ProjectImportError(f"{path}: missing or invalid '@graph'")

        nodes: dict[str, dict[str, Any]] = {
            node["@id"]: node for node in graph if isinstance(node, dict) and "@id" in node
        }

        return self._build_project(nodes)

    def _build_project(self, nodes: dict[str, dict[str, Any]]) -> ProjectModel:
        buildings = [n for n in nodes.values() if "loc:Building" in _node_types(n)]
        spaces = {n["@id"]: n for n in nodes.values() if "loc:Space" in _node_types(n)}
        floors = {n["@id"]: n for n in nodes.values() if "loc:Floor" in _node_types(n)}
        room_nodes = [n for n in nodes.values() if "loc:Room" in _node_types(n)]
        device_nodes = [n for n in nodes.values() if "core:Device" in _node_types(n)]
        channel_nodes = {n["@id"]: n for n in nodes.values() if "knx:Channel" in _node_types(n)}
        datapoint_nodes = [n for n in nodes.values() if "core:Datapoint" in _node_types(n)]
        function_point_nodes = [n for n in nodes.values() if "knx:FunctionPoint" in _node_types(n)]

        default_name = "Unknown Project"
        project_name = buildings[0].get("dct:title", default_name) if buildings else default_name

        floor_to_space = {
            floor_id: space["@id"]
            for space in spaces.values()
            for floor_id in _ref_ids(space.get("loc:hasFloor"))
        }
        room_to_floor = {
            room_id: floor["@id"]
            for floor in floors.values()
            for room_id in _ref_ids(floor.get("loc:hasRoom"))
        }

        rooms = tuple(
            self._build_room(n, room_to_floor, floor_to_space, floors, spaces) for n in room_nodes
        )

        point_to_device: dict[str, str] = {}
        device_to_points: dict[str, list[str]] = {}
        for device in device_nodes:
            for channel_id in _ref_ids(device.get("knx:hasChannel")):
                channel = channel_nodes.get(channel_id)
                if channel is None:
                    continue
                for point_id in _ref_ids(channel.get("core:hasPoint")):
                    point_to_device[point_id] = device["@id"]
                    device_to_points.setdefault(device["@id"], []).append(point_id)

        devices = tuple(self._build_device(n, nodes, device_to_points) for n in device_nodes)
        communication_objects = tuple(
            self._build_communication_object(n, point_to_device) for n in datapoint_nodes
        )
        group_addresses = tuple(self._build_group_address(n) for n in function_point_nodes)

        datapoint_types = tuple(
            sorted(
                {dpt for ga in group_addresses for dpt in (ga.datapoint_type,) if dpt is not None}
                | {
                    dpt
                    for co in communication_objects
                    for dpt in (co.datapoint_type,)
                    if dpt is not None
                }
            )
        )

        return ProjectModel(
            project_name=project_name,
            rooms=rooms,
            devices=devices,
            group_addresses=group_addresses,
            communication_objects=communication_objects,
            datapoint_types=datapoint_types,
        )

    @staticmethod
    def _build_room(
        node: dict[str, Any],
        room_to_floor: dict[str, str],
        floor_to_space: dict[str, str],
        floors: dict[str, dict[str, Any]],
        spaces: dict[str, dict[str, Any]],
    ) -> Room:
        floor_id = room_to_floor.get(node["@id"])
        floor_title = floors[floor_id].get("dct:title") if floor_id in floors else None
        space_id = floor_to_space.get(floor_id) if floor_id else None
        # loc:Space is the individual building/villa (e.g. "Villa A"); loc:Building is
        # the overall site/project (e.g. "Hot Stone") and is exposed as project_name instead.
        building_title = spaces[space_id].get("dct:title") if space_id in spaces else None

        return Room(
            id=node["@id"],
            name=node.get("dct:title", ""),
            floor=floor_title,
            building=building_title,
            device_ids=_ref_ids(node.get("loc:containsEquipment")),
        )

    @staticmethod
    def _build_device(
        node: dict[str, Any],
        nodes: dict[str, dict[str, Any]],
        device_to_points: dict[str, list[str]],
    ) -> Device:
        raw_ia = _literal(node.get("knx:individualAddress"))
        individual_address = _decode_individual_address(int(raw_ia)) if raw_ia is not None else ""

        manufacturer = None
        application_program_id = _ref_id(node.get("core:hosts"))
        if application_program_id is not None:
            application_program = nodes.get(application_program_id, {})
            manufacturer = application_program.get("core:manufacturer")

        product_name = None
        product_id = _ref_id(node.get("core:hasProduct"))
        if product_id is not None:
            product = nodes.get(product_id, {})
            product_name = product.get("dct:title")

        return Device(
            id=node["@id"],
            name=node.get("dct:title", ""),
            individual_address=individual_address,
            serial_number=_literal(node.get("core:serialNumber")),
            manufacturer=manufacturer,
            product_name=product_name,
            communication_object_ids=tuple(device_to_points.get(node["@id"], ())),
        )

    @staticmethod
    def _build_communication_object(
        node: dict[str, Any], point_to_device: dict[str, str]
    ) -> CommunicationObject:
        return CommunicationObject(
            id=node["@id"],
            name=node.get("dct:title", ""),
            device_id=point_to_device.get(node["@id"]),
            flags=node.get("mac:configFlags"),
            datapoint_type=_strip_namespace(_ref_id(node.get("knx:datapointType"))),
            readable=_bool_literal(node.get("core:readable")),
            writable=_bool_literal(node.get("core:writable")),
        )

    @staticmethod
    def _build_group_address(node: dict[str, Any]) -> GroupAddress:
        raw_address = _literal(node.get("knx:groupAddress"))
        return GroupAddress(
            id=node["@id"],
            address=_decode_group_address(int(raw_address)) if raw_address is not None else "",
            name=node.get("dct:title", ""),
            description=node.get("dct:description", ""),
            datapoint_type=_strip_namespace(_ref_id(node.get("knx:datapointType"))),
            security=node.get("knx:securityMode"),
            readable=_bool_literal(node.get("core:readable")),
            writable=_bool_literal(node.get("core:writable")),
            communication_object_ids=_ref_ids(node.get("core:groups")),
        )

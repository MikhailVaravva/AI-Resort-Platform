"""Loads a real .knxproj using xknxproject - the same library the Home
Assistant KNX integration uses to load project files.

No .knxproj/project.xml parsing is implemented here or anywhere else in
this codebase: `XKNXProj(path, password).parse()` does all of it,
including decrypting password-protected archives. This module's only job
is reshaping xknxproject's result into ai_resort_platform.ets's own,
smaller dataclasses (ETSProject/Device/Room/GroupAddress/
CommunicationObject) - not re-deriving anything xknxproject already
computed (e.g. its `topology` and `locations` are used directly, not
recomputed from individual addresses the way earlier, JSON-LD-based code
in this repo had to).
"""

from pathlib import Path
from typing import Any

from xknxproject.exceptions import InvalidPasswordException, XknxProjectException
from xknxproject.models.knxproject import KNXProject
from xknxproject.xknxproj import XKNXProj

from ai_resort_platform.ets.communication_objects import CommunicationObject, Flags
from ai_resort_platform.ets.devices import Device
from ai_resort_platform.ets.group_addresses import GroupAddress
from ai_resort_platform.ets.project import Area, ETSProject, Line, Topology
from ai_resort_platform.ets.rooms import Building, Floor, Room


class EtsProjectError(Exception):
    """Raised when a .knxproj cannot be opened or parsed."""


class EtsProjectPasswordError(EtsProjectError):
    """Raised when the project is password-protected and the given
    password (or no password at all) is wrong."""


def read_project(path: Path, password: str | None = None) -> ETSProject:
    if not path.exists():
        raise EtsProjectError(f"{path}: file not found")

    try:
        data = XKNXProj(path, password=password).parse()
    except InvalidPasswordException as exc:
        raise EtsProjectPasswordError(f"{path}: invalid or missing password") from exc
    except XknxProjectException as exc:
        raise EtsProjectError(f"{path}: {exc}") from exc

    info = data["info"]
    buildings, floors, rooms = _build_locations(data)
    return ETSProject(
        name=info["name"],
        guid=info["guid"],
        tool_version=info["tool_version"],
        devices=_build_devices(data),
        buildings=buildings,
        floors=floors,
        rooms=rooms,
        group_addresses=_build_group_addresses(data),
        communication_objects=_build_communication_objects(data),
        topology=_build_topology(data),
    )


def _build_devices(data: KNXProject) -> tuple[Device, ...]:
    return tuple(
        Device(
            individual_address=address,
            name=device["name"],
            description=device.get("description", ""),
            manufacturer=device.get("manufacturer_name"),
            hardware_name=device.get("hardware_name"),
            order_number=device.get("order_number"),
            communication_object_ids=tuple(device.get("communication_object_ids", ())),
        )
        for address, device in data["devices"].items()
    )


def _build_group_addresses(data: KNXProject) -> tuple[GroupAddress, ...]:
    result = []
    for address, ga in data["group_addresses"].items():
        dpt = ga.get("dpt")
        result.append(
            GroupAddress(
                id=ga["identifier"],
                address=address,
                name=ga["name"],
                description=ga.get("description", ""),
                dpt_main=dpt["main"] if dpt else None,
                dpt_sub=dpt.get("sub") if dpt else None,
                data_secure=ga.get("data_secure", False),
                communication_object_ids=tuple(ga.get("communication_object_ids", ())),
            )
        )
    return tuple(result)


def _build_communication_objects(data: KNXProject) -> tuple[CommunicationObject, ...]:
    result = []
    for co_id, co in data["communication_objects"].items():
        flags = co.get("flags", {})
        result.append(
            CommunicationObject(
                id=co_id,
                name=co["name"],
                number=co["number"],
                device_address=co["device_address"],
                description=co.get("description", ""),
                flags=Flags(
                    read=flags.get("read", False),
                    write=flags.get("write", False),
                    communication=flags.get("communication", False),
                    transmit=flags.get("transmit", False),
                    update=flags.get("update", False),
                    read_on_init=flags.get("read_on_init", False),
                ),
                group_address_links=tuple(co.get("group_address_links", ())),
            )
        )
    return tuple(result)


def _build_locations(
    data: KNXProject,
) -> tuple[tuple[Building, ...], tuple[Floor, ...], tuple[Room, ...]]:
    """Single walk of the location tree (Building -> BuildingPart -> Floor
    -> Room) producing all three collections. `Room.building` is the
    nearest enclosing *BuildingPart* name (e.g. "Villa A"), matching the
    resort's own naming - the `buildings` collection below is for real
    Building-type spaces (e.g. the site, "Hot Stone"), a distinct level.
    """
    buildings: list[Building] = []
    floors: list[Floor] = []
    rooms: list[Room] = []

    def walk(spaces: dict[str, Any], building: str | None, floor: str | None) -> None:
        for space_id, space in spaces.items():
            space_type = space.get("type")
            name = space.get("name", "")
            identifier = space.get("identifier", space_id)
            next_building = name if space_type == "BuildingPart" else building
            next_floor = name if space_type == "Floor" else floor

            if space_type == "Building":
                buildings.append(Building(id=identifier, name=name))
            elif space_type == "Floor":
                floors.append(Floor(id=identifier, name=name, building=building))
            elif space_type == "Room":
                rooms.append(
                    Room(
                        id=identifier,
                        name=name,
                        floor=next_floor,
                        building=next_building,
                        device_ids=tuple(space.get("devices", ())),
                    )
                )

            walk(space.get("spaces", {}), next_building, next_floor)

    walk(data["locations"], None, None)
    return tuple(buildings), tuple(floors), tuple(rooms)


def _build_topology(data: KNXProject) -> Topology:
    areas = []
    for area_address, area in data["topology"].items():
        lines = tuple(
            Line(
                address=int(line_address),
                name=line.get("name", ""),
                device_ids=tuple(line.get("devices", ())),
            )
            for line_address, line in area.get("lines", {}).items()
        )
        areas.append(Area(address=int(area_address), name=area.get("name", ""), lines=lines))
    return Topology(areas=tuple(areas))

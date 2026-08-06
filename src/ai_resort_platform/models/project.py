from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GroupAddress:
    """A KNX group address, independent of which importer produced it."""

    id: str
    address: str
    name: str
    description: str = ""
    datapoint_type: str | None = None
    security: str | None = None
    readable: bool = False
    writable: bool = False
    communication_object_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CommunicationObject:
    """A device-side communication object (a "Datapoint" in KNX terms)."""

    id: str
    name: str
    device_id: str | None = None
    flags: str | None = None
    datapoint_type: str | None = None
    readable: bool = False
    writable: bool = False


@dataclass(frozen=True, slots=True)
class Device:
    """A physical KNX device."""

    id: str
    name: str
    individual_address: str
    serial_number: str | None = None
    manufacturer: str | None = None
    product_name: str | None = None
    communication_object_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Room:
    """A room and the devices installed in it."""

    id: str
    name: str
    floor: str | None = None
    building: str | None = None
    device_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ProjectModel:
    """The internal representation of an ETS project, independent of source format.

    Every importer (JSON-LD semantic export, and later .knxproj) populates
    this same model - nothing downstream of an importer needs to know which
    format the data came from.
    """

    project_name: str
    rooms: tuple[Room, ...] = field(default_factory=tuple)
    devices: tuple[Device, ...] = field(default_factory=tuple)
    group_addresses: tuple[GroupAddress, ...] = field(default_factory=tuple)
    communication_objects: tuple[CommunicationObject, ...] = field(default_factory=tuple)
    datapoint_types: tuple[str, ...] = field(default_factory=tuple)

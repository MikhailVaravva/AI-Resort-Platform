from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ai_resort_platform.ets.communication_objects import CommunicationObject
from ai_resort_platform.ets.devices import Device, Product
from ai_resort_platform.ets.group_addresses import DatapointType, GroupAddress
from ai_resort_platform.ets.rooms import Building, Floor, Room


@dataclass(frozen=True, slots=True)
class Line:
    address: int
    name: str = ""
    device_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Area:
    address: int
    name: str = ""
    lines: tuple[Line, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Topology:
    areas: tuple[Area, ...] = field(default_factory=tuple)

    @property
    def lines(self) -> tuple[Line, ...]:
        """Every Line across every Area, flattened for convenience."""
        return tuple(line for area in self.areas for line in area.lines)


@dataclass(frozen=True, slots=True)
class ETSProject:
    """The single, simple entry point every other module uses to read an ETS project.

    Backed by `xknxproject` (the library the Home Assistant KNX
    integration itself uses to load `.knxproj` files) - see
    `ets/reader.py`. No custom `.knxproj`/`project.xml` parsing exists in
    this codebase; this class only reshapes what xknxproject already
    parsed into this project's own dataclasses, plus a handful of derived,
    deduplicated convenience views (`datapoint_types`, `manufacturers`,
    `products`) over data that's already there - see their docstrings.
    """

    name: str
    guid: str
    tool_version: str
    devices: tuple[Device, ...] = field(default_factory=tuple)
    buildings: tuple[Building, ...] = field(default_factory=tuple)
    floors: tuple[Floor, ...] = field(default_factory=tuple)
    rooms: tuple[Room, ...] = field(default_factory=tuple)
    group_addresses: tuple[GroupAddress, ...] = field(default_factory=tuple)
    communication_objects: tuple[CommunicationObject, ...] = field(default_factory=tuple)
    topology: Topology = field(default_factory=Topology)

    @property
    def datapoint_types(self) -> tuple[DatapointType, ...]:
        """Every distinct DPT (main, sub) actually used by a group address."""
        seen: dict[tuple[int, int | None], DatapointType] = {}
        for ga in self.group_addresses:
            if ga.dpt_main is None:
                continue
            key = (ga.dpt_main, ga.dpt_sub)
            seen.setdefault(key, DatapointType(main=ga.dpt_main, sub=ga.dpt_sub))
        return tuple(
            seen[key] for key in sorted(seen, key=lambda k: (k[0], -1 if k[1] is None else k[1]))
        )

    @property
    def manufacturers(self) -> tuple[str, ...]:
        """Every distinct manufacturer name actually used by a device."""
        return tuple(sorted({d.manufacturer for d in self.devices if d.manufacturer}))

    @property
    def products(self) -> tuple[Product, ...]:
        """Every distinct product (manufacturer + hardware + order number)
        actually used by a device."""
        seen: dict[tuple[str | None, str | None, str | None], Product] = {}
        for device in self.devices:
            key = (device.manufacturer, device.hardware_name, device.order_number)
            seen.setdefault(
                key,
                Product(
                    manufacturer=device.manufacturer,
                    hardware_name=device.hardware_name,
                    order_number=device.order_number,
                ),
            )
        return tuple(
            seen[key] for key in sorted(seen, key=lambda k: (k[0] or "", k[1] or "", k[2] or ""))
        )

    def device(self, identifier: str) -> Device:
        """Look up a device by individual address or, failing that, by name."""
        for device in self.devices:
            if device.individual_address == identifier:
                return device
        for device in self.devices:
            if device.name == identifier:
                return device
        raise KeyError(f"no device matching {identifier!r}")

    def room(self, name: str) -> Room:
        for room in self.rooms:
            if room.name == name:
                return room
        raise KeyError(f"no room named {name!r}")

    def group_address(self, address: str) -> GroupAddress:
        for ga in self.group_addresses:
            if ga.address == address:
                return ga
        raise KeyError(f"no group address {address!r}")

    @classmethod
    def open(cls, path: str | Path, password: str | None = None) -> ETSProject:
        """Read a real `.knxproj` file. `password` is required for
        password-protected projects (most real ones - see ets/reader.py).
        """
        from ai_resort_platform.ets.reader import read_project

        return read_project(Path(path), password=password)

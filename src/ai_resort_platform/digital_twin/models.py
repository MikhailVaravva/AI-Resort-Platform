from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Capability:
    """One controllable/observable function of an Entity (e.g. switch, brightness).

    `kind` is the KNX datapoint type of the capability (e.g. "switch",
    "scaling") - the only reliable, non-textual signal available to tell two
    capabilities of the same Entity apart.
    """

    kind: str
    command_group_address: str | None = None
    status_group_address: str | None = None


@dataclass(frozen=True, slots=True)
class Entity:
    """A logical controllable/observable thing (e.g. one light circuit, one cover).

    Built from group addresses grouped by name (see digital_twin/builder.py
    for the exact heuristic) - this is a best-effort grouping, not something
    ETS hands us directly, since the source project has no explicit
    "entity" concept of its own.
    """

    id: str
    name: str
    capabilities: tuple[Capability, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Scene:
    """A KNX scene: a control point that recalls/stores a preset group of states.

    Detected heuristically from group address naming ("Scene N") and the
    "sceneControl" datapoint type - ETS parameter data, which would give an
    authoritative list of what a scene actually sets, is not available from
    the semantic export (see readers/jsonld_reader.py).
    """

    id: str
    name: str
    number: int | None = None
    control_group_address: str | None = None
    status_group_address: str | None = None


@dataclass(frozen=True, slots=True)
class Device:
    """A physical KNX device, as represented in the digital twin."""

    id: str
    name: str
    individual_address: str
    manufacturer: str | None = None
    product_name: str | None = None
    serial_number: str | None = None


@dataclass(frozen=True, slots=True)
class Room:
    """A room within a villa.

    Only populated when the source project has location data finer than
    "the whole villa" - the current reference project does not (every
    device in it belongs directly to the villa), so this stays empty until
    a source with room-level device placement is available.
    """

    id: str
    name: str
    devices: tuple[Device, ...] = field(default_factory=tuple)
    entities: tuple[Entity, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Villa:
    """One deployed villa: a physical unit with its own devices and entities."""

    id: str
    name: str
    villa_type: str | None = None
    rooms: tuple[Room, ...] = field(default_factory=tuple)
    devices: tuple[Device, ...] = field(default_factory=tuple)
    entities: tuple[Entity, ...] = field(default_factory=tuple)
    scenes: tuple[Scene, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Resort:
    """The whole resort: every villa built from a project source."""

    name: str
    villas: tuple[Villa, ...] = field(default_factory=tuple)

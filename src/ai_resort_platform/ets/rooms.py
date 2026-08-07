from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Building:
    """A building (the top level of the location tree, e.g. the resort site)."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Floor:
    """A floor within a building part."""

    id: str
    name: str
    building: str | None = None


@dataclass(frozen=True, slots=True)
class Room:
    """A room, read from a real .knxproj's location tree (Building ->
    BuildingPart -> Floor -> Room). `floor`/`building` are the names of the
    enclosing Floor/BuildingPart, if any - a Room isn't required to be
    nested under both.
    """

    id: str
    name: str
    floor: str | None = None
    building: str | None = None
    device_ids: tuple[str, ...] = field(default_factory=tuple)

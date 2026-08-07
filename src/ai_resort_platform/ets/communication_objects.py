from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Flags:
    read: bool = False
    write: bool = False
    communication: bool = False
    transmit: bool = False
    update: bool = False
    read_on_init: bool = False


@dataclass(frozen=True, slots=True)
class CommunicationObject:
    """A device-side communication object, as read directly from a real .knxproj."""

    id: str
    name: str
    number: int
    device_address: str
    description: str = ""
    flags: Flags = field(default_factory=Flags)
    group_address_links: tuple[str, ...] = field(default_factory=tuple)

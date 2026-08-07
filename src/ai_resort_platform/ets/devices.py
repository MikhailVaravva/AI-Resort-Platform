from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Product:
    """A device's product identity (manufacturer + hardware + order number).

    Not a separate catalog from xknxproject (it only exposes these three
    fields per Device, no standalone product/manufacturer list) - this is
    the distinct set of products actually used by devices in the project,
    see ETSProject.products / ETSProject.manufacturers.
    """

    manufacturer: str | None = None
    hardware_name: str | None = None
    order_number: str | None = None


@dataclass(frozen=True, slots=True)
class Device:
    """A physical KNX device, as read directly from a real .knxproj.

    `individual_address` doubles as the device's natural identifier - a
    real .knxproj has exactly one device per individual address, so there
    is no separate internal id to carry alongside it.
    """

    individual_address: str
    name: str
    description: str = ""
    manufacturer: str | None = None
    hardware_name: str | None = None
    order_number: str | None = None
    communication_object_ids: tuple[str, ...] = field(default_factory=tuple)

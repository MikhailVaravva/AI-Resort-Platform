from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DatapointType:
    """A KNX datapoint type (e.g. main=1, sub=1 -> DPT 1.001, "switch").

    Not a catalog entry from xknxproject (it doesn't expose DPT names or
    descriptions, only the main/sub numbers already on GroupAddress) - this
    is the distinct set of main/sub pairs actually used in the project, see
    ETSProject.datapoint_types.
    """

    main: int
    sub: int | None = None


@dataclass(frozen=True, slots=True)
class GroupAddress:
    """A KNX group address, as read directly from a real .knxproj."""

    id: str
    address: str
    name: str
    description: str = ""
    dpt_main: int | None = None
    dpt_sub: int | None = None
    data_secure: bool = False
    communication_object_ids: tuple[str, ...] = field(default_factory=tuple)

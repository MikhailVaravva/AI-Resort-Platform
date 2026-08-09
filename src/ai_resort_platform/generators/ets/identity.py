"""The first concrete IdentityStrategy - stage 2 of the Serialization pipeline.

Like ModelProjectDiffer, this stage only ever reads a ProjectModel, so it
is not blocked on the schema questions in
docs/ets-writer-architecture.md section 18 and is equally correct under
either implementation strategy in section 19.

What it mints, and what it does not (section 6): internal *object ids* -
the value that identifies which XML element is which - never bus
addresses. Individual and group addresses are Clone Engine's
AddressAllocator (Step 5). A cloned device needs both, from these two
independently pluggable strategies.

Ids are derived from the base project rather than invented. The observed
id space of the reference project is a per-kind prefix and an integer:

    prj:BP-1    building part (room)
    prj:DI-50   device instance
    prj:GA-266  group address

so minting means "same prefix the base project already uses for this kind,
next free integer". This matters because of section 18's risk 2: whether
these ids are equal to the internal project.xml `Id` values or merely
resemble them is unconfirmed. Deriving the shape from whatever the Reader
captured keeps a minted id consistent with its project under either
answer, where hardcoding a format would bake in the guess.

Section 14 requires a minted id to be unique against the full target id
space *including other CREATEs in the same changeset*. A strategy that
recomputed the maximum from `base_project` on every call would hand out
the same id twice for two new devices, so this one remembers what it has
already issued.
"""

import re
from dataclasses import dataclass, field

from ai_resort_platform.generators.ets.writer import IdentityStrategy
from ai_resort_platform.models.project import ProjectModel

ROOM = "room"
DEVICE = "device"
GROUP_ADDRESS = "group_address"

# Used only when the base project contains no object of that kind at all
# and there is therefore nothing to observe. Taken from the reference
# project's own ids, not from ETS documentation - see the module docstring.
_FALLBACK_PREFIXES = {
    ROOM: "prj:BP-",
    DEVICE: "prj:DI-",
    GROUP_ADDRESS: "prj:GA-",
}

_SUFFIXED = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)$")


class UnknownObjectKindError(ValueError):
    """Raised for an object kind this strategy cannot mint ids for.

    Deliberately an error rather than a generic fallback id: a kind we
    cannot observe in ProjectModel (a scene, today) would get an id in a
    shape nothing has verified, which section 14's uniqueness check could
    not meaningfully test.
    """


def _ids_of_kind(project: ProjectModel, object_kind: str) -> tuple[str, ...]:
    match object_kind:
        case "room":
            return tuple(room.id for room in project.rooms)
        case "device":
            return tuple(device.id for device in project.devices)
        case "group_address":
            return tuple(ga.id for ga in project.group_addresses)
        case _:
            raise UnknownObjectKindError(
                f"cannot mint an id for object kind {object_kind!r}; "
                f"known kinds are {sorted(_FALLBACK_PREFIXES)}"
            )


def _all_ids(project: ProjectModel) -> set[str]:
    """Every id in the project, across kinds.

    Section 14 asks for uniqueness within the target project, not merely
    within the kind being minted, so the check spans communication objects
    too even though they are never minted (section 9).
    """
    return {
        *(room.id for room in project.rooms),
        *(device.id for device in project.devices),
        *(ga.id for ga in project.group_addresses),
        *(co.id for co in project.communication_objects),
    }


def _prefix_and_next_number(ids: tuple[str, ...], fallback_prefix: str) -> tuple[str, int]:
    """The prefix this kind already uses, and one past its highest number.

    Ids that do not end in digits are ignored for numbering but still
    participate in the uniqueness check performed by the caller. When
    several prefixes are in use the most common one wins, so a single
    oddly-shaped legacy id cannot redirect every future mint.
    """
    counts: dict[str, int] = {}
    highest: dict[str, int] = {}
    for value in ids:
        matched = _SUFFIXED.match(value)
        if matched is None:
            continue
        prefix = matched["prefix"]
        number = int(matched["number"])
        counts[prefix] = counts.get(prefix, 0) + 1
        highest[prefix] = max(highest.get(prefix, 0), number)

    if not counts:
        return fallback_prefix, 1

    prefix = max(counts, key=lambda candidate: (counts[candidate], candidate))
    return prefix, highest[prefix] + 1


@dataclass(eq=False)
class SequentialIdentityStrategy(IdentityStrategy):
    """Mints "<observed prefix><next free integer>" per object kind.

    Stateful on purpose: `issued` accumulates every id handed out, so a
    changeset that creates several objects of one kind gets distinct ids
    even though `mint_id` re-receives the same unmodified `base_project`
    each time (section 14).

    Not frozen and compared by identity, because two strategies that have
    issued different ids are not interchangeable.
    """

    issued: set[str] = field(default_factory=set)

    def mint_id(self, object_kind: str, base_project: ProjectModel) -> str:
        existing = _ids_of_kind(base_project, object_kind)
        taken = _all_ids(base_project) | self.issued
        prefix, number = _prefix_and_next_number(existing, _FALLBACK_PREFIXES[object_kind])

        candidate = f"{prefix}{number}"
        while candidate in taken:
            number += 1
            candidate = f"{prefix}{number}"

        self.issued.add(candidate)
        return candidate

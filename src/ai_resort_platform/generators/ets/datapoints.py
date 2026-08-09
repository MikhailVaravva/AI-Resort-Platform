"""Resolves a ProjectModel datapoint type to a knx_master.xml DPT id.

Closes the gap section 10 of docs/ets-writer-architecture.md left open:
GroupAddress.datapoint_type carries the Semantic Export's short name
("switch"), while a .knxproj GroupAddress element carries a master-data id
("DPST-1-1"), and nothing in this codebase mapped between them.

The table is *derived from the project being edited*, never hardcoded.
Every .knxproj ships the KNX Association's knx_master.xml inside it, and
each DatapointSubtype there carries the Name the short form is built from:

    <DatapointSubtype Id="DPST-1-1"   Name="DPT_Switch"        Text="switch"/>
    <DatapointSubtype Id="DPST-9-1"   Name="DPT_Value_Temp"    .../>
    <DatapointSubtype Id="DPST-16-1"  Name="DPT_String_8859_1" .../>

Dropping the "DPT_" prefix and lower-camel-casing the remaining
underscore-separated words reproduces the export's short name exactly:
switch, valueTemp, string88591. Note that `Text` is *not* the source -
DPST-5-1's Text is "percentage (0..100%)" while the export calls it
"scaling", which is `Name` (DPT_Scaling) put through the same rule.

Deriving beats hardcoding for the same reason section 6's ids are observed
rather than invented: the mapping then stays correct for a DPT this
project happens not to use, and for whatever master data a different ETS
version ships, instead of freezing today's subset.

A major-only type has no subtype to name, and the export writes it as
`major.<n>.x` (e.g. `major.5.x` for the 8-bit unsigned family), which maps
to the `DPT-<n>` id rather than a `DPST-` one.
"""

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

KNX_MASTER_ENTRY = "knx_master.xml"

_MAJOR_ONLY = re.compile(r"^major\.(?P<number>\d+)\.x$")


class UnknownDatapointTypeError(KeyError):
    """Raised for a datapoint type with no id in this project's master data.

    Section 14 requires every GroupAddress.datapoint_type to resolve to a
    DPT id actually present in knx_master.xml before a file is touched, so
    an unresolvable type has to stop the pipeline rather than serialize to
    something plausible-looking.
    """


def _short_name(master_name: str) -> str:
    """ "DPT_Value_1_Ucount" -> "value1Ucount"."""
    words = master_name.removeprefix("DPT_").split("_")
    if not words or not words[0]:
        return ""
    first, *rest = words
    tail = "".join(word[:1].upper() + word[1:] if word[:1].isalpha() else word for word in rest)
    return first[:1].lower() + first[1:] + tail


@dataclass(frozen=True, slots=True)
class DatapointTypeTable:
    """Short datapoint-type names to DPT ids, for one project's master data."""

    by_short_name: dict[str, str]
    known_ids: frozenset[str]

    def resolve(self, datapoint_type: str) -> str:
        """The DPT id for a ProjectModel datapoint type.

        Raises UnknownDatapointTypeError rather than returning a guess -
        see the class this module raises.
        """
        major_only = _MAJOR_ONLY.match(datapoint_type)
        if major_only is not None:
            candidate = f"DPT-{major_only['number']}"
            if candidate in self.known_ids:
                return candidate
            raise UnknownDatapointTypeError(
                f"{datapoint_type!r} maps to {candidate!r}, which this project's "
                f"{KNX_MASTER_ENTRY} does not define"
            )

        try:
            return self.by_short_name[datapoint_type]
        except KeyError:
            raise UnknownDatapointTypeError(
                f"{datapoint_type!r} has no DatapointSubtype in this project's "
                f"{KNX_MASTER_ENTRY}"
            ) from None


def load_datapoint_types(knx_master: bytes) -> DatapointTypeTable:
    """Build the table from the bytes of a knx_master.xml."""
    root = ElementTree.fromstring(knx_master)
    by_short_name: dict[str, str] = {}
    known_ids: set[str] = set()

    for element in root.iter():
        identifier = element.attrib.get("Id")
        if identifier is None:
            continue
        tag = element.tag.rpartition("}")[2]
        if tag == "DatapointType":
            known_ids.add(identifier)
        elif tag == "DatapointSubtype":
            known_ids.add(identifier)
            name = element.attrib.get("Name")
            if name:
                by_short_name[_short_name(name)] = identifier

    return DatapointTypeTable(by_short_name=by_short_name, known_ids=frozenset(known_ids))


def load_datapoint_types_from_knxproj(path: Path) -> DatapointTypeTable:
    """Build the table from a .knxproj.

    knx_master.xml sits in the outer archive and is never encrypted, so
    this needs no project password - unlike the project data itself.
    """
    with zipfile.ZipFile(path) as archive:
        return load_datapoint_types(archive.read(KNX_MASTER_ENTRY))

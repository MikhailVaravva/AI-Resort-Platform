"""Turns a ProjectChangeSet into the XML a .knxproj actually contains.

Stage 3 of the Serialization pipeline (docs/ets-writer-architecture.md
section 4), and the first stage that has to know the file format. It was
blocked until the reference project was decrypted; section 18.1 records
what that measurement found, and this module encodes it.

Scope is group addresses. That is where the Clone Engine's work lands,
and it is the object whose element shape is fully measured: every one of
the 74 group addresses in the installation's project carries exactly Id,
Address, Name, Description, DatapointType and Puid, with Key on the 25
that are Data Secure. Devices and rooms are deliberately not serialized
here - a device's element also carries download state and a manufacturer
product reference, and section 18.2 lists both as open.

This produces fragments; it does not touch a file. Writing them into a
real archive is EtsWriter's job and stays unimplemented, because the two
questions that decide it (does a patched 0.xml survive the archive's
signature, and what has to happen to a device's download state) can only
be answered by experiment against ETS itself.
"""

import re
from dataclasses import dataclass
from xml.sax.saxutils import quoteattr

from ai_resort_platform.generators.ets.datapoints import DatapointTypeTable
from ai_resort_platform.generators.ets.models import (
    ChangeKind,
    ObjectChange,
    ProjectChangeSet,
    SerializedProject,
)
from ai_resort_platform.generators.ets.writer import EtsSerializer
from ai_resort_platform.models.project import ProjectModel

GROUP_ADDRESS_KIND = "group_address"

# "prj:GA-266" in a Semantic Export is "P-1A1D-0_GA-266" in the file:
# same numeric suffix, the export's namespace in place of the project's
# own installation prefix. Verified against every group address, device
# and room of the reference project - see section 18.1.
_EXPORT_ID_PREFIX = "prj:"

# The three-level group address ETS stores as a single integer:
# main << 11 | middle << 8 | sub. Confirmed against the file (2304 is
# 1/1/0) and already the encoding JsonLdImporter decodes on the way in.
_THREE_LEVEL = re.compile(r"^(?P<main>\d+)/(?P<middle>\d+)/(?P<sub>\d+)$")

# Model field -> the attribute it is on a GroupAddress element. The
# element has six attributes in the measured project (Id, Address, Name,
# Description, DatapointType, Puid) plus Key on the secure ones; these
# four are the ones a change can set. Id is the identity, not a change;
# Puid and Key are ETS's own and never authored here.
#
# Anything else in an ObjectChange is either a different element's
# business or not representable, and is refused rather than dropped: a
# serializer that silently ignores a requested change is worse than one
# that cannot make it.
_GROUP_ADDRESS_ATTRIBUTES = {
    "address": "Address",
    "name": "Name",
    "description": "Description",
    "datapoint_type": "DatapointType",
}

# `communication_object_ids` is a real change, but it belongs to the
# device side: the link lives in a `Links` attribute on
# ComObjectInstanceRef, not on the group address (section 9). Named here
# so the error can say so instead of "unknown field".
_ELSEWHERE = {
    "communication_object_ids": "ComObjectInstanceRef/@Links (section 9)",
    "readable": "the communication object's Read flag",
    "writable": "the communication object's Write flag",
    "security": "GroupAddress/@Key, which is a key rather than a mode",
}


class SerializationError(ValueError):
    """Raised for a change this serializer cannot express in XML."""


def encode_group_address(address: str) -> int:
    """ "1/1/0" -> 2304."""
    matched = _THREE_LEVEL.match(address)
    if matched is None:
        raise SerializationError(f"{address!r} is not a three-level group address")
    main, middle, sub = (int(matched[part]) for part in ("main", "middle", "sub"))
    if main > 31 or middle > 7 or sub > 255:
        raise SerializationError(f"{address!r} is out of range for a three-level address")
    return (main << 11) | (middle << 8) | sub


@dataclass(frozen=True, slots=True)
class XmlEtsSerializer(EtsSerializer):
    """Emits ETS-shaped XML fragments for group address changes.

    `id_prefix` is the project's own installation prefix, e.g.
    "P-1A1D-0_". It is a property of the base archive rather than of any
    ProjectModel, so it is supplied here for the same reason
    ProjectChangeSet carries the base project's GUID.

    `datapoint_types` resolves the model's short DPT name to the id the
    file stores - see generators/ets/datapoints.py.
    """

    id_prefix: str
    datapoint_types: DatapointTypeTable

    def serialize(
        self, change_set: ProjectChangeSet, base_project: ProjectModel
    ) -> SerializedProject:
        fragments: dict[str, str] = {}
        for change in change_set.changes:
            if change.object_kind != GROUP_ADDRESS_KIND:
                raise SerializationError(
                    f"{change.object_kind!r} is not serialized yet; only "
                    f"{GROUP_ADDRESS_KIND!r} is - see this module's docstring"
                )
            if change.change_kind is ChangeKind.DELETE:
                # Nothing to emit: the Update pipeline removes the element
                # the change names, and there is no replacement content.
                continue
            fragments[change.object_id] = self._group_address(change)
        return SerializedProject(change_set=change_set, xml_fragments=fragments)

    def internal_id(self, object_id: str) -> str:
        """The id the file uses for an object the model calls `object_id`."""
        if object_id.startswith(_EXPORT_ID_PREFIX):
            return f"{self.id_prefix}{object_id.removeprefix(_EXPORT_ID_PREFIX)}"
        if object_id.startswith(self.id_prefix):
            return object_id
        raise SerializationError(
            f"{object_id!r} is neither an export id ({_EXPORT_ID_PREFIX}...) nor "
            f"one of this project's own ({self.id_prefix}...)"
        )

    def _group_address(self, change: ObjectChange) -> str:
        attributes = {"Id": self.internal_id(change.object_id)}
        for field, value in change.fields.items():
            if field in _ELSEWHERE:
                raise SerializationError(
                    f"{field!r} is not an attribute of GroupAddress; it lives on "
                    f"{_ELSEWHERE[field]}"
                )
            if field not in _GROUP_ADDRESS_ATTRIBUTES:
                raise SerializationError(f"{field!r} has no place on a GroupAddress element")
            attributes[_GROUP_ADDRESS_ATTRIBUTES[field]] = self._value(field, value)

        # Always double quotes, escaping any of its own, because that is
        # what the file uses throughout - quoteattr would otherwise switch
        # to single quotes for a value containing one, which is valid XML
        # but a gratuitous difference from every surrounding element.
        rendered = " ".join(
            f"{key}={quoteattr(value, {chr(34): '&quot;'})}" for key, value in attributes.items()
        )
        return f"<GroupAddress {rendered} />"

    def _value(self, field: str, value: str) -> str:
        if field == "address":
            return str(encode_group_address(value))
        if field == "datapoint_type":
            return self.datapoint_types.resolve(value)
        return value

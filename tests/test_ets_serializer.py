"""The serializer, against the element shape the real project actually has."""

import pytest

from ai_resort_platform.generators.ets.datapoints import load_datapoint_types_from_knxproj
from ai_resort_platform.generators.ets.models import (
    ChangeKind,
    ObjectChange,
    ProjectChangeSet,
)
from ai_resort_platform.generators.ets.serializer import (
    SerializationError,
    XmlEtsSerializer,
    encode_group_address,
)
from ai_resort_platform.models.project import ProjectModel
from tests.test_villa_a1_project import VILLA_A1

PREFIX = "P-1A1D-0_"


@pytest.fixture(scope="module")
def serializer() -> XmlEtsSerializer:
    return XmlEtsSerializer(
        id_prefix=PREFIX, datapoint_types=load_datapoint_types_from_knxproj(VILLA_A1)
    )


def _change(fields, kind=ChangeKind.UPDATE, object_id="prj:GA-266"):
    return ProjectChangeSet(
        base_project_guid="g",
        changes=(
            ObjectChange(
                object_kind="group_address",
                change_kind=kind,
                object_id=object_id,
                fields=fields,
            ),
        ),
    )


def _one(serializer, *args, **kwargs) -> str:
    result = serializer.serialize(_change(*args, **kwargs), ProjectModel(project_name="p"))
    return next(iter(result.xml_fragments.values()))


def test_the_address_is_the_integer_ets_stores():
    """2304 is 1/1/0 in the reference project - the same encoding
    JsonLdImporter decodes on the way in."""
    assert encode_group_address("1/1/0") == 2304
    assert encode_group_address("0/0/1") == 1
    assert encode_group_address("31/7/255") == 65535


def test_an_out_of_range_address_is_refused():
    for bad in ("32/0/0", "0/8/0", "0/0/256", "1/1", "not an address"):
        with pytest.raises(SerializationError):
            encode_group_address(bad)


def test_a_renumber_emits_only_the_attribute_that_changed(serializer):
    """Patch, don't regenerate (section 1): the fragment carries the id
    and the changed attribute, nothing else."""
    fragment = _one(serializer, {"address": "1/2/0"})

    assert fragment == '<GroupAddress Id="P-1A1D-0_GA-266" Address="2560" />'


def test_export_ids_are_translated_to_the_projects_own(serializer):
    """prj:GA-266 is P-1A1D-0_GA-266 in the file - section 18.1."""
    assert serializer.internal_id("prj:GA-266") == "P-1A1D-0_GA-266"
    # Already internal is left alone, so a .knxproj-native reader works too.
    assert serializer.internal_id("P-1A1D-0_GA-266") == "P-1A1D-0_GA-266"


def test_an_id_from_another_project_is_refused(serializer):
    with pytest.raises(SerializationError, match="neither"):
        serializer.internal_id("P-035B-0_GA-266")


def test_the_datapoint_type_is_resolved_to_the_master_data_id(serializer):
    fragment = _one(serializer, {"datapoint_type": "switch"})

    assert 'DatapointType="DPST-1-1"' in fragment


def test_an_unknown_datapoint_type_stops_the_pipeline(serializer):
    from ai_resort_platform.generators.ets.datapoints import UnknownDatapointTypeError

    with pytest.raises(UnknownDatapointTypeError):
        _one(serializer, {"datapoint_type": "notARealType"})


def test_names_are_escaped(serializer):
    fragment = _one(serializer, {"name": 'Bath & "Spa" <1>'})

    assert 'Name="Bath &amp; &quot;Spa&quot; &lt;1&gt;"' in fragment


def test_a_delete_emits_no_fragment(serializer):
    result = serializer.serialize(
        _change({}, kind=ChangeKind.DELETE), ProjectModel(project_name="p")
    )

    assert result.xml_fragments == {}
    # The change itself is still carried, for the Update pipeline to act on.
    assert len(result.change_set.changes) == 1


def test_a_field_that_lives_on_another_element_says_so(serializer):
    """Section 9: the group-address link is a Links attribute on
    ComObjectInstanceRef, not something on the GroupAddress."""
    with pytest.raises(SerializationError, match="ComObjectInstanceRef"):
        _one(serializer, {"communication_object_ids": "co-1"})


def test_an_unrepresentable_field_is_refused_not_dropped(serializer):
    """A serializer that silently ignores a requested change is worse than
    one that cannot make it."""
    with pytest.raises(SerializationError, match="no place"):
        _one(serializer, {"parameter:ramp_time": "5s"})


def test_object_kinds_that_are_not_serialized_yet_are_explicit(serializer):
    change_set = ProjectChangeSet(
        base_project_guid="g",
        changes=(
            ObjectChange(
                object_kind="device", change_kind=ChangeKind.UPDATE, object_id="prj:DI-50"
            ),
        ),
    )

    with pytest.raises(SerializationError, match="not serialized yet"):
        serializer.serialize(change_set, ProjectModel(project_name="p"))


def test_end_to_end_against_the_real_project(serializer):
    """Reader -> differ -> serializer, on the installation's own project.

    The fragment is compared against the element the file really holds for
    that group address, so a mistake in the id prefix, the address
    encoding or the DPT resolution shows up as a mismatch with reality
    rather than with a fixture.
    """
    import xml.etree.ElementTree as ET
    from dataclasses import replace

    from ai_resort_platform.generators.ets.differ import ModelProjectDiffer
    from ai_resort_platform.readers.jsonld_reader import JsonLdImporter
    from tests.test_ets_writer_reference_villa import REFERENCE_GUID, REFERENCE_VILLA

    original = JsonLdImporter().import_project(REFERENCE_VILLA)
    target = original.group_addresses[0]
    renamed = replace(
        original,
        group_addresses=(
            replace(target, name="Renamed", address="1/2/3"),
            *original.group_addresses[1:],
        ),
    )

    change_set = ModelProjectDiffer(base_project_guid=REFERENCE_GUID).diff(original, renamed)
    # The reference project's own prefix, not Villa A1's.
    reference = XmlEtsSerializer(id_prefix="P-035B-0_", datapoint_types=serializer.datapoint_types)
    (fragment,) = reference.serialize(change_set, original).xml_fragments.values()

    assert 'Id="P-035B-0_GA-266"' in fragment
    assert 'Name="Renamed"' in fragment
    assert f'Address="{encode_group_address("1/2/3")}"' in fragment
    # Only what changed: the untouched description and DPT stay out.
    assert "Description" not in fragment
    assert "DatapointType" not in fragment
    # ...and it parses, with the same tag the file uses.
    assert ET.fromstring(fragment).tag == "GroupAddress"


def test_the_fragment_uses_the_same_attributes_the_file_does(serializer):
    """A CREATE names every attribute; each must be one the real element
    actually has, or ETS is being handed a key it does not know."""
    import xml.etree.ElementTree as ET

    from xknxproject.zip.extractor import extract

    with extract(VILLA_A1, "00000000") as contents:
        root = ET.fromstring(contents.open_project_0().read())
    namespace = root.tag.split("}")[0].strip("{")
    real = next(root.iter(f"{{{namespace}}}GroupAddress"))

    fragment = _one(
        serializer,
        {
            "address": "1/1/0",
            "name": "New",
            "description": "d",
            "datapoint_type": "switch",
        },
        kind=ChangeKind.CREATE,
        object_id="prj:GA-900",
    )

    assert set(ET.fromstring(fragment).attrib) <= set(real.attrib)

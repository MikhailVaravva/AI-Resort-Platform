import pytest

from ai_resort_platform.generators.ets.datapoints import (
    DatapointTypeTable,
    UnknownDatapointTypeError,
    load_datapoint_types,
)

MASTER = b"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="http://knx.org/xml/project/23">
  <MasterData>
    <DatapointTypes>
      <DatapointType Id="DPT-1" Number="1" Name="1.xxx" Text="1-bit">
        <DatapointSubtypes>
          <DatapointSubtype Id="DPST-1-1" Number="1" Name="DPT_Switch" Text="switch"/>
          <DatapointSubtype Id="DPST-1-3" Number="3" Name="DPT_Enable" Text="enable"/>
        </DatapointSubtypes>
      </DatapointType>
      <DatapointType Id="DPT-5" Number="5" Name="5.xxx" Text="8-bit unsigned value">
        <DatapointSubtypes>
          <DatapointSubtype Id="DPST-5-1" Number="1" Name="DPT_Scaling"
                            Text="percentage (0..100%)"/>
          <DatapointSubtype Id="DPST-5-10" Number="10" Name="DPT_Value_1_Ucount"/>
        </DatapointSubtypes>
      </DatapointType>
      <DatapointType Id="DPT-16" Number="16" Name="16.xxx" Text="character string">
        <DatapointSubtypes>
          <DatapointSubtype Id="DPST-16-1" Number="1" Name="DPT_String_8859_1"/>
        </DatapointSubtypes>
      </DatapointType>
    </DatapointTypes>
  </MasterData>
</KNX>
"""


@pytest.fixture
def table() -> DatapointTypeTable:
    return load_datapoint_types(MASTER)


def test_a_simple_name_resolves(table: DatapointTypeTable):
    assert table.resolve("switch") == "DPST-1-1"
    assert table.resolve("enable") == "DPST-1-3"


def test_multiword_names_become_lower_camel_case(table: DatapointTypeTable):
    assert table.resolve("value1Ucount") == "DPST-5-10"


def test_numeric_words_pass_through_uncapitalised(table: DatapointTypeTable):
    """DPT_String_8859_1 -> string88591, the shape the export actually emits."""
    assert table.resolve("string88591") == "DPST-16-1"


def test_the_name_attribute_is_the_source_not_the_text_attribute(table: DatapointTypeTable):
    """DPST-5-1 is Name="DPT_Scaling" but Text="percentage (0..100%)"."""
    assert table.resolve("scaling") == "DPST-5-1"
    with pytest.raises(UnknownDatapointTypeError):
        table.resolve("percentage (0..100%)")


def test_a_major_only_type_resolves_to_the_datapoint_type_id(table: DatapointTypeTable):
    assert table.resolve("major.5.x") == "DPT-5"
    assert table.resolve("major.16.x") == "DPT-16"


def test_an_undefined_major_only_type_is_an_error(table: DatapointTypeTable):
    with pytest.raises(UnknownDatapointTypeError, match="DPT-99"):
        table.resolve("major.99.x")


def test_an_unknown_short_name_is_an_error_not_a_guess(table: DatapointTypeTable):
    """Section 14: an unresolvable type must stop the pipeline."""
    with pytest.raises(UnknownDatapointTypeError, match="notADatapointType"):
        table.resolve("notADatapointType")


def test_both_types_and_subtypes_count_as_known_ids(table: DatapointTypeTable):
    assert "DPT-1" in table.known_ids
    assert "DPST-1-1" in table.known_ids

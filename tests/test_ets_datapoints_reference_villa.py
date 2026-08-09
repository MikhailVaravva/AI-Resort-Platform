"""Integration tests: resolve the real villa's datapoint types against the
KNX Association master data shipped inside the real .knxproj.

The expected ids below are not invented: they are what the reference
project's own 0.xml records on each GroupAddress element. Deriving the
same values from knx_master.xml alone is what makes the naming rule in
generators/ets/datapoints.py a fact about KNX master data rather than a
pattern that happened to fit a handful of examples.

No project password is involved. knx_master.xml sits in the outer archive
unencrypted; only the project data itself is protected.
"""

from pathlib import Path

import pytest

from ai_resort_platform.generators.ets.datapoints import (
    DatapointTypeTable,
    load_datapoint_types_from_knxproj,
)
from ai_resort_platform.models.project import ProjectModel
from ai_resort_platform.readers.jsonld_reader import JsonLdImporter

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "examples" / "Reference-Villa"
REFERENCE_KNXPROJ = REFERENCE_DIR / "reference_villa.knxproj"
REFERENCE_VILLA = REFERENCE_DIR / "reference_villa.jsonld"

# Every datapoint type the reference villa's 62 group addresses use, with
# the DPT id its own 0.xml assigns to them.
EXPECTED = {
    "absoluteColourTemperature": "DPST-7-600",
    "date": "DPST-11-1",
    "enable": "DPST-1-3",
    "major.5.x": "DPT-5",
    "openClose": "DPST-1-9",
    "scaling": "DPST-5-1",
    "sceneControl": "DPST-18-1",
    "start": "DPST-1-10",
    "step": "DPST-1-7",
    "string88591": "DPST-16-1",
    "switch": "DPST-1-1",
    "value1Ucount": "DPST-5-10",
    "valueHumidity": "DPST-9-7",
    "valueTemp": "DPST-9-1",
}


@pytest.fixture(scope="module")
def table() -> DatapointTypeTable:
    return load_datapoint_types_from_knxproj(REFERENCE_KNXPROJ)


@pytest.fixture(scope="module")
def project() -> ProjectModel:
    return JsonLdImporter().import_project(REFERENCE_VILLA)


@pytest.mark.parametrize(("short_name", "dpt_id"), sorted(EXPECTED.items()))
def test_short_name_resolves_to_the_id_the_project_records(
    table: DatapointTypeTable, short_name: str, dpt_id: str
):
    assert table.resolve(short_name) == dpt_id


def test_every_group_address_in_the_real_project_resolves(
    table: DatapointTypeTable, project: ProjectModel
):
    """Section 14, on real data: no group address may fail to resolve."""
    unresolved = [
        ga.datapoint_type
        for ga in project.group_addresses
        if ga.datapoint_type is not None and ga.datapoint_type not in EXPECTED
    ]

    assert unresolved == []
    assert {ga.datapoint_type for ga in project.group_addresses} == set(EXPECTED)


def test_the_master_data_covers_far_more_than_this_project_uses(table: DatapointTypeTable):
    """The table is derived, not a hardcoded list of what we happened to see."""
    assert len(table.by_short_name) > 300
    assert set(EXPECTED) <= set(table.by_short_name) | {"major.5.x"}


def test_the_two_types_that_broke_the_generated_home_assistant_yaml_resolve(
    table: DatapointTypeTable,
):
    """`string88591` and `major.5.x` are real DPTs, not corrupt values.

    Both were emitted verbatim into a generated KNX YAML as Home Assistant
    `type:` values, where they are meaningless. They are perfectly valid
    *ETS* datapoint types - the bug was passing an ETS name to Home
    Assistant, so a correct writer needs exactly this resolution step.
    """
    assert table.resolve("string88591") == "DPST-16-1"
    assert table.resolve("major.5.x") == "DPT-5"

"""The resort project: twelve villas, one naming convention.

Committed as reference data rather than as a build input. The deployment
recipe still points at the single-villa project, because build_package
has no per-villa scoping - given this file it would put all twelve
villas' addresses in one package. That gap is real and unclosed; these
tests guard the thing the project is actually useful for today, which is
the naming convention the generator depends on.
"""

import re
from pathlib import Path

import pytest

from ai_resort_platform.ets.project import ETSProject

HOT_STONE = Path(__file__).resolve().parent.parent / "examples" / "Hot-Stone" / "hot_stone.knxproj"
PASSWORD = "12345"

# Villas whose audio group is complete and follows A1. The rest are not
# commissioned yet: their addresses are drafts until an installer
# configures each module's own web interface, which is what decides them.
NORMALISED = ("A1", "A3", "A4")


@pytest.fixture(scope="module")
def project() -> ETSProject:
    return ETSProject.open(HOT_STONE, password=PASSWORD)


def _audio(project: ETSProject, villa: str) -> dict[str, str]:
    """Function name -> address, for one villa's audio group."""
    found = {}
    for ga in project.group_addresses:
        match = re.match(rf"^{villa}\s+Audio\s+(.*)$", ga.name or "")
        if match:
            found[match.group(1)] = ga.address
    return found


def test_the_resort_has_twelve_villas(project: ETSProject):
    assert len(project.rooms) == 12
    assert {r.building for r in project.rooms} == {"Villa A", "Villa B", "Villa C", "Villa D"}


def test_the_normalised_villas_all_match_a1(project: ETSProject):
    """The generator pairs commands with statuses by name, so a villa
    named differently gets no media player at all - which is what the
    other villas looked like before this was fixed."""
    a1 = _audio(project, "A1")
    assert len(a1) == 27

    for villa in NORMALISED[1:]:
        other = _audio(project, villa)
        assert set(other) == set(a1), villa


def test_each_normalised_villa_uses_the_same_sub_addresses(project: ETSProject):
    """Same function, same last number, different middle group per villa."""
    a1 = {fn: addr.rsplit("/", 1)[1] for fn, addr in _audio(project, "A1").items()}

    for villa, middle in (("A3", "1/3"), ("A4", "1/4")):
        for fn, addr in _audio(project, villa).items():
            assert addr == f"{middle}/{a1[fn]}", f"{villa} {fn}"


def test_the_addresses_the_audio_module_documents_are_present(project: ETSProject):
    """The twelve read off the module's own Source Management page, which
    the project did not carry until they were measured and imported."""
    a1 = _audio(project, "A1")

    for fn in (
        "Equalizer",
        "Equalizer status",
        "Source Select",
        "Source Select status",
        "Source Information",
        "Auto Source Selection",
        "Volume Minimum status",
        "Volume Maximum status",
        "Text View",
        "Album",
        "Artist",
        "Playlist name",
    ):
        assert fn in a1, fn


def test_no_villa_keeps_audio_outside_its_own_middle_group(project: ETSProject):
    """A2 once had audio addresses sitting in D2's range."""
    for villa, middle in (("A1", "1/1"), ("A3", "1/3"), ("A4", "1/4")):
        for fn, addr in _audio(project, villa).items():
            assert addr.startswith(f"{middle}/"), f"{villa} {fn} -> {addr}"

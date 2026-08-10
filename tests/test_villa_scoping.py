"""Building one villa out of a resort project.

Without this a package built from the resort file describes all twelve
villas at once, which is why the deployment recipe had to point at a
single-villa export instead.
"""

from pathlib import Path

import pytest

from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.homeassistant.builder import (
    VillaNotFoundError,
    build_package,
    villa_group_addresses,
)

HOT_STONE = Path(__file__).resolve().parent.parent / "examples" / "Hot-Stone" / "hot_stone.knxproj"


@pytest.fixture(scope="module")
def resort() -> ETSProject:
    return ETSProject.open(HOT_STONE, password="12345")


def test_a_villa_gets_only_its_own_line(resort: ETSProject):
    """Villa A1's devices are 1.1.x, so its addresses are 1/1/x."""
    addresses = villa_group_addresses(resort, "Villa A1")

    assert addresses
    assert {ga.address.rsplit("/", 1)[0] for ga in addresses} == {"1/1"}


def test_every_villa_is_a_disjoint_slice(resort: ETSProject):
    """Two villas must never share an address, or a package for one would
    control the other."""
    seen: dict[str, str] = {}
    for room in resort.rooms:
        for ga in villa_group_addresses(resort, room.name):
            assert ga.address not in seen, f"{ga.address}: {seen.get(ga.address)} and {room.name}"
            seen[ga.address] = room.name

    assert len(seen) == 786  # the rest are 1/5-1/7, which belong to no villa


def test_scoping_actually_shrinks_the_package(resort: ETSProject):
    whole = build_package(resort)
    one = build_package(resort, villa="Villa A1")

    assert len(one.entities) < len(whole.entities)
    assert one.villa_name == "Villa A1"


def test_each_villa_carries_its_own_name(resort: ETSProject):
    """Unscoped, villa_name came from rooms[0] - whichever room happened to
    be first, which for this project is A2."""
    for room in resort.rooms:
        assert build_package(resort, villa=room.name).villa_name == room.name


def test_the_normalised_villas_all_get_a_media_player(resort: ETSProject):
    """A1, A3 and A4 follow one naming convention, so one generator builds
    all three without a special case."""
    for villa in ("Villa A1", "Villa A3", "Villa A4"):
        package = build_package(resort, villa=villa)
        assert package.media_players, villa
        assert len(package.selects) == 2, villa


def test_an_unknown_villa_says_what_the_project_has(resort: ETSProject):
    with pytest.raises(VillaNotFoundError, match="Villa A1"):
        villa_group_addresses(resort, "Villa Z9")


def test_a_single_villa_export_still_builds_without_the_argument():
    """The A1-only project has one room, so nothing has to be selected."""
    villa_a1 = Path(__file__).resolve().parent.parent / "examples" / "Villa-A1" / "villa_a1.knxproj"
    project = ETSProject.open(villa_a1, password="00000000")

    package = build_package(project)

    assert package.villa_name == "Villa A1"
    assert package.media_players


def test_every_sensor_type_is_one_the_knx_platform_accepts(resort: ETSProject):
    """The KNX sensor platform takes numeric DPTs only, and rejects the
    whole integration over one it does not know - an invalid `type` is not
    ignored, it fails setup for every KNX entity in the package.

    Building the resort project once produced six such types at once
    ('232.600', '251.600', '3.7', '17.1', '1.1' and '-1'), two of them in
    villa A1, from a numeric fallback that looked reasonable and was not
    valid config.

    The accepted set is checked against a running Home Assistant, not
    guessed; this list is that answer written down.
    """
    accepted = {
        "1byte_unsigned",
        "color_temperature",
        "humidity",
        "latin_1",
        "percent",
        "pulse",
        "scene_number",
        "temperature",
    }

    for room in resort.rooms:
        for entity in build_package(resort, villa=room.name).entities:
            declared = entity.config.get("type")
            if declared is not None:
                assert declared in accepted, f"{room.name} / {entity.name}: {declared!r}"


def test_black_out_is_one_control_over_every_dmx_fixture(resort: ETSProject):
    """Blacking out the DMX is one thing to a resident, even where the
    project spells it per fixture - A1 has a Black Out for Stone and
    another for Terrace."""
    package = build_package(resort, villa="Villa A1")

    black_outs = [e for e in package.entities if "Black Out" in e.name]
    (control,) = black_outs
    assert control.domain == "switch"
    assert control.name == "DMX Black Out"
    assert control.config["address"] == ["1/1/109", "1/1/110"]


def test_an_address_with_no_datapoint_type_yields_nothing(resort: ETSProject):
    """A2 and C2 each have a "DMX Active Black Out", and neither carries a
    DPT in the project - 1/2/114 and 3/2/89 are both None.

    Without one there is nothing to classify the address as, so no entity
    is built. That is a gap in the ETS project rather than in the
    generator, and inventing a type to paper over it would put a control
    in the house whose behaviour nobody has established.

    Worth separating the two cases: A2 is a type A villa and will be
    brought to A1's shape at commissioning, so its missing DPT is an
    oversight. C is a different villa type whose audio module is to be
    configured differently, so nothing about C2 should be made to match
    A1 - the project describes four types on purpose.
    """
    for villa in ("Villa A2", "Villa C2"):
        package = build_package(resort, villa=villa)
        assert [e for e in package.entities if "Black Out" in e.name] == [], villa

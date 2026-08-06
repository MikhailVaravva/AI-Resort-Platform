"""Integration tests: build the digital twin from the real reference project."""

from pathlib import Path

from ai_resort_platform.digital_twin.builder import build_resort
from ai_resort_platform.readers.jsonld_reader import JsonLdImporter

REFERENCE_VILLA = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "Reference-Villa"
    / "reference_villa.jsonld"
)


def _build_reference_resort():
    project = JsonLdImporter().import_project(REFERENCE_VILLA)
    return build_resort(project)


def test_reference_resort_has_one_villa():
    resort = _build_reference_resort()

    assert resort.name == "Hot Stone"
    assert len(resort.villas) == 1

    villa = resort.villas[0]
    assert villa.name == "Villa A1"
    assert villa.villa_type == "Villa A"


def test_reference_villa_has_all_seven_devices():
    resort = _build_reference_resort()
    villa = resort.villas[0]

    assert len(villa.devices) == 7
    assert {d.individual_address for d in villa.devices} == {
        "1.1.1",
        "1.1.2",
        "1.1.3",
        "1.1.4",
        "1.1.5",
        "1.1.6",
        "1.1.7",
    }


def test_reference_villa_g_token_entities_have_distinct_capabilities_per_dpt():
    resort = _build_reference_resort()
    villa = resort.villas[0]
    entities_by_id = {e.id: e for e in villa.entities}

    g1 = entities_by_id[f"{villa.id}:G1"]
    kinds = {c.kind: c for c in g1.capabilities}
    assert set(kinds) == {"switch", "scaling", "absoluteColourTemperature"}
    assert kinds["switch"].command_group_address == "1/1/0"
    assert kinds["switch"].status_group_address == "1/1/1"
    assert kinds["scaling"].command_group_address == "1/1/2"
    assert kinds["scaling"].status_group_address == "1/1/3"


def test_reference_villa_command_and_status_with_mismatched_wording_still_merge():
    """ "DMX Terrace Red value" and "...Red status" don't share exact wording
    (one has "value", the other doesn't) - the builder must still pair them."""
    resort = _build_reference_resort()
    villa = resort.villas[0]
    entities_by_name = {e.name: e for e in villa.entities}

    entity = entities_by_name["DMX Terrace Red"]
    assert len(entity.capabilities) == 1
    capability = entity.capabilities[0]
    assert capability.command_group_address == "1/1/160"
    assert capability.status_group_address == "1/1/161"


def test_reference_villa_stray_comma_before_status_still_merges():
    """Source name is "Audio Play mode, status" (stray comma) for the status
    GA, vs "Audio Play mode" for the command GA."""
    resort = _build_reference_resort()
    villa = resort.villas[0]
    entities_by_name = {e.name: e for e in villa.entities}

    entity = entities_by_name["Audio Play mode"]
    assert len(entity.capabilities) == 1
    capability = entity.capabilities[0]
    assert capability.command_group_address == "1/1/242"
    assert capability.status_group_address == "1/1/243"


def test_reference_villa_known_naming_mismatch_stays_split():
    """Known heuristic limitation: "Audio Absolut volume" (command) and
    "Audio Volume status" share no common wording at all, so they end up as
    two separate single-capability entities rather than one. Documenting
    this as an explicit, visible test rather than silently accepting it."""
    resort = _build_reference_resort()
    villa = resort.villas[0]
    entities_by_name = {e.name: e for e in villa.entities}

    assert entities_by_name["Audio Absolut volume"].capabilities[0].command_group_address == (
        "1/1/211"
    )
    assert entities_by_name["Audio Absolut volume"].capabilities[0].status_group_address is None

    assert entities_by_name["Audio Volume"].capabilities[0].command_group_address is None
    assert entities_by_name["Audio Volume"].capabilities[0].status_group_address == "1/1/212"


def test_reference_villa_entity_and_scene_group_addresses_account_for_every_ga():
    """No group address should be silently dropped between entities and scenes."""
    project = JsonLdImporter().import_project(REFERENCE_VILLA)
    resort = build_resort(project)
    villa = resort.villas[0]

    addresses_in_entities = {
        address
        for entity in villa.entities
        for capability in entity.capabilities
        for address in (capability.command_group_address, capability.status_group_address)
        if address is not None
    }
    addresses_in_scenes = set()
    for scene in villa.scenes:
        if scene.control_group_address is not None:
            addresses_in_scenes.add(scene.control_group_address)
        if scene.status_group_address is not None:
            addresses_in_scenes.add(scene.status_group_address)

    accounted = addresses_in_entities | addresses_in_scenes
    all_addresses = {ga.address for ga in project.group_addresses}

    assert accounted == all_addresses


def test_reference_villa_scenes():
    resort = _build_reference_resort()
    villa = resort.villas[0]

    assert len(villa.scenes) == 7
    numbers = {s.number for s in villa.scenes}
    assert numbers == {None, 1, 2, 3, 4, 5, 6}
    assert all(s.control_group_address == "1/1/150" for s in villa.scenes)

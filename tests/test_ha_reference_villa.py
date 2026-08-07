"""Integration tests: generate the Home Assistant package from the real reference villa."""

import collections
from pathlib import Path

import yaml

from ai_resort_platform.digital_twin.builder import build_resort
from ai_resort_platform.generators.ha_builder import build_dashboard, build_resort_packages
from ai_resort_platform.generators.ha_yaml import (
    dashboard_to_yaml,
    package_to_yaml,
    write_dashboard,
    write_package,
)
from ai_resort_platform.readers.jsonld_reader import JsonLdImporter

REFERENCE_VILLA = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "Reference-Villa"
    / "reference_villa.jsonld"
)


def _build_reference_packages():
    project = JsonLdImporter().import_project(REFERENCE_VILLA)
    resort = build_resort(project)
    return resort, build_resort_packages(resort)


def test_one_package_per_villa():
    resort, packages = _build_reference_packages()

    assert len(packages) == len(resort.villas) == 1
    assert packages[0].villa_id == resort.villas[0].id
    assert packages[0].villa_name == "Villa A1"


def test_reference_villa_domain_distribution():
    _, packages = _build_reference_packages()
    package = packages[0]

    counts = collections.Counter(e.domain for e in package.entities)
    assert counts == {"light": 13, "sensor": 11, "switch": 9, "cover": 1}


def test_reference_villa_curtain_merged_into_one_cover():
    _, packages = _build_reference_packages()
    package = packages[0]

    covers = [e for e in package.entities if e.domain == "cover"]
    assert len(covers) == 1
    assert covers[0].config == {
        "move_long_address": "1/1/30",
        "stop_address": "1/1/31",
        "position_address": "1/1/32",
        "position_state_address": "1/1/33",
    }


def test_reference_villa_no_unique_id_collisions():
    _, packages = _build_reference_packages()
    package = packages[0]

    all_ids = (
        [e.unique_id for e in package.entities]
        + [s.unique_id for s in package.scenes]
        + [s.unique_id for s in package.scripts]
    )
    assert len(all_ids) == len(set(all_ids))


def test_reference_villa_scenes_and_scripts():
    _, packages = _build_reference_packages()
    package = packages[0]

    assert len(package.scenes) == 6
    assert len(package.scripts) == 6
    assert {s.scene_number for s in package.scenes} == {1, 2, 3, 4, 5, 6}


def test_reference_villa_automations_are_empty():
    _, packages = _build_reference_packages()

    assert packages[0].automations == ()


def test_reference_villa_package_yaml_round_trips():
    _, packages = _build_reference_packages()
    package = packages[0]

    data = yaml.safe_load(package_to_yaml(package))

    assert set(data.keys()) == {"light", "sensor", "switch", "cover", "scene", "script"}
    assert len(data["light"]) == 13
    assert len(data["scene"]) == 6
    assert len(data["script"]) == 6


def test_reference_villa_dashboard_covers_every_domain_present():
    _, packages = _build_reference_packages()
    package = packages[0]

    dashboard = build_dashboard(package)
    view = dashboard.views[0]
    card_titles = {c.title for c in view.cards}

    assert card_titles == {"Lights", "Sensors", "Switches", "Covers", "Scenes", "Scripts"}

    total_entities_in_cards = sum(len(c.entities) for c in view.cards)
    assert total_entities_in_cards == len(package.entities) + len(package.scenes) + len(
        package.scripts
    )


def test_reference_villa_writes_one_package_file_and_one_dashboard_file(tmp_path):
    _, packages = _build_reference_packages()
    package = packages[0]
    dashboard = build_dashboard(package)

    package_path = tmp_path / "villa_a1.yaml"
    dashboard_path = tmp_path / "villa_a1_dashboard.yaml"
    write_package(package, package_path)
    write_dashboard(dashboard, dashboard_path)

    assert package_path.exists()
    assert dashboard_path.exists()
    assert yaml.safe_load(package_path.read_text(encoding="utf-8"))
    assert yaml.safe_load(dashboard_path.read_text(encoding="utf-8"))


def test_reference_villa_package_is_stable_across_rebuilds():
    """Regenerating from the same input must not change any entity_id."""
    project = JsonLdImporter().import_project(REFERENCE_VILLA)
    resort = build_resort(project)

    first = build_resort_packages(resort)[0]
    second = build_resort_packages(resort)[0]

    assert [e.unique_id for e in first.entities] == [e.unique_id for e in second.entities]
    assert first == second


def test_reference_villa_dashboard_yaml_round_trips():
    _, packages = _build_reference_packages()
    dashboard = build_dashboard(packages[0])

    data = yaml.safe_load(dashboard_to_yaml(dashboard))

    assert data["title"] == "Villa A1"
    assert len(data["views"]) == 1

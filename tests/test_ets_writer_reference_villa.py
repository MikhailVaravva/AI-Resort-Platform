"""Integration tests: diff and mint ids against the real reference project.

The unit tests build small hand-made ProjectModels; these run the same two
stages over all 350 nodes the semantic export actually contains, which is
what makes the section 4 guarantee ("no differences means no change")
meaningful rather than a property of a two-object fixture.
"""

from dataclasses import replace
from pathlib import Path

from ai_resort_platform.generators.ets.differ import ModelProjectDiffer
from ai_resort_platform.generators.ets.identity import SequentialIdentityStrategy
from ai_resort_platform.generators.ets.models import ChangeKind
from ai_resort_platform.models.project import ProjectModel
from ai_resort_platform.readers.jsonld_reader import JsonLdImporter

REFERENCE_VILLA = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "Reference-Villa"
    / "reference_villa.jsonld"
)
REFERENCE_GUID = "31f9b2d9-7433-48d6-b127-1fea6c0c66b4"


def _reference_project() -> ProjectModel:
    return JsonLdImporter().import_project(REFERENCE_VILLA)


def test_the_real_project_does_not_differ_from_itself():
    """Section 4, on real data: a re-import must produce an empty changeset.

    Any field the differ mishandles - a mutable default, an unstable
    ordering, a value that does not compare equal to itself - shows up here
    as a spurious change the Writer would then apply to a real .knxproj.
    """
    project = _reference_project()

    change_set = ModelProjectDiffer(base_project_guid=REFERENCE_GUID).diff(project, project)

    assert change_set.changes == ()


def test_two_separate_imports_also_do_not_differ():
    change_set = ModelProjectDiffer(base_project_guid=REFERENCE_GUID).diff(
        _reference_project(), _reference_project()
    )

    assert change_set.changes == ()


def test_renaming_one_group_address_touches_only_that_object():
    project = _reference_project()
    target = project.group_addresses[0]
    renamed = replace(
        project,
        group_addresses=(replace(target, name="Renamed"), *project.group_addresses[1:]),
    )

    (change,) = ModelProjectDiffer(base_project_guid=REFERENCE_GUID).diff(project, renamed).changes

    assert change.object_kind == "group_address"
    assert change.change_kind is ChangeKind.UPDATE
    assert change.object_id == target.id
    # The other 61 group addresses, 7 devices and the room are all absent
    # from the changeset, and only the renamed field is carried.
    assert change.fields == {"name": "Renamed"}


def test_minted_ids_follow_the_real_projects_own_prefixes():
    project = _reference_project()
    strategy = SequentialIdentityStrategy()

    minted = {kind: strategy.mint_id(kind, project) for kind in ("room", "device", "group_address")}

    assert minted["room"].startswith("prj:BP-")
    assert minted["device"].startswith("prj:DI-")
    assert minted["group_address"].startswith("prj:GA-")


def test_minted_ids_collide_with_nothing_in_the_real_project():
    """Section 14: unique across the whole target id space."""
    project = _reference_project()
    strategy = SequentialIdentityStrategy()
    taken = {
        *(room.id for room in project.rooms),
        *(device.id for device in project.devices),
        *(ga.id for ga in project.group_addresses),
        *(co.id for co in project.communication_objects),
    }

    minted = [
        strategy.mint_id(kind, project)
        for kind in ("room", "device", "group_address")
        for _ in range(5)
    ]

    assert len(set(minted)) == len(minted)
    assert taken.isdisjoint(minted)

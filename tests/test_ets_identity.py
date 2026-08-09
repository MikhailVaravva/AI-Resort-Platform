import pytest

from ai_resort_platform.generators.ets.identity import (
    SequentialIdentityStrategy,
    UnknownObjectKindError,
)
from ai_resort_platform.models.project import (
    CommunicationObject,
    Device,
    GroupAddress,
    ProjectModel,
    Room,
)


def project(**kwargs: object) -> ProjectModel:
    return ProjectModel(project_name="Hot Stone VILLA", **kwargs)  # type: ignore[arg-type]


def group_addresses(*ids: str) -> tuple[GroupAddress, ...]:
    return tuple(GroupAddress(id=i, address="1/1/1", name=i) for i in ids)


def devices(*ids: str) -> tuple[Device, ...]:
    return tuple(Device(id=i, name=i, individual_address="1.1.1") for i in ids)


def test_mints_one_past_the_highest_existing_number():
    base = project(group_addresses=group_addresses("prj:GA-264", "prj:GA-266", "prj:GA-265"))

    assert SequentialIdentityStrategy().mint_id("group_address", base) == "prj:GA-267"


def test_reuses_the_prefix_the_project_already_uses_for_that_kind():
    base = project(rooms=(Room(id="BP-7", name="Bedroom"),))

    assert SequentialIdentityStrategy().mint_id("room", base) == "BP-8"


def test_successive_mints_do_not_collide():
    """Section 14: unique against other CREATEs in the same changeset."""
    base = project(devices=devices("prj:DI-50"))
    strategy = SequentialIdentityStrategy()

    minted = [strategy.mint_id("device", base) for _ in range(3)]

    assert minted == ["prj:DI-51", "prj:DI-52", "prj:DI-53"]
    assert len(set(minted)) == 3


def test_each_kind_is_numbered_independently():
    base = project(
        rooms=(Room(id="prj:BP-4", name="Bedroom"),),
        devices=devices("prj:DI-50"),
        group_addresses=group_addresses("prj:GA-266"),
    )
    strategy = SequentialIdentityStrategy()

    assert strategy.mint_id("room", base) == "prj:BP-5"
    assert strategy.mint_id("device", base) == "prj:DI-51"
    assert strategy.mint_id("group_address", base) == "prj:GA-267"


def test_falls_back_to_the_observed_reference_prefix_for_an_empty_kind():
    assert SequentialIdentityStrategy().mint_id("group_address", project()) == "prj:GA-1"


def test_skips_an_id_already_taken_by_another_kind():
    """Section 14: uniqueness spans the project, not just the kind."""
    base = project(
        devices=devices("shared-1"),
        # Same prefix in another kind already occupies the next number.
        group_addresses=group_addresses("shared-2"),
    )

    assert SequentialIdentityStrategy().mint_id("device", base) == "shared-3"


def test_communication_object_ids_are_never_reused_even_though_never_minted():
    base = project(
        devices=devices("prj:DI-50"),
        communication_objects=(CommunicationObject(id="prj:DI-51", name="Switch"),),
    )

    assert SequentialIdentityStrategy().mint_id("device", base) == "prj:DI-52"


def test_the_majority_prefix_wins_over_a_single_odd_id():
    base = project(group_addresses=group_addresses("prj:GA-1", "prj:GA-2", "legacy-99"))

    assert SequentialIdentityStrategy().mint_id("group_address", base) == "prj:GA-3"


def test_an_id_without_a_number_does_not_break_minting():
    base = project(rooms=(Room(id="prj:BP-3", name="A"), Room(id="unnumbered", name="B")))

    assert SequentialIdentityStrategy().mint_id("room", base) == "prj:BP-4"


def test_an_unmintable_kind_is_an_error_not_a_guessed_id():
    with pytest.raises(UnknownObjectKindError, match="scene"):
        SequentialIdentityStrategy().mint_id("scene", project())


def test_two_strategies_do_not_share_issued_ids():
    base = project(devices=devices("prj:DI-1"))

    assert SequentialIdentityStrategy().mint_id("device", base) == "prj:DI-2"
    assert SequentialIdentityStrategy().mint_id("device", base) == "prj:DI-2"


def test_issued_ids_are_recorded():
    base = project(devices=devices("prj:DI-1"))
    strategy = SequentialIdentityStrategy()

    strategy.mint_id("device", base)
    strategy.mint_id("device", base)

    assert strategy.issued == {"prj:DI-2", "prj:DI-3"}

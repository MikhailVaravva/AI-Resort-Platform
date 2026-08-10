"""Turning off state sync for addresses nothing answers.

Home Assistant reads every state address at startup and warns on each
timeout. Some addresses can never answer, so the read is pure noise - but
which ones is not something the ETS project knows, which is why the
caller states them.
"""

import yaml

from ai_resort_platform.ets.group_addresses import GroupAddress
from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.generators.ha_yaml import package_to_yaml
from ai_resort_platform.homeassistant.builder import build_package


def _ga(address, name, main, sub):
    return GroupAddress(id=address, address=address, name=name, dpt_main=main, dpt_sub=sub)


def _project():
    return ETSProject(
        name="T",
        guid="g",
        tool_version="6",
        group_addresses=(
            # Sensors, not switches: `sync_state` is not a universal KNX
            # option and the switch platform rejects it (see
            # _SYNC_STATE_DOMAINS).
            _ga("1/1/40", "A1 Outside Temperature", 9, 1),
            _ga("1/1/41", "A1 Indoor Temperature", 9, 1),
        ),
    )


def test_an_entity_whose_state_address_never_answers_stops_being_read():
    package = build_package(_project(), unresponsive_addresses=("1/1/41",))
    by_name = {e.name: e for e in package.entities}

    assert by_name["Indoor Temperature"].config["sync_state"] is False
    assert by_name["Outside Temperature"].config.get("sync_state") is None


def test_nothing_changes_without_the_argument():
    """Silence is opt-in: a project alone never says an address is mute."""
    package = build_package(_project())

    assert all("sync_state" not in e.config for e in package.entities)


def test_a_mixed_entity_keeps_its_sync():
    """`sync_state` is per entity, not per address. Switching it off for an
    entity that also has an answering state address would trade real state
    for a quieter log."""
    project = ETSProject(
        name="T",
        guid="g",
        tool_version="6",
        group_addresses=(
            _ga("1/1/0", "A1 G1 on/off", 1, 1),
            _ga("1/1/1", "A1 G1 Switch status", 1, 1),
            _ga("1/1/2", "A1 G1 Brightness Absolut", 5, 1),
            _ga("1/1/3", "A1 G1 Brightness status", 5, 1),
        ),
    )

    package = build_package(project, unresponsive_addresses=("1/1/3",))

    (light,) = [e for e in package.entities if e.domain == "light"]
    assert "1/1/1" in light.config.values()
    assert "1/1/3" in light.config.values()
    assert "sync_state" not in light.config


def test_command_only_entities_are_untouched():
    """No state address means no read to silence in the first place."""
    project = ETSProject(
        name="T",
        guid="g",
        tool_version="6",
        group_addresses=(_ga("1/1/60", "A1 Bell", 1, 7),),
    )

    package = build_package(project, unresponsive_addresses=("1/1/60",))

    assert all("sync_state" not in e.config for e in package.entities)


def test_yaml_emits_a_real_boolean():
    package = build_package(_project(), unresponsive_addresses=("1/1/41",))

    sensors = yaml.safe_load(package_to_yaml(package))["knx"]["sensor"]
    silenced = next(s for s in sensors if s["name"] == "Indoor Temperature")
    assert silenced["sync_state"] is False


def test_a_domain_that_rejects_sync_state_is_left_alone():
    """`sync_state` is not a universal KNX option. Emitting it for a
    `light` failed setup for the entire knx integration on the live
    installation - an unknown key is not ignored, it takes every KNX
    entity in the package down with it."""
    project = ETSProject(
        name="T",
        guid="g",
        tool_version="6",
        group_addresses=(
            _ga("1/1/0", "A1 G1 on/off", 1, 1),
            _ga("1/1/1", "A1 G1 Switch status", 1, 1),
            _ga("1/1/2", "A1 G1 Brightness Absolut", 5, 1),
            _ga("1/1/3", "A1 G1 Brightness status", 5, 1),
            _ga("1/1/50", "A1 Fan", 1, 1),
            _ga("1/1/51", "A1 Fan status", 1, 1),
        ),
    )

    package = build_package(project, unresponsive_addresses=("1/1/1", "1/1/3", "1/1/51"))

    for entity in package.entities:
        if entity.domain in ("light", "switch", "cover", "number", "button"):
            assert "sync_state" not in entity.config, entity.name


def test_a_bus_that_answers_nothing_silences_every_readable_entity():
    """Stronger than a list of addresses, and it needed stronger evidence:
    2342 outgoing reads with not one GroupValueResponse in the telegram
    log, then ETS reading a group address on its own tunnel and receiving
    nothing back."""
    package = build_package(_project(), answers_read_requests=False)

    with_state = [e for e in package.entities if any(k.endswith("state_address") for k in e.config)]
    assert with_state
    for entity in with_state:
        assert entity.config["sync_state"] is False, entity.name


def test_it_still_reaches_no_platform_that_rejects_the_option():
    project = ETSProject(
        name="T",
        guid="g",
        tool_version="6",
        group_addresses=(
            _ga("1/1/0", "A1 G1 on/off", 1, 1),
            _ga("1/1/1", "A1 G1 Switch status", 1, 1),
            _ga("1/1/2", "A1 G1 Brightness Absolut", 5, 1),
            _ga("1/1/3", "A1 G1 Brightness status", 5, 1),
        ),
    )

    package = build_package(project, answers_read_requests=False)

    for entity in package.entities:
        if entity.domain in ("light", "switch", "cover", "number", "button"):
            assert "sync_state" not in entity.config, entity.name

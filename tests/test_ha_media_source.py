"""The media_player with a media source as its child.

KNX carries no artwork, and its longest string is a 14-character EIS15,
so metadata has to come from a player that speaks the module's own
protocol. `universal` supplies exactly that mechanism: anything not named
in `commands`/`attributes` falls through to the child.
"""

import yaml

from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.generators.ha_yaml import package_to_yaml
from ai_resort_platform.homeassistant.builder import build_package
from tests.test_homeassistant_builder_reference_villa import REFERENCE_VILLA

SOURCE = "media_player.192_168_1_17"


def _player(**kwargs: object):
    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    (player,) = build_package(project, **kwargs).media_players  # type: ignore[arg-type]
    return player


def test_without_a_source_transport_stays_on_knx():
    commands = _player().commands

    assert commands["media_play"]["target"] == {"entity_id": "switch.audio_play_pause"}
    assert commands["media_next_track"]["target"] == {"entity_id": "button.audio_next_prev"}
    assert _player().children == ()


def test_with_a_source_transport_is_delegated_to_the_child():
    """The child does play/pause/next/previous better than the bus can:
    real transport state instead of a write-only pulse."""
    player = _player(audio_media_source=SOURCE)

    assert player.children == (SOURCE,)
    for delegated in ("media_play", "media_pause", "media_next_track", "media_previous_track"):
        assert delegated not in player.commands


def test_playlist_selection_stays_on_knx_so_the_check_in_automation_keeps_working():
    """The module's Direct Playlist Selection (1/1/239) is not the child's
    `source`, and _build_welcome_automation calls select_source with that
    playlist index - delegating it would break check-in."""
    player = _player(audio_media_source=SOURCE)

    assert player.commands["select_source"]["target"] == {
        "entity_id": "number.audio_playlist_select"
    }
    assert player.attributes["source"] == "number.audio_playlist_select"


def test_the_amplifier_stays_on_knx_even_with_a_source():
    """Power, volume and mute act on hardware no media source can reach."""
    commands = _player(audio_media_source=SOURCE).commands

    assert commands["turn_on"]["target"] == {"entity_id": "switch.audio_power"}
    assert commands["turn_off"]["target"] == {"entity_id": "switch.audio_power"}
    assert commands["volume_mute"]["target"] == {"entity_id": "switch.audio_mute"}
    assert commands["volume_set"]["target"] == {"entity_id": "light.audio_absolut_volume"}


def test_the_knx_title_no_longer_overrides_the_childs():
    """Mapping media_title to the KNX sensor would replace the child's real
    title with a 14-character truncation of it."""
    player = _player(audio_media_source=SOURCE)

    assert "media_title" not in player.attributes
    assert player.attributes == {
        "is_volume_muted": "switch.audio_mute",
        "volume_level": "sensor.villa_a1_audio_volume",
        "source": "number.audio_playlist_select",
    }


def test_state_is_the_childs_unless_the_amplifier_is_off():
    player = _player(audio_media_source=SOURCE)
    assert player.state_template is not None

    # Standby, not the power switch: the switch has no readable status
    # (its callback's polarity is inverted, see
    # _apply_audio_module_semantics).
    assert "binary_sensor.audio_standby" in player.state_template
    assert f"states('{SOURCE}')" in player.state_template
    # play/pause is the child's business now, not a KNX switch's.
    assert "audio_play_pause" not in player.state_template


def test_yaml_emits_children_for_the_universal_platform():
    package_yaml = package_to_yaml(
        build_package(ETSProject.open(REFERENCE_VILLA, password="12345"), audio_media_source=SOURCE)
    )

    (entry,) = yaml.safe_load(package_yaml)["media_player"]
    assert entry["platform"] == "universal"
    assert entry["children"] == [SOURCE]


def test_occupancy_automations_ignore_restart_transitions():
    """An HA restart takes every entity through `unavailable` on the way
    back, so a trigger with only `to:` fires on unavailable -> off. That
    was observed silencing the live villa on every restart."""
    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    package = build_package(project, welcome_playlist=1, background_playlist=2)

    for automation in package.automations:
        (trigger,) = automation.triggers
        assert trigger["from"] in ("on", "off"), automation.name
        assert trigger["from"] != trigger["to"], automation.name

"""Integration tests against the installation's own ETS project.

The reference project under examples/Reference-Villa predates the audio
module's equalizer and source addresses, so until this file existed the
features built on them were covered only by synthetic projects - the
generator was never run end to end against the thing it actually
generates for.
"""

from pathlib import Path

import pytest

from ai_resort_platform.deployment import load_deployment
from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.homeassistant.builder import (
    _SYNC_STATE_DOMAINS,
    AUDIO_EQUALIZER_PRESETS,
    AUDIO_SOURCE_OPTIONS,
    build_dashboard,
    build_package,
)

ROOT = Path(__file__).resolve().parent.parent
VILLA_A1 = ROOT / "examples" / "Villa-A1" / "villa_a1.knxproj"
PASSWORD = "00000000"


@pytest.fixture(scope="module")
def project() -> ETSProject:
    return ETSProject.open(VILLA_A1, password=PASSWORD)


@pytest.fixture(scope="module")
def package(project: ETSProject):
    recipe = load_deployment(ROOT / "deployments" / "villa_a1.toml")
    return build_package(
        project,
        welcome_playlist=recipe.welcome_playlist,
        background_playlist=recipe.background_playlist,
        audio_media_source=recipe.audio_media_source,
        unresponsive_addresses=recipe.unresponsive_addresses,
        answers_read_requests=recipe.answers_read_requests,
    )


def test_the_recipe_points_at_this_project():
    """A recipe naming a project that is not in the checkout would build
    on one machine only."""
    recipe = load_deployment(ROOT / "deployments" / "villa_a1.toml")

    assert recipe.project_path == VILLA_A1
    assert recipe.project_path.exists()


def test_the_project_carries_the_addresses_added_for_the_audio_module(project: ETSProject):
    addresses = {ga.address for ga in project.group_addresses}

    assert len(addresses) == 74
    for added in (
        "1/1/200",
        "1/1/201",
        "1/1/204",
        "1/1/205",
        "1/1/206",
        "1/1/207",
        "1/1/217",
        "1/1/219",
        "1/1/228",
        "1/1/229",
        "1/1/230",
        "1/1/233",
    ):
        assert added in addresses, added


def test_the_equalizer_comes_from_the_project_with_no_argument(package):
    """The whole point of adding 1/1/200 to ETS: no caller has to hand it
    in any more."""
    (equalizer,) = [s for s in package.selects if "Equalizer" in s.name]

    assert equalizer.address == "1/1/200"
    assert equalizer.state_address == "1/1/201"
    assert equalizer.options == AUDIO_EQUALIZER_PRESETS
    assert equalizer.options[0] == ("Without Optimisation", 1)


def test_the_input_selector_is_a_named_select(package):
    (source,) = [s for s in package.selects if "Source" in s.name]

    assert source.address == "1/1/204"
    assert source.state_address == "1/1/205"
    assert source.options == AUDIO_SOURCE_OPTIONS
    assert source.payload_length == 0
    assert [e for e in package.entities if e.name == "Audio Source Select"] == []


def test_album_and_artist_arrive_as_their_own_sensors(package):
    by_name = {e.name: e for e in package.entities}

    for name, address in (
        ("Audio Album", "1/1/229"),
        ("Audio Artist", "1/1/230"),
        ("Audio Text View", "1/1/228"),
        ("Audio Playlist name", "1/1/233"),
        ("Audio Source Information", "1/1/206"),
    ):
        assert by_name[name].domain == "sensor"
        assert by_name[name].config["type"] == "latin_1"
        assert by_name[name].config["state_address"] == address


def test_addresses_nothing_answers_are_not_polled(package):
    """Confirmed on 14 August, with the whole bus connected: of Villa
    A1's 25 status addresses, exactly one (1/1/170, DMX Terrace Dimming)
    answered a read. The recipe accepts that trade rather than special
    case the one exception - see its own `answers_read_requests` comment
    - so every state address the generator is able to suppress is
    suppressed, the audio module's included but not exclusive.
    """
    silenced = {e.name for e in package.entities if e.config.get("sync_state") is False}

    assert "Audio Track name" in silenced
    assert "Audio Standby" in silenced

    # No longer special cases: the 14 August measurement covered the rest
    # of the bus too, and the recipe's `answers_read_requests=False`
    # makes no exception for them.
    for entity in package.entities:
        if entity.domain not in _SYNC_STATE_DOMAINS:
            continue
        has_state_address = any(
            key.endswith("state_address") and isinstance(value, str)
            for key, value in entity.config.items()
        )
        if has_state_address:
            assert entity.config.get("sync_state") is False, entity.name

    # A platform that rejects the option never receives it, whatever the
    # recipe says - emitting it for a light once failed setup for the
    # entire knx integration.
    for entity in package.entities:
        if entity.domain in ("light", "switch", "cover", "number", "button"):
            assert "sync_state" not in entity.config, entity.name


def test_check_in_sets_the_playlist_directly(package):
    welcome = package.automations[0]

    assert welcome.triggers[0]["from"] == "off"
    for step in (welcome.actions[1], welcome.actions[5]):
        assert step["action"] == "number.set_value"
        assert step["target"] == {"entity_id": "number.audio_playlist_select"}


def test_the_player_composes_knx_control_with_the_media_source(package):
    (player,) = package.media_players

    assert player.children == ("media_player.192_168_1_147",)
    # Physical: the amplifier, which no media source can reach.
    assert player.commands["turn_on"]["target"] == {"entity_id": "switch.audio_power"}
    assert player.commands["volume_set"]["target"] == {"entity_id": "light.audio_absolut_volume"}
    # Logical: delegated, so artwork and full-length metadata come through.
    assert "media_play" not in player.commands
    assert "media_title" not in player.attributes


def test_the_dashboard_shows_the_controls_before_the_readings(package):
    titles = [c.title for c in build_dashboard(package).views[0].cards]

    assert titles[0] == "Villa A1 Audio"
    assert titles[1] == "Selects"
    assert titles.index("Selects") < titles.index("Sensors")

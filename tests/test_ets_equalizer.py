"""The audio module's equalizer - the first entity built from addresses the
ETS project does not contain."""

import yaml

from ai_resort_platform.generators.ha_package import HaSelect, HomeAssistantPackage
from ai_resort_platform.generators.ha_yaml import package_to_yaml
from ai_resort_platform.homeassistant.builder import (
    AUDIO_EQUALIZER_PRESETS,
    AudioEqualizerAddresses,
)

EQUALIZER = AudioEqualizerAddresses(address="1/1/200", state_address="1/1/201")


def _package(*selects: HaSelect) -> HomeAssistantPackage:
    return HomeAssistantPackage(villa_id="g", villa_name="Villa A1", selects=selects)


def test_presets_carry_the_documented_payloads_and_are_numbered_from_one():
    """The official documentation lists the profiles as "- (1) Without
    Optimisation" ... "- (10) Mono" and says those bracketed numbers are the
    EIS14 values to send. Numbering from 0 would select the wrong profile
    for every entry, and the last one would not exist at all."""
    assert AUDIO_EQUALIZER_PRESETS[0] == ("Without Optimisation", 1)
    assert AUDIO_EQUALIZER_PRESETS[1] == ("Bass Boost", 2)
    assert AUDIO_EQUALIZER_PRESETS[-1] == ("Mono", 10)
    assert [payload for _, payload in AUDIO_EQUALIZER_PRESETS] == list(range(1, 11))


def test_yaml_gives_every_option_an_explicit_payload():
    select = HaSelect(
        unique_id="villa_a1_audio_equalizer",
        name="Villa A1 Audio Equalizer",
        address=EQUALIZER.address,
        state_address=EQUALIZER.state_address,
        options=AUDIO_EQUALIZER_PRESETS,
    )

    knx = yaml.safe_load(package_to_yaml(_package(select)))["knx"]

    (entry,) = knx["select"]
    assert entry["address"] == "1/1/200"
    assert entry["state_address"] == "1/1/201"
    assert entry["payload_length"] == 1
    assert entry["options"] == [
        {"option": name, "payload": payload} for name, payload in AUDIO_EQUALIZER_PRESETS
    ]
    assert entry["options"][0] == {"option": "Without Optimisation", "payload": 1}
    # unique_id is not a documented KNX option, same as every other entity.
    assert "unique_id" not in entry


def test_a_package_without_an_equalizer_emits_no_select_key():
    assert "select" not in (yaml.safe_load(package_to_yaml(_package())).get("knx") or {})


def test_the_equalizer_reaches_the_dashboard():
    """A select is not an HaEntity, so build_dashboard's domain loop cannot
    see it - without its own card the equalizer is generated and then
    invisible, which is what happened on the live installation."""
    from ai_resort_platform.ets.project import ETSProject
    from ai_resort_platform.homeassistant.builder import (
        AudioEqualizerAddresses,
        build_dashboard,
        build_package,
    )
    from tests.test_homeassistant_builder_reference_villa import REFERENCE_VILLA

    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    package = build_package(project, audio_equalizer=AudioEqualizerAddresses(address="1/1/200"))

    view = build_dashboard(package).views[0]
    (card,) = [c for c in view.cards if c.title == "Selects"]

    assert card.entities == ("select.villa_a1_audio_equalizer",)


def test_no_selects_card_without_an_equalizer():
    from ai_resort_platform.ets.project import ETSProject
    from ai_resort_platform.homeassistant.builder import build_dashboard, build_package
    from tests.test_homeassistant_builder_reference_villa import REFERENCE_VILLA

    package = build_package(ETSProject.open(REFERENCE_VILLA, password="12345"))
    view = build_dashboard(package).views[0]

    assert [c for c in view.cards if c.title == "Selects"] == []


def _project_with(*group_addresses):
    from ai_resort_platform.ets.project import ETSProject

    return ETSProject(name="T", guid="g", tool_version="6", group_addresses=group_addresses)


def _ga(address, name, main, sub):
    from ai_resort_platform.ets.group_addresses import GroupAddress

    return GroupAddress(id=address, address=address, name=name, dpt_main=main, dpt_sub=sub)


EQ_COMMAND = _ga("1/1/200", "A1 Audio Equalizer", 5, None)
EQ_STATUS = _ga("1/1/201", "A1 Audio Equalizer status", 5, None)


def test_the_equalizer_is_taken_from_the_project_when_it_carries_it():
    """No explicit argument needed once ETS has the addresses - that
    parameter existed to make the gap visible, not to keep it."""
    from ai_resort_platform.homeassistant.builder import build_package

    package = build_package(_project_with(EQ_COMMAND, EQ_STATUS))

    (select,) = package.selects
    assert select.address == "1/1/200"
    assert select.state_address == "1/1/201"
    assert select.options == AUDIO_EQUALIZER_PRESETS


def test_the_generic_sensor_for_those_addresses_is_removed():
    """Left alone the pipeline makes the pair a read-only
    1byte_unsigned sensor on 1/1/201 and drops the command address
    entirely - both wrong and a duplicate of the select."""
    from ai_resort_platform.homeassistant.builder import build_package

    package = build_package(_project_with(EQ_COMMAND, EQ_STATUS))

    assert [e.name for e in package.entities] == []


def test_an_explicit_argument_still_wins_over_the_project():
    from ai_resort_platform.homeassistant.builder import (
        AudioEqualizerAddresses,
        build_package,
    )

    package = build_package(
        _project_with(EQ_COMMAND, EQ_STATUS),
        audio_equalizer=AudioEqualizerAddresses(address="2/1/1", state_address="2/1/2"),
    )

    (select,) = package.selects
    assert select.address == "2/1/1"


def test_a_command_without_a_status_still_builds_a_select():
    from ai_resort_platform.homeassistant.builder import build_package

    (select,) = build_package(_project_with(EQ_COMMAND)).selects

    assert select.address == "1/1/200"
    assert select.state_address is None


def test_controls_come_before_readings_on_the_dashboard():
    """Card order decides whether a control can be found at all.

    The equalizer was originally card nine, behind a twenty-row Sensors
    list, which put it a screen and a half down the page - generated,
    deployed, and in practice unfindable.
    """
    from ai_resort_platform.ets.project import ETSProject
    from ai_resort_platform.homeassistant.builder import (
        AudioEqualizerAddresses,
        build_dashboard,
        build_package,
    )
    from tests.test_homeassistant_builder_reference_villa import REFERENCE_VILLA

    project = ETSProject.open(REFERENCE_VILLA, password="12345")
    package = build_package(project, audio_equalizer=AudioEqualizerAddresses(address="1/1/200"))

    titles = [c.title for c in build_dashboard(package).views[0].cards]

    assert titles.index("Selects") < titles.index("Sensors")
    assert titles.index("Villa A1 Audio") < titles.index("Sensors")
    # The media player is what the villa is currently doing - first.
    assert titles[0] == "Villa A1 Audio"
    assert titles[1] == "Selects"

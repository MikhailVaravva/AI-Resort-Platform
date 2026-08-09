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


def test_presets_are_the_modules_own_list_in_its_own_order():
    """The payload is the index, so the order is load-bearing, not cosmetic."""
    assert AUDIO_EQUALIZER_PRESETS[0] == "Without Optimisation"
    assert AUDIO_EQUALIZER_PRESETS[1] == "Bass Boost"
    assert AUDIO_EQUALIZER_PRESETS[-1] == "Mono"
    assert len(AUDIO_EQUALIZER_PRESETS) == 10


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
        {"option": name, "payload": index} for index, name in enumerate(AUDIO_EQUALIZER_PRESETS)
    ]
    # unique_id is not a documented KNX option, same as every other entity.
    assert "unique_id" not in entry


def test_a_package_without_an_equalizer_emits_no_select_key():
    assert "select" not in (yaml.safe_load(package_to_yaml(_package())).get("knx") or {})

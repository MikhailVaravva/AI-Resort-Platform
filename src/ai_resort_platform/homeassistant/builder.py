"""Builds a Home Assistant package directly from an ETSProject.

The first ETSProject consumer. Reuses the existing HA output model and
YAML serialization as-is (generators/ha_package.py, generators/ha_yaml.py -
neither depends on digital_twin, so both are reusable unchanged). Only the
classification/grouping step is new: generators/ha_builder.py's version
expects digital_twin's pre-grouped Entity/Capability model, which this
project no longer builds - ETSProject exposes flat GroupAddresses instead,
so grouping them into entities (and now scenes) has to happen here,
directly from ETSProject.group_addresses.

Scope: entities (light/switch/binary_sensor/cover/sensor), scenes/scripts,
and the overview dashboard - full coverage of generators/ha_builder.py. No
automations (neither builder has any - see
generators/ha_package.py:HaAutomation).
"""

import re

from ai_resort_platform.ets.group_addresses import GroupAddress
from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.generators.ha_package import (
    Dashboard,
    DashboardCard,
    DashboardView,
    HaEntity,
    HaMediaPlayer,
    HaScene,
    HaScript,
    HomeAssistantPackage,
)

_SLUG_INVALID = re.compile(r"[^a-z0-9]+")
_VILLA_CODE_PREFIX = re.compile(r"^[A-Z]\d+\s+")
# Same source-naming quirks handled in generators/ha_builder.py: a status GA
# is sometimes "X status", sometimes "X, status" (stray comma); a command GA
# sometimes has a trailing "value" its status counterpart omits.
_STATUS_SUFFIX = re.compile(r"[,\s]+status$", re.IGNORECASE)
_VALUE_SUFFIX = re.compile(r"\s+value$", re.IGNORECASE)
_TRAILING_NOISE = re.compile(r"[,\s]+$")
_GROUP_TOKEN = re.compile(r"\bG(\d+)\b", re.IGNORECASE)
_COVER_KEYWORDS = ("curtain", "cover", "blind", "shutter")
_SCENE_NUMBER = re.compile(r"\bscene\s+(\d+)\b", re.IGNORECASE)
# DPST-18-1 "scene control" - the recall/store control point. Verified
# against the reference project (see docstring in _extract_scenes).
_SCENE_CONTROL_DPT: tuple[int, int | None] = (18, 1)

# Exact (dpt_main, dpt_sub) pairs that make an entity a light - NOT dpt_main
# alone: dpt_main=5 is also used for e.g. an audio play-mode counter
# (5.10), which must not become a "light" just because it shares the main
# DPT number with brightness (5.1). Verified against the reference project.
_LIGHT_DPTS: set[tuple[int, int | None]] = {(5, 1), (7, 600)}
_SWITCH_DPT_MAIN = 1
# DPST-11-1 "date" - has its own dedicated KNX platform (`date:`), not
# `sensor` (DPT main-type 11 doesn't appear in the sensor "Value types"
# table at all). Verified against the reference project and the official
# KNX integration documentation (home-assistant.io/integrations/knx/).
_DATE_DPT: tuple[int, int | None] = (11, 1)

# DPST-1-7 "step" (increase/decrease) - a momentary directional pulse by
# KNX specification, not a persistent on/off state: a device receiving it
# performs one step and does not "stay" in the sent value the way a real
# switch does. Modeled as `button` (a stateless, single-press KNX
# platform) rather than `switch`, but only when the group address is
# command-only (no status GA at all) - if a device ever DID report a
# genuine status back for a DPST-1-7 point, that would mean it behaves as
# a persistent state after all, and the switch-merge logic above should
# handle it instead. Verified against the reference project: "Curtain
# Stop" (handled separately by _build_cover, before this ever runs) and
# "Audio Next/Prev" are the only DPST-1-7 group addresses, and neither has
# a status counterpart.
_TRIGGER_DPTS: set[tuple[int, int | None]] = {(1, 7)}

# Home Assistant KNX `sensor.type` identifiers ("Value types" table,
# home-assistant.io/integrations/knx/) for the DPTs this builder's sensor
# fallback actually emits. Verified against that table directly (not
# guessed, and not xknx's internal DPT names, which don't always match the
# documented HA option) - anything not listed here falls back to the
# numeric "{main}.{sub}" label.
#
# DPT main-type 1 (switch/enable/step/open_close/start), DPT 11.001 (date),
# and DPT 18.001 (scene_control) are deliberately NOT here: none of them
# appear in the documented Value types table at all - HA has no valid
# `sensor.type` for a DPT-1.x value, and dates/scene-control are handled by
# their own dedicated platforms (`date:`, and the Scene platform's own
# `scene_number`/`address`), not `sensor`. The numeric fallback does not
# fix this for those DPTs either - if a group address with one of these
# DPTs reaches `_sensor_fallback`, the resulting `type:` is not valid HA
# config; that can only be fixed by not classifying it as `sensor` at all,
# which is a domain/entity-selection decision, not a label fix.
_DPT_LABELS: dict[tuple[int, int | None], str] = {
    (5, 1): "percent",
    (5, 10): "pulse",
    (5, None): "1byte_unsigned",
    (7, 600): "color_temperature",
    (9, 1): "temperature",
    (9, 7): "humidity",
    (16, 1): "latin_1",
}

_DASHBOARD_SECTIONS = (
    ("light", "Lights"),
    ("cover", "Covers"),
    ("switch", "Switches"),
    ("binary_sensor", "Binary Sensors"),
    ("sensor", "Sensors"),
    ("date", "Dates"),
    ("number", "Numbers"),
    ("button", "Buttons"),
)


def _slugify(text: str) -> str:
    slug = _SLUG_INVALID.sub("_", text.lower()).strip("_")
    return slug or "entity"


def _entity_id(entity: HaEntity) -> str:
    """The `entity_id` Home Assistant actually assigns a KNX-platform
    entity: since `unique_id` isn't a supported KNX option (see
    generators/ha_yaml.py), HA derives it from `name` alone, not from our
    own internal `HaEntity.unique_id` - verified against a real running
    Home Assistant instance (e.g. "Audio Power" -> switch.audio_power, not
    switch.villa_a1_audio_power)."""
    return f"{entity.domain}.{_slugify(entity.name)}"


def build_package(project: ETSProject) -> HomeAssistantPackage:
    """Build one HomeAssistantPackage covering every group address in `project`.

    unique_ids are scoped to the villa's room name (e.g. "Villa A1"), not the
    whole project name ("Hot Stone VILLA") - matching the old DigitalTwin
    builder, which scoped ids per-villa/per-room. Falls back to the project
    name if the project has no rooms.
    """
    return _build_package(project, project.group_addresses)


# The BAB Audio Module device's own name in the reference project - the only
# reliable way to find it. Its `manufacturer`/`hardware_name`/`order_number`
# ("BAB TECHNOLOGIE GmbH"/"Module"/"0001") are identical to the DMX module's
# (verified against the reference project), so only the device name
# distinguishes them.
_AUDIO_MODULE_DEVICE_NAME = "Audio Module A1"


def build_audio_module_package(project: ETSProject) -> HomeAssistantPackage:
    """Build a HomeAssistantPackage covering only the group addresses wired
    to the BAB Audio Module device, so it can be tested in Home Assistant on
    its own.

    A group address "belongs to" the module if it's linked to one of the
    module's own communication objects (`Device.communication_object_ids`) -
    not by name-matching "Audio" in the group address name. That distinction
    matters here: several "Audio ..." group addresses (e.g. "Audio Volume
    status", "Audio Mute status", "Audio Play mode") are verified to be
    wired only to the KNX Smart Touch S3 touch panel's own communication
    objects, not the module's - they're the panel's own derived/mirrored
    values, not something the module itself sends or receives, so they're
    excluded here.
    """
    device = project.device(_AUDIO_MODULE_DEVICE_NAME)
    device_co_ids = set(device.communication_object_ids)
    group_addresses = tuple(
        ga for ga in project.group_addresses if device_co_ids & set(ga.communication_object_ids)
    )
    return _build_package(project, group_addresses)


def _build_package(
    project: ETSProject, group_addresses: tuple[GroupAddress, ...]
) -> HomeAssistantPackage:
    villa_name = project.rooms[0].name if project.rooms else project.name
    slug = _slugify(villa_name)
    cover_source, after_cover = _extract_cover_group_addresses(group_addresses)
    scenes, scripts, remaining = _extract_scenes(slug, after_cover)

    entities: list[HaEntity] = []
    if cover_source:
        entities.append(_build_cover(slug, cover_source))

    for entity_key, name, dpts in _group_addresses(remaining):
        entities.extend(_build_entities_for(slug, entity_key, name, dpts))

    entities = list(_apply_audio_module_semantics(tuple(entities)))
    media_player = _build_audio_media_player(slug, villa_name, tuple(entities))

    return HomeAssistantPackage(
        villa_id=project.guid,
        villa_name=villa_name,
        entities=tuple(entities),
        scenes=scenes,
        scripts=scripts,
        media_players=(media_player,) if media_player else (),
    )


def _apply_audio_module_semantics(entities: tuple[HaEntity, ...]) -> tuple[HaEntity, ...]:
    """Two of the audio module's entities need a different domain than the
    generic classification gives them, based on their real KNX behaviour
    (verified against the reference project's communication objects, not
    just DPT numbers) - scoped to exactly these two, by name, so nothing
    else's classification changes (e.g. the DMX channels have the same
    structural shape - a single command-role DPT 5 key - but are out of
    scope here):

    - "Audio Absolut volume" (DPT 5.001) has no DPT-1.x switch of its own,
      so the generic pipeline exposes it as a read-only `sensor` (see
      _build_entities_for) - but its communication object is genuinely
      read/write (verified), a continuously controllable level with
      nothing to switch, not a status readout. Rebuilt as a `light`
      instead: `address` is required by that platform regardless, so it
      borrows "Audio Power"'s (the same physical module, already a
      command target) to satisfy it, while `brightness_address` is the
      real, writable volume value - the point of this change is to make
      volume actually controllable, not just observable.
    - "Audio Playlist Select" (DPT 5, no sub-type) is wired to the exact
      same communication object as "Audio Absolut volume" (verified:
      identical read/write/communication/transmit flags) - a real,
      writable command target, not a status readout - so it becomes a
      `number` (writable) instead of a read-only `sensor`.
    """
    power = next((e for e in entities if e.name == "Audio Power"), None)
    if power is None:
        return entities

    result = []
    for entity in entities:
        if entity.name == "Audio Absolut volume" and entity.domain == "sensor":
            result.append(
                HaEntity(
                    domain="light",
                    unique_id=entity.unique_id,
                    name=entity.name,
                    config={
                        "address": power.config["address"],
                        "brightness_address": entity.config["state_address"],
                    },
                )
            )
        elif entity.name == "Audio Playlist Select" and entity.domain == "sensor":
            result.append(
                HaEntity(
                    domain="number",
                    unique_id=entity.unique_id,
                    name=entity.name,
                    config={
                        "address": entity.config["state_address"],
                        "type": entity.config["type"],
                    },
                )
            )
        else:
            result.append(entity)
    return tuple(result)


def _build_audio_media_player(
    slug: str, villa_name: str, entities: tuple[HaEntity, ...]
) -> HaMediaPlayer | None:
    """One `media_player` for the BAB Audio Module, composed entirely from
    entities `_build_package` already built for it (matched by `name`) -
    the KNX integration has no media_player platform of its own, and
    nothing here is re-derived from group addresses. Returns None if this
    project doesn't have all seven required source entities (e.g. no
    audio module wired up at all).
    """
    by_name = {e.name: e for e in entities}
    power = by_name.get("Audio Power")
    play_pause = by_name.get("Audio Play/Pause")
    next_track = by_name.get("Audio Next/Prev")
    volume = by_name.get("Audio Absolut volume")
    mute = by_name.get("Audio Mute")
    title = by_name.get("Audio Track name")
    playlist = by_name.get("Audio Playlist Select")
    if not (power and play_pause and next_track and volume and mute and title and playlist):
        return None

    def service(
        action: str, target: HaEntity, data: dict[str, object] | None = None
    ) -> dict[str, object]:
        call: dict[str, object] = {"action": action, "target": {"entity_id": _entity_id(target)}}
        if data:
            call["data"] = data
        return call

    return HaMediaPlayer(
        unique_id=f"{slug}_audio_module",
        name=f"{villa_name} Audio",
        commands={
            "turn_on": service("switch.turn_on", power),
            "turn_off": service("switch.turn_off", power),
            "media_play": service("switch.turn_on", play_pause),
            "media_pause": service("switch.turn_off", play_pause),
            # DPST-1-7 "step": a momentary pulse (see _TRIGGER_DPTS), not a
            # persistent state - modeled as a `button`, pressed via the
            # core button.press service. Value 1 (the button's default
            # payload) conventionally means "increase"; the source project
            # has no separate "previous" group address to map a
            # previous-track command to.
            "media_next_track": service("button.press", next_track),
            "volume_mute": service("switch.toggle", mute),
            # "Audio Absolut volume" is rebuilt as a `light` (see
            # _apply_audio_module_semantics) specifically so this can be a
            # real write, not just a display - light.turn_on's
            # brightness_pct (0-100) is the volume percentage HA's
            # 0.0-1.0 volume_level maps onto directly.
            "volume_set": service(
                "light.turn_on",
                volume,
                {"brightness_pct": "{{ (volume_level * 100) | round(0) }}"},
            ),
            # "Audio Playlist Select" is rebuilt as a `number` (see
            # _apply_audio_module_semantics) so this can write the
            # requested source through, not just display the current one.
            # There is no known name<->index mapping in the source
            # project, so `source` is expected to be that raw numeric
            # index as a string, not a friendly playlist name.
            "select_source": service("number.set_value", playlist, {"value": "{{ source }}"}),
        },
        # Home Assistant's Universal Media Player cannot derive
        # playing/idle/off from multiple entities without state_template.
        # This is intentional.
        #
        # Neither "Audio Power" nor "Audio Play/Pause" alone gives a valid
        # media_player state (their own state is just "on"/"off") - off
        # vs idle vs playing depends on BOTH together, which the
        # `universal` platform's plain attributes.state (a single bare
        # entity reference, no logic) can't express - state_template is
        # the documented mechanism for exactly this.
        state_template=(
            f"{{% if is_state('{_entity_id(power)}', 'off') %}}\n"
            "  off\n"
            f"{{% elif is_state('{_entity_id(play_pause)}', 'on') %}}\n"
            "  playing\n"
            "{% else %}\n"
            "  idle\n"
            "{% endif %}"
        ),
        attributes={
            "is_volume_muted": _entity_id(mute),
            # KNX `light.brightness` is HA's normalized 0-255 scale (xknx
            # converts the DPT 5.001 0-100% value for us) - still not the
            # exact 0.0-1.0 `volume_level` expects, since the `universal`
            # platform's `attributes:` supports only a bare entity/
            # attribute reference, no conversion. Documented limitation,
            # not fixable without a value not covered by this mapping.
            "volume_level": f"{_entity_id(volume)}|brightness",
            "media_title": _entity_id(title),
            # No `source_list` for the same reason: the project has no
            # catalog of playlist names, only this numeric index.
            "source": _entity_id(playlist),
        },
    )


def build_dashboard(package: HomeAssistantPackage) -> Dashboard:
    """Build a one-view overview dashboard for a villa's package."""
    cards = []
    for domain, title in _DASHBOARD_SECTIONS:
        entity_ids = tuple(_entity_id(e) for e in package.entities if e.domain == domain)
        if entity_ids:
            cards.append(DashboardCard(title=title, entities=entity_ids))

    if package.scenes:
        cards.append(
            DashboardCard(
                title="Scenes",
                entities=tuple(f"scene.{_slugify(s.name)}" for s in package.scenes),
            )
        )
    if package.scripts:
        cards.append(
            DashboardCard(
                title="Scripts", entities=tuple(f"script.{s.unique_id}" for s in package.scripts)
            )
        )
    for media_player in package.media_players:
        # The documented Lovelace card for a media_player entity
        # (home-assistant.io) - a single-entity card, not the generic
        # "entities" list card the sections above use.
        cards.append(
            DashboardCard(
                title=media_player.name,
                card_type="media-control",
                entity=f"media_player.{_slugify(media_player.name)}",
            )
        )

    view = DashboardView(title=package.villa_name, cards=tuple(cards))
    return Dashboard(villa_id=package.villa_id, title=package.villa_name, views=(view,))


def _strip_villa_code(name: str) -> str:
    return _VILLA_CODE_PREFIX.sub("", name, count=1)


def _extract_cover_group_addresses(
    group_addresses: tuple[GroupAddress, ...],
) -> tuple[list[GroupAddress], list[GroupAddress]]:
    cover_ids = {
        ga.id
        for ga in group_addresses
        if any(keyword in ga.name.lower() for keyword in _COVER_KEYWORDS)
    }
    cover_gas = [ga for ga in group_addresses if ga.id in cover_ids]
    remaining = [ga for ga in group_addresses if ga.id not in cover_ids]
    return cover_gas, remaining


def _extract_scenes(
    slug: str, group_addresses: list[GroupAddress]
) -> tuple[tuple[HaScene, ...], tuple[HaScript, ...], list[GroupAddress]]:
    """Pull scene-related group addresses out, mirroring
    digital_twin/builder.py's heuristic: DPST-18-1 (verified above against
    the real reference project) is the recall/store control point; a
    "Scene N" name pairs a status group address with that control point.

    The control GA itself never becomes a generic entity (same as the old
    builder): it only exists as the `address` referenced by each numbered
    HaScene, not as its own YAML entry.
    """
    control_gas = [ga for ga in group_addresses if (ga.dpt_main, ga.dpt_sub) == _SCENE_CONTROL_DPT]
    control_address = control_gas[0].address if control_gas else None
    consumed_ids = {ga.id for ga in control_gas}

    scenes: list[HaScene] = []
    scripts: list[HaScript] = []
    remaining: list[GroupAddress] = []

    for ga in group_addresses:
        if ga.id in consumed_ids:
            continue
        if control_address is None:
            remaining.append(ga)
            continue
        match = _SCENE_NUMBER.search(_strip_villa_code(ga.name))
        if match is None:
            remaining.append(ga)
            continue

        number = int(match.group(1))
        scene_unique_id = f"{slug}_scene_{number}"
        scenes.append(
            HaScene(
                unique_id=scene_unique_id,
                name=f"Scene {number}",
                address=control_address,
                scene_number=number,
            )
        )
        scripts.append(
            HaScript(
                unique_id=f"{slug}_activate_scene_{number}",
                name=f"Activate Scene {number}",
                sequence=(
                    {
                        "service": "scene.turn_on",
                        "target": {"entity_id": f"scene.{scene_unique_id}"},
                    },
                ),
            )
        )

    return tuple(scenes), tuple(scripts), remaining


def _build_cover(slug: str, cover_gas: list[GroupAddress]) -> HaEntity:
    config: dict[str, str] = {}
    for ga in cover_gas:
        remainder = _strip_villa_code(ga.name)
        is_status = bool(_STATUS_SUFFIX.search(remainder))
        if ga.dpt_main == 1 and ga.dpt_sub == 9:  # DPST-1-9 up/down
            config["move_long_address"] = ga.address
        elif ga.dpt_main == 1 and ga.dpt_sub == 7:  # DPST-1-7 step/stop
            config["stop_address"] = ga.address
        elif ga.dpt_main == 5:  # scaling: position command/status
            config["position_state_address" if is_status else "position_address"] = ga.address

    name = next(kw for kw in _COVER_KEYWORDS if kw in cover_gas[0].name.lower()).capitalize()
    unique_id = f"{slug}_{_slugify(name)}"
    return HaEntity(domain="cover", unique_id=unique_id, name=name, config=config)


def _group_addresses(
    group_addresses: list[GroupAddress],
) -> list[tuple[str, str, dict[tuple[int, int | None], dict[str, GroupAddress]]]]:
    """Group group addresses by entity key, then by (dpt_main, dpt_sub).

    Mirrors digital_twin/builder.py's proven heuristic: a "G<N>" token is an
    explicit entity marker; otherwise a command GA and its status GA are
    paired by name (after stripping "status"/"value" suffixes and stray
    punctuation) rather than merged with unrelated group addresses.
    """
    names: dict[str, str] = {}
    order: list[str] = []
    dpts_by_key: dict[str, dict[tuple[int, int | None], dict[str, GroupAddress]]] = {}

    for ga in group_addresses:
        remainder = _strip_villa_code(ga.name)
        is_status = bool(_STATUS_SUFFIX.search(remainder))
        base = _STATUS_SUFFIX.sub("", remainder) if is_status else remainder
        base = _VALUE_SUFFIX.sub("", base)
        base = _TRAILING_NOISE.sub("", base).strip()

        group_match = _GROUP_TOKEN.search(base)
        entity_key = f"G{group_match.group(1)}" if group_match else base
        if entity_key not in names:
            names[entity_key] = entity_key if group_match else base
            order.append(entity_key)

        dpt_key = (ga.dpt_main, ga.dpt_sub) if ga.dpt_main is not None else (-1, None)
        role = "status" if is_status else "command"
        dpts_by_key.setdefault(entity_key, {}).setdefault(dpt_key, {})[role] = ga

    return [(key, names[key], dpts_by_key[key]) for key in order]


def _build_entities_for(
    slug: str,
    entity_key: str,
    name: str,
    dpts: dict[tuple[int, int | None], dict[str, GroupAddress]],
) -> list[HaEntity]:
    base_id = f"{slug}_{_slugify(name)}"
    light_keys = {k for k in dpts if k in _LIGHT_DPTS}
    switch_keys = {k for k in dpts if k[0] == _SWITCH_DPT_MAIN}

    # The KNX `light` platform requires `address` (switching) or
    # `individual_colors` - confirmed against a real Home Assistant
    # instance, which rejects a light with only `brightness_address`/
    # `color_temperature_address` and no switch DPT at all (e.g. a DMX
    # dimmer channel or "Audio Absolut volume" that only has a DPT 5.001
    # scaling address, no DPT 1.x). Without a switch key there is no valid
    # `light` config to build, so these fall through to `_sensor_fallback`
    # instead (DPT 5.001/7.600 both have documented sensor.type values -
    # "percent"/"color_temperature" - so they're still exposed, read-only).
    if light_keys and switch_keys:
        used_keys = light_keys | switch_keys
        config = _light_config(dpts, light_keys, switch_keys)
        entities = [HaEntity(domain="light", unique_id=base_id, name=name, config=config)]
        leftover = {k: v for k, v in dpts.items() if k not in used_keys}
        entities.extend(_sensor_fallback(base_id, name, leftover))
        return entities

    if len(dpts) == 1:
        (key,) = dpts
        if key == _DATE_DPT:
            return [_build_date(base_id, name, dpts[key])]
        roles = dpts[key]
        if key in _TRIGGER_DPTS and "command" in roles and "status" not in roles:
            return [_build_button(base_id, name, roles["command"])]

    # A command GA and its status GA sometimes use different DPT-1
    # sub-types (e.g. command DPST-1-10 "start", status DPST-1-1
    # "switch") - grouped separately by (dpt_main, dpt_sub) above, but
    # still the same physical switch. Verified against the reference
    # project ("Audio Play/Pause": command 1.010, status 1.001). Merge
    # whenever every key here is DPT main-type 1 and there's at most one
    # command and one status total - DPT 1.x has no valid `sensor.type`
    # (see _DPT_LABELS), so this is the only way such a pair can become
    # valid HA KNX config at all, not just a cosmetic grouping choice.
    if switch_keys == set(dpts):
        commands = [roles["command"] for roles in dpts.values() if "command" in roles]
        statuses = [roles["status"] for roles in dpts.values() if "status" in roles]
        if len(commands) <= 1 and len(statuses) <= 1:
            switch_config: dict[str, str] = {}
            if commands:
                switch_config["address"] = commands[0].address
            if statuses:
                switch_config["state_address"] = statuses[0].address
            domain = "switch" if commands else "binary_sensor"
            return [HaEntity(domain=domain, unique_id=base_id, name=name, config=switch_config)]

    return _sensor_fallback(base_id, name, dpts)


def _build_date(base_id: str, name: str, roles: dict[str, GroupAddress]) -> HaEntity:
    """DPST-11-1 as the KNX `date` platform: `address` is required (where
    new values are sent), `state_address` optional (read back from the
    bus) - per the official documentation. Falls back to using a
    status-only group address as `address` if that's the only one
    available, since the platform requires it."""
    config: dict[str, str] = {}
    if "command" in roles:
        config["address"] = roles["command"].address
        if "status" in roles:
            config["state_address"] = roles["status"].address
    else:
        config["address"] = roles["status"].address
    return HaEntity(domain="date", unique_id=base_id, name=name, config=config)


def _build_button(base_id: str, name: str, ga: GroupAddress) -> HaEntity:
    """DPST-1-7 "step", command-only: the KNX `button` platform. `payload`
    defaults to `1` (per the official documentation) - a single press
    sends the "increase" direction, matching how this group address is
    already used elsewhere (e.g. media_next_track)."""
    return HaEntity(domain="button", unique_id=base_id, name=name, config={"address": ga.address})


def _light_config(
    dpts: dict[tuple[int, int | None], dict[str, GroupAddress]],
    light_keys: set[tuple[int, int | None]],
    switch_keys: set[tuple[int, int | None]],
) -> dict[str, str]:
    config: dict[str, str] = {}
    for key in switch_keys:
        roles = dpts[key]
        if "command" in roles:
            config["address"] = roles["command"].address
        if "status" in roles:
            config["state_address"] = roles["status"].address
    for key in light_keys:
        roles = dpts[key]
        prefix = "brightness" if key == (5, 1) else "color_temperature"
        if "command" in roles:
            config[f"{prefix}_address"] = roles["command"].address
        if "status" in roles:
            config[f"{prefix}_state_address"] = roles["status"].address
    return config


def _sensor_fallback(
    base_id: str, name: str, dpts: dict[tuple[int, int | None], dict[str, GroupAddress]]
) -> list[HaEntity]:
    """One sensor per remaining (dpt_main, dpt_sub) group, so nothing is
    silently dropped. `unique_id` is always suffixed - this can run
    alongside an already-built light entity sharing `base_id`."""
    entities = []
    multiple = len(dpts) > 1
    for (main, sub), roles in dpts.items():
        ga = roles.get("status") or roles.get("command")
        if ga is None:
            continue
        numeric_label = f"{main}.{sub}" if sub is not None else str(main)
        dpt_label = _DPT_LABELS.get((main, sub)) or numeric_label
        entities.append(
            HaEntity(
                domain="sensor",
                unique_id=f"{base_id}_{_slugify(dpt_label)}",
                name=f"{name} {dpt_label}" if multiple else name,
                config={"type": dpt_label, "state_address": ga.address},
            )
        )
    return entities

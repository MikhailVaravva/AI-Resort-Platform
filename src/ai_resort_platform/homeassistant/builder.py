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
    HaAutomation,
    HaEntity,
    HaMediaPlayer,
    HaScene,
    HaScript,
    HaTemplateSensor,
    HomeAssistantPackage,
    RoomArea,
)

_SLUG_INVALID = re.compile(r"[^a-z0-9]+")
# A bare KNX group address, e.g. "1/1/202" - distinguishes real address
# values in an HaEntity/HaScene's config from non-address strings (e.g.
# `type: "temperature"`, `entity_category: "config"`) sharing the same
# plain dict, without hardcoding which config keys are addresses.
_GA_ADDRESS = re.compile(r"^\d+/\d+/\d+$")
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


def _media_player_entity_id(media_player: HaMediaPlayer) -> str:
    """Same reasoning as _entity_id, for the `universal` platform's own
    `media_player` entity - HA derives entity_id from `name`."""
    return f"media_player.{_slugify(media_player.name)}"


def _is_internal(entity: HaEntity) -> bool:
    """`entity_category` (see _apply_audio_module_semantics) marks an
    entity as internal KNX plumbing, not something a resident should see
    in a domain list or a room's view."""
    return "entity_category" in entity.config


def _build_areas(
    project: ETSProject,
    group_addresses: tuple[GroupAddress, ...],
    entities: tuple[HaEntity, ...],
    scenes: tuple[HaScene, ...],
) -> tuple[RoomArea, ...]:
    """Groups entity_ids by the ETS room their underlying group address is
    wired to - NOT real Home Assistant Areas (see HomeAssistantPackage),
    only used to organize build_dashboard's per-room views. Each
    resulting RoomArea also carries that room's own Building/Floor names
    (ets.rooms.Room.building/.floor - already the resolved result of
    ETS's Building -> BuildingPart -> Floor -> Room location tree, not
    re-derived here), so build_dashboard can order/label views by that
    hierarchy instead of by room name alone.

    A group address belongs to a room if it's linked to a communication
    object of a device that room's own `Room.device_ids` lists (the same
    device/CO/GA linkage build_audio_module_package already uses to scope
    a device's group addresses) - not by name-matching. A group address
    occasionally reaches devices in more than one room (KNX group
    addresses can fan out to several physical locations at once); such
    an entity is listed under every room it touches, rather than guessing
    a single "primary" one. Rooms are matched by `Room.id` throughout
    (not `Room.name`), since two rooms could in principle share a
    display name but never an id.

    Only `entities` and `scenes` are placed - each has a real group
    address of its own. `media_players`/`template_sensors`/`scripts` are
    composites built from other entities (see _build_audio_media_player),
    not wired to one physical KNX address, so there is nothing here to
    place them by.
    """
    device_co_ids = {d.individual_address: set(d.communication_object_ids) for d in project.devices}
    address_rooms: dict[str, set[str]] = {}
    for room in project.rooms:
        room_co_ids: set[str] = set()
        for device_id in room.device_ids:
            room_co_ids |= device_co_ids.get(device_id, set())
        for ga in group_addresses:
            if room_co_ids & set(ga.communication_object_ids):
                address_rooms.setdefault(ga.address, set()).add(room.id)

    by_room_id: dict[str, list[str]] = {}

    def place(entity_id: str, addresses: list[str]) -> None:
        room_ids: set[str] = set()
        for address in addresses:
            if _GA_ADDRESS.match(address):
                room_ids |= address_rooms.get(address, set())
        for room_id in room_ids:
            by_room_id.setdefault(room_id, []).append(entity_id)

    for entity in entities:
        if not _is_internal(entity):
            place(_entity_id(entity), list(entity.config.values()))
    for scene in scenes:
        place(f"scene.{_slugify(scene.name)}", [scene.address])

    return tuple(
        RoomArea(
            room_id=room.id,
            room=room.name,
            floor=room.floor,
            building=room.building,
            entity_ids=tuple(by_room_id[room.id]),
        )
        for room in project.rooms
        if room.id in by_room_id
    )


def build_package(
    project: ETSProject,
    *,
    welcome_playlist: int | None = None,
    background_playlist: int | None = None,
    welcome_volume_percent: float = 50,
    welcome_to_background_delay: str = "00:05:00",
) -> HomeAssistantPackage:
    """Build one HomeAssistantPackage covering every group address in `project`.

    unique_ids are scoped to the villa's room name (e.g. "Villa A1"), not the
    whole project name ("Hot Stone VILLA") - matching the old DigitalTwin
    builder, which scoped ids per-villa/per-room. Falls back to the project
    name if the project has no rooms.

    `welcome_playlist`/`background_playlist` opt into the standard
    check-in automation (see _build_welcome_automation) - omitted by
    default since there is nothing in ETSProject to derive them from; the
    automation is simply not built without both.
    """
    return _build_package(
        project,
        project.group_addresses,
        welcome_playlist=welcome_playlist,
        background_playlist=background_playlist,
        welcome_volume_percent=welcome_volume_percent,
        welcome_to_background_delay=welcome_to_background_delay,
    )


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
    project: ETSProject,
    group_addresses: tuple[GroupAddress, ...],
    *,
    welcome_playlist: int | None = None,
    background_playlist: int | None = None,
    welcome_volume_percent: float = 50,
    welcome_to_background_delay: str = "00:05:00",
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
    volume_level_sensor = _build_volume_level_sensor(slug, villa_name, tuple(entities))
    welcome_automation = _build_welcome_automation(
        slug,
        villa_name,
        tuple(entities),
        media_player,
        welcome_playlist=welcome_playlist,
        background_playlist=background_playlist,
        volume_percent=welcome_volume_percent,
        background_delay=welcome_to_background_delay,
    )
    departure_automation = _build_departure_automation(slug, villa_name, tuple(entities))
    areas = _build_areas(project, group_addresses, tuple(entities), scenes)

    return HomeAssistantPackage(
        villa_id=project.guid,
        villa_name=villa_name,
        entities=tuple(entities),
        scenes=scenes,
        scripts=scripts,
        media_players=(media_player,) if media_player else (),
        template_sensors=(volume_level_sensor,) if volume_level_sensor else (),
        automations=tuple(a for a in (welcome_automation, departure_automation) if a is not None),
        areas=areas,
    )


def _apply_audio_module_semantics(entities: tuple[HaEntity, ...]) -> tuple[HaEntity, ...]:
    """Two of the audio module's entities need a different domain than the
    generic classification gives them, based on their real KNX behaviour
    (verified against the reference project's communication objects, not
    just DPT numbers) - scoped to exactly these two, by name, so nothing
    else's classification changes (e.g. the DMX channels have the same
    structural shape - a single command-role DPT 5 key - but are out of
    scope here):

    - "Audio Absolut volume" (1/1/211, DPT 5.001) has no DPT-1.x switch of
      its own, so the generic pipeline exposes it as a read-only `sensor`
      (see _build_entities_for) - but its communication object is
      genuinely read/write (verified), a continuously controllable level
      with nothing to switch, not a status readout. Rebuilt as a `light`
      instead: `address` is required by that platform regardless, so it
      borrows "Audio Power"'s (the same physical module, already a
      command target) to satisfy it, while `brightness_address` is the
      real, writable volume value - the point of this change is to make
      volume actually controllable, not just observable. "Audio Volume"
      (1/1/212) is verified real ETS data too - the status counterpart of
      1/1/211, just not name-paired with it by the generic pipeline
      ("Audio Absolut volume" vs "Audio Volume" don't strip to the same
      base name) - folded in here as `brightness_state_address` instead
      of staying its own separate, redundant sensor. The light is given
      `entity_category: config` (a documented common KNX option, see
      home-assistant.io/integrations/knx/): the media_player's own
      volume slider (backed by this light, see
      _build_audio_media_player/_build_volume_level_sensor) is the
      intended user-facing control, so this stays a purely internal
      KNX implementation detail - HA's default dashboard/area cards
      exclude `config`/`diagnostic` entities, and build_dashboard does
      the same for our own generated dashboard (see there), so a
      "Volume" light never shows up in a "Lights" list next to real ones.
    - "Audio Playlist Select" (1/1/239, DPT 5, no sub-type) is wired to
      the exact same communication object as "Audio Absolut volume"
      (verified: identical read/write/communication/transmit flags) - a
      real, writable command target, not a status readout - so it
      becomes a `number` (writable) instead of a read-only `sensor`.
    - "Audio Next/Prev" (1/1/226, DPST-1-7 "step") already becomes a
      `button` via the generic pipeline (see _TRIGGER_DPTS), sending the
      default payload 1 - "next", per the official BAB AUDIOMODULE V3
      documentation ("Media Server - Title +/-", EIS1: 0=previous track,
      1=next track). That same group address's other documented value
      (0, "previous") was never reachable from a single fixed-payload
      button, so a second `button` entity, "Audio Previous", is added
      here targeting the identical address with `payload: 0` - no new
      group address, just the other half of the one BAB already
      documents on 1/1/226. The original "Audio Next/Prev" entity is
      left completely unchanged.

    Every address used here (1/1/202, 1/1/211, 1/1/212, 1/1/226,
    1/1/239) is a verified, real group address in the reference project -
    none invented.
    """
    by_name = {e.name: e for e in entities}
    power = by_name.get("Audio Power")
    if power is None:
        return entities
    volume_status = by_name.get("Audio Volume")

    result = []
    for entity in entities:
        if entity.name == "Audio Next/Prev" and entity.domain == "button":
            result.append(entity)
            result.append(
                HaEntity(
                    domain="button",
                    unique_id=f"{entity.unique_id}_previous",
                    name="Audio Previous",
                    config={"address": entity.config["address"], "payload": "0"},
                )
            )
        elif entity.name == "Audio Absolut volume" and entity.domain == "sensor":
            config = {
                "address": power.config["address"],
                "brightness_address": entity.config["state_address"],
                "entity_category": "config",
            }
            if volume_status is not None:
                config["brightness_state_address"] = volume_status.config["state_address"]
            result.append(
                HaEntity(
                    domain="light", unique_id=entity.unique_id, name=entity.name, config=config
                )
            )
        elif entity.name == "Audio Volume" and volume_status is not None:
            continue  # folded into "Audio Absolut volume" above, see there
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
    # "Audio Power Convert" (1/1/240 command, 1/1/241 status) is the real
    # Power ON/OFF function - confirmed by the user against the BAB Audio
    # Module's own documentation, distinct from "Audio Power" (1/1/202/
    # 1/1/203), which is Standby, a separate function. Power's own
    # communication objects live only on the KNX Smart Touch S3 touch
    # panel (device 1.1.4), not the Audio Module itself (1.1.5) - verified
    # against the reference project - so build_audio_module_package's
    # device-CO-based scoping (see there) never includes it; the
    # media_player this function builds for that narrower package will
    # be None as a result, same as if any other required entity were
    # missing. "Audio Power" (Standby) is deliberately NOT referenced
    # anywhere in this function: it stays its own independent switch,
    # unaffected by any media_player command (turn_on/turn_off/
    # state_template all use Power, never Standby).
    power = by_name.get("Audio Power Convert")
    play_pause = by_name.get("Audio Play/Pause")
    next_track = by_name.get("Audio Next/Prev")
    # "Audio Previous" (see _apply_audio_module_semantics) is the other
    # half of the same BAB-documented group address as "Audio Next/Prev"
    # (1/1/226, EIS1: 0=previous,1=next) - optional here (not one of the
    # required entities below) since older packages built before this
    # entity existed still have a fully working media_player without it,
    # just without a previous-track command.
    previous_track = by_name.get("Audio Previous")
    volume = by_name.get("Audio Absolut volume")
    mute = by_name.get("Audio Mute")
    title = by_name.get("Audio Track name")
    playlist = by_name.get("Audio Playlist Select")
    if not (power and play_pause and next_track and volume and mute and title and playlist):
        return None

    # Built by _build_volume_level_sensor, alongside this media_player -
    # same deterministic name, so both agree on this entity_id without
    # either one having to be passed into the other.
    volume_level_entity_id = f"sensor.{slug}_audio_volume"

    def service(
        action: str, target: HaEntity, data: dict[str, object] | None = None
    ) -> dict[str, object]:
        call: dict[str, object] = {"action": action, "target": {"entity_id": _entity_id(target)}}
        if data:
            call["data"] = data
        return call

    commands: dict[str, dict[str, object]] = {
        "turn_on": service("switch.turn_on", power),
        "turn_off": service("switch.turn_off", power),
        "media_play": service("switch.turn_on", play_pause),
        "media_pause": service("switch.turn_off", play_pause),
        # DPST-1-7 "step" (see _TRIGGER_DPTS): a momentary pulse, not a
        # persistent state - modeled as `button` entities, pressed via
        # the core button.press service. Per the official BAB
        # AUDIOMODULE V3 documentation ("Media Server - Title +/-",
        # EIS1), value 1 (this button's payload) means "next".
        "media_next_track": service("button.press", next_track),
        "volume_mute": service("switch.toggle", mute),
    }
    if previous_track is not None:
        # Same group address as media_next_track (1/1/226), payload 0 -
        # BAB's documented "previous" value for this object, see
        # _apply_audio_module_semantics.
        commands["media_previous_track"] = service("button.press", previous_track)
    # "Audio Absolut volume" is rebuilt as a `light` (see
    # _apply_audio_module_semantics) specifically so this can be a
    # real write, not just a display - light.turn_on's brightness_pct
    # (0-100) is HA's 0.0-1.0 volume_level * 100, clamped to [0, 100]
    # in case a caller ever passes something out of range (KNX DPT
    # 5.001 itself only accepts 0-100%).
    commands["volume_set"] = service(
        "light.turn_on",
        volume,
        {"brightness_pct": "{{ [0, [100, (volume_level * 100) | round(0)] | min] | max }}"},
    )
    # "Audio Playlist Select" is rebuilt as a `number` (see
    # _apply_audio_module_semantics) so this can write the requested
    # source through, not just display the current one. There is no
    # known name<->index mapping in the source project, so `source` is
    # expected to be that raw numeric index as a string, not a
    # friendly playlist name.
    commands["select_source"] = service("number.set_value", playlist, {"value": "{{ source }}"})

    return HaMediaPlayer(
        unique_id=f"{slug}_audio_module",
        name=f"{villa_name} Audio",
        commands=commands,
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
        #
        # The not-playing state is `paused`, not `idle`, and the
        # difference is visible in the UI rather than cosmetic. Home
        # Assistant's frontend renders the previous/next-track buttons
        # only for `playing` and `paused`:
        #
        #     ("playing"===o||"paused"===o||n) && supportsFeature(t,16)
        #         && s.push({action:"media_previous_track"})
        #
        # so an `idle` player advertising NEXT_TRACK/PREVIOUS_TRACK (which
        # this one does - the `universal` platform derives both flags from
        # the commands above) still shows a lone play button and no
        # transport controls.
        #
        # `paused` is also the more accurate of the two: HA defines `idle`
        # as on-but-nothing-loaded, while this module always has a
        # playlist loaded and resumes it on play - Play/Pause being off is
        # exactly a pause, which is what the underlying group address
        # (1/1/222, EIS1 play/pause) means.
        state_template=(
            f"{{% if is_state('{_entity_id(power)}', 'off') %}}\n"
            "  off\n"
            f"{{% elif is_state('{_entity_id(play_pause)}', 'on') %}}\n"
            "  playing\n"
            "{% else %}\n"
            "  paused\n"
            "{% endif %}"
        ),
        attributes={
            "is_volume_muted": _entity_id(mute),
            # KNX `light.brightness` is HA's normalized 0-255 scale (xknx
            # converts the DPT 5.001 0-100% value for us), not the 0.0-1.0
            # `volume_level` expects, and the `universal` platform's
            # `attributes:` can't convert it (bare entity/attribute
            # reference only, no templates) - so this reads the 0.0-1.0
            # value from a small `template` sensor instead
            # (_build_volume_level_sensor), which does support templating.
            "volume_level": volume_level_entity_id,
            "media_title": _entity_id(title),
            # No `source_list` for the same reason: the project has no
            # catalog of playlist names, only this numeric index.
            "source": _entity_id(playlist),
        },
    )


# Universal Media Player expects volume_level in the range 0.0..1.0.
# KNX brightness is 0..255, therefore a template sensor is used for
# normalization. Universal Media Player attributes do not support Jinja
# templates directly.
def _build_volume_level_sensor(
    slug: str, villa_name: str, entities: tuple[HaEntity, ...]
) -> HaTemplateSensor | None:
    """A `template` sensor converting "Audio Absolut volume" (rebuilt as a
    `light`, see _apply_audio_module_semantics) from HA's normalized
    0-255 `brightness` scale to the 0.0-1.0 `_build_audio_media_player`'s
    `volume_level` attribute needs - the `universal` platform's
    `attributes:` has no templating of its own to do this conversion
    itself (see there). Clamped to [0.0, 1.0] and defaults to 0 while the
    light's brightness is unknown/unavailable, so the template never
    errors. Returns None if this villa has no "Audio Absolut volume"
    entity at all (matches _build_audio_media_player's own check).
    """
    volume = next((e for e in entities if e.name == "Audio Absolut volume"), None)
    if volume is None:
        return None

    light_entity_id = _entity_id(volume)
    return HaTemplateSensor(
        unique_id=f"{slug}_audio_volume",
        name=f"{villa_name} Audio Volume",
        state=(
            "{{ [0.0, [1.0, "
            f"(state_attr('{light_entity_id}', 'brightness') | float(0)) / 255"
            "] | min] | max }}"
        ),
    )


def _build_welcome_automation(
    slug: str,
    villa_name: str,
    entities: tuple[HaEntity, ...],
    media_player: HaMediaPlayer | None,
    *,
    welcome_playlist: int | None,
    background_playlist: int | None,
    volume_percent: float,
    background_delay: str,
) -> HaAutomation | None:
    """Standard check-in automation for any villa that has both a "Guest"
    switch and an audio media_player (see _build_audio_media_player) -
    matched by name, same as every other generator here; nothing here is
    specific to any one villa.

    Trigger: "Guest" turns on. Actions: power the audio module on, select
    the welcome playlist, start playback, set the welcome volume, then
    after a delay switch to the background playlist.

    `welcome_playlist`/`background_playlist` are raw numeric indices, not
    names: "Audio Playlist Select" (see _apply_audio_module_semantics) is
    a plain writable number with no name<->index catalog anywhere in
    ETSProject - there is nothing here that could resolve a name like
    "Welcome" to the right value for a given installation, so the caller
    must supply the real index. Returns None if the villa has no "Guest"
    switch, no audio media_player, or the playlist indices weren't given
    at all (see build_package).
    """
    if media_player is None or welcome_playlist is None or background_playlist is None:
        return None
    guest = next((e for e in entities if e.name == "Guest" and e.domain == "switch"), None)
    if guest is None:
        return None

    mp_entity_id = _media_player_entity_id(media_player)

    def call(action: str, data: dict[str, object] | None = None) -> dict[str, object]:
        step: dict[str, object] = {"action": action, "target": {"entity_id": mp_entity_id}}
        if data:
            step["data"] = data
        return step

    return HaAutomation(
        unique_id=f"{slug}_welcome",
        name=f"{villa_name} Welcome",
        triggers=({"trigger": "state", "entity_id": _entity_id(guest), "to": "on"},),
        actions=(
            call("media_player.turn_on"),
            call("media_player.select_source", {"source": str(welcome_playlist)}),
            call("media_player.media_play"),
            call("media_player.volume_set", {"volume_level": volume_percent / 100}),
            {"delay": background_delay},
            call("media_player.select_source", {"source": str(background_playlist)}),
        ),
    )


def _build_departure_automation(
    slug: str, villa_name: str, entities: tuple[HaEntity, ...]
) -> HaAutomation | None:
    """Check-out automation: when "Guest" turns off, put the Audio Module
    into Standby - the real BAB "Standby" function (1/1/202/1/1/203, see
    the BAB capability matrix), NOT "Power" (1/1/240/1/1/241): the two are
    deliberately kept separate everywhere else in this generator (see
    _build_audio_media_player), and this automation targets the Standby
    switch directly rather than going through the media_player, since
    Standby was never wired into the media_player's own commands.

    Per the official BAB AUDIOMODULE V3 documentation, Standby's command
    telegram values are 0=Power off, 1=Power on - exactly the KNX
    `switch` platform's own on/off semantics, so a plain `switch.turn_off`
    on "Audio Power" is the correct, direct way to send it.

    Matched by name, same as every other generator here - nothing here is
    specific to any one villa. Returns None if the villa has no "Guest"
    switch or no "Audio Power" (Standby) switch.
    """
    guest = next((e for e in entities if e.name == "Guest" and e.domain == "switch"), None)
    standby = next((e for e in entities if e.name == "Audio Power" and e.domain == "switch"), None)
    if guest is None or standby is None:
        return None

    return HaAutomation(
        unique_id=f"{slug}_departure",
        name=f"{villa_name} Departure",
        triggers=({"trigger": "state", "entity_id": _entity_id(guest), "to": "off"},),
        actions=(
            {
                "action": "switch.turn_off",
                "target": {"entity_id": _entity_id(standby)},
            },
        ),
    )


def build_dashboard(package: HomeAssistantPackage) -> Dashboard:
    """Build an overview dashboard for a villa's package: one villa-wide
    view (domain cards, scenes, scripts, media_player), plus one
    additional view per ETS room (see _build_areas/HomeAssistantPackage.
    areas) - the closest equivalent to a per-Area dashboard achievable at
    all, since Home Assistant has no YAML mechanism to create real Areas.

    Room views are ordered by (building, floor, room) - reflecting ETS's
    Building -> BuildingPart -> Floor -> Room location tree in the tab
    order, since Lovelace views are always a flat tab list with no
    nesting of their own; there is no separate "Building"/"Floor" view
    or grouping beyond that ordering. Each view (villa-wide and every
    room) gets its own unique `view_id` (see DashboardView), so a room
    that happens to share its display name with the villa itself (this
    project's own "Villa A1" is both) never collides with the villa-wide
    view - Lovelace disambiguates views by `path`, not by `title`.

    Entities with `entity_category` set (e.g. "Audio Absolut volume", see
    _apply_audio_module_semantics) are internal KNX implementation
    details, not something a resident should see in a "Lights"/etc. list
    - mirrors how HA's own default dashboard/area cards already exclude
    `config`/`diagnostic` entities. _build_areas already excludes them
    from `package.areas` too, so the per-room views need no separate
    filtering here.
    """
    cards = []
    for domain, title in _DASHBOARD_SECTIONS:
        entity_ids = tuple(
            _entity_id(e) for e in package.entities if e.domain == domain and not _is_internal(e)
        )
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
                entity=_media_player_entity_id(media_player),
            )
        )

    views = [
        DashboardView(title=package.villa_name, view_id="overview", cards=tuple(cards)),
    ]
    for area in sorted(package.areas, key=lambda a: (a.building or "", a.floor or "", a.room)):
        views.append(
            DashboardView(
                title=area.room,
                view_id=_slugify(f"room-{area.room_id}"),
                cards=(DashboardCard(title=area.room, entities=area.entity_ids),),
            )
        )
    return Dashboard(villa_id=package.villa_id, title=package.villa_name, views=tuple(views))


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

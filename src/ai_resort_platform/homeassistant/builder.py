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

# Old sensor-fallback `type`/unique_id labels, from the JSON-LD builder's
# `datapoint_type` semantic strings - verified against every real group
# address in the reference project (ground truth: JsonLdImporter's
# ProjectModel.group_addresses[*].datapoint_type for reference_villa.jsonld).
# Kept only for pairs the old builder actually preserved as a sensor;
# anything not listed here falls back to the numeric "{main}.{sub}" label
# the new builder already used (there's no old value to preserve for it).
_DPT_LABELS: dict[tuple[int, int | None], str] = {
    (1, 1): "switch",
    (1, 3): "enable",
    (1, 7): "step",
    (1, 9): "openClose",
    (1, 10): "start",
    (5, 1): "scaling",
    (5, 10): "value1Ucount",
    (5, None): "major.5.x",
    (7, 600): "absoluteColourTemperature",
    (9, 1): "valueTemp",
    (9, 7): "valueHumidity",
    (11, 1): "date",
    (16, 1): "string88591",
    (18, 1): "sceneControl",
}

_DASHBOARD_SECTIONS = (
    ("light", "Lights"),
    ("cover", "Covers"),
    ("switch", "Switches"),
    ("binary_sensor", "Binary Sensors"),
    ("sensor", "Sensors"),
)


def _slugify(text: str) -> str:
    slug = _SLUG_INVALID.sub("_", text.lower()).strip("_")
    return slug or "entity"


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

    return HomeAssistantPackage(
        villa_id=project.guid,
        villa_name=villa_name,
        entities=tuple(entities),
        scenes=scenes,
        scripts=scripts,
    )


def build_dashboard(package: HomeAssistantPackage) -> Dashboard:
    """Build a one-view overview dashboard for a villa's package."""
    cards = []
    for domain, title in _DASHBOARD_SECTIONS:
        entity_ids = tuple(
            f"{domain}.{e.unique_id}" for e in package.entities if e.domain == domain
        )
        if entity_ids:
            cards.append(DashboardCard(title=title, entities=entity_ids))

    if package.scenes:
        cards.append(
            DashboardCard(
                title="Scenes", entities=tuple(f"scene.{s.unique_id}" for s in package.scenes)
            )
        )
    if package.scripts:
        cards.append(
            DashboardCard(
                title="Scripts", entities=tuple(f"script.{s.unique_id}" for s in package.scripts)
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

    if light_keys:
        switch_keys = {k for k in dpts if k[0] == _SWITCH_DPT_MAIN}
        used_keys = light_keys | switch_keys
        config = _light_config(dpts, light_keys, switch_keys)
        entities = [HaEntity(domain="light", unique_id=base_id, name=name, config=config)]
        leftover = {k: v for k, v in dpts.items() if k not in used_keys}
        entities.extend(_sensor_fallback(base_id, name, leftover))
        return entities

    if len(dpts) == 1:
        key, roles = next(iter(dpts.items()))
        if key[0] == _SWITCH_DPT_MAIN:
            if "command" in roles:
                config = {"address": roles["command"].address}
                if "status" in roles:
                    config["state_address"] = roles["status"].address
                return [HaEntity(domain="switch", unique_id=base_id, name=name, config=config)]
            return [
                HaEntity(
                    domain="binary_sensor",
                    unique_id=base_id,
                    name=name,
                    config={"state_address": roles["status"].address},
                )
            ]

    return _sensor_fallback(base_id, name, dpts)


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

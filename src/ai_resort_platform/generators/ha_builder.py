import re

from ai_resort_platform.digital_twin.models import Capability, Entity, Resort, Scene, Villa
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
_COVER_KEYWORDS = ("curtain", "cover", "blind", "shutter")
# Presence of either of these is what makes an Entity a light - "switch" alone
# does not (a plain on/off Entity is a `switch`, not a light with no analog
# control). Both kinds are still folded into the light config when present
# alongside brightness/colour temperature.
_LIGHT_TRIGGER_KINDS = {"scaling", "absoluteColourTemperature"}
_LIGHT_CONSUMED_KINDS = _LIGHT_TRIGGER_KINDS | {"switch"}

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


def build_resort_packages(resort: Resort) -> tuple[HomeAssistantPackage, ...]:
    return tuple(build_package(villa) for villa in resort.villas)


def build_package(villa: Villa) -> HomeAssistantPackage:
    """Build a HomeAssistantPackage for one villa - one package per villa."""
    villa_slug = _slugify(villa.name)
    cover_source, remaining = _extract_cover_entities(villa.entities)

    ha_entities: list[HaEntity] = []
    if cover_source:
        ha_entities.append(_build_cover(villa_slug, cover_source))
    for entity in remaining:
        ha_entities.extend(_build_entities_for(villa_slug, entity))

    ha_scenes = tuple(
        scene for scene in (_build_scene(villa_slug, s) for s in villa.scenes) if scene is not None
    )
    ha_scripts = tuple(
        script
        for script in (_build_scene_script(villa_slug, s) for s in villa.scenes)
        if script is not None
    )

    return HomeAssistantPackage(
        villa_id=villa.id,
        villa_name=villa.name,
        entities=tuple(ha_entities),
        scenes=ha_scenes,
        scripts=ha_scripts,
        automations=(),
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


def _extract_cover_entities(entities: tuple[Entity, ...]) -> tuple[list[Entity], list[Entity]]:
    """Pull every Entity whose name suggests a cover into one group.

    digital_twin's Entity builder deliberately doesn't merge these (see
    digital_twin/builder.py) - a real cover needs move/stop/position
    combined into ONE Home Assistant entity, so that merge happens here,
    scoped to HA generation only.
    """
    cover_ids = {
        entity.id
        for entity in entities
        if any(keyword in entity.name.lower() for keyword in _COVER_KEYWORDS)
    }
    cover_entities = [e for e in entities if e.id in cover_ids]
    remaining = [e for e in entities if e.id not in cover_ids]
    return cover_entities, remaining


def _build_cover(villa_slug: str, cover_entities: list[Entity]) -> HaEntity:
    config: dict[str, str] = {}
    for entity in cover_entities:
        for capability in entity.capabilities:
            if capability.kind == "openClose" and capability.command_group_address:
                config["move_long_address"] = capability.command_group_address
            elif capability.kind == "step" and capability.command_group_address:
                config["stop_address"] = capability.command_group_address
            elif capability.kind == "scaling":
                if capability.command_group_address:
                    config["position_address"] = capability.command_group_address
                if capability.status_group_address:
                    config["position_state_address"] = capability.status_group_address

    name = next(
        keyword for keyword in _COVER_KEYWORDS if keyword in cover_entities[0].name.lower()
    ).capitalize()
    unique_id = f"{villa_slug}_{_slugify(name)}"
    return HaEntity(domain="cover", unique_id=unique_id, name=name, config=config)


def _build_entities_for(villa_slug: str, entity: Entity) -> list[HaEntity]:
    kinds = {c.kind for c in entity.capabilities}
    base_id = f"{villa_slug}_{_slugify(entity.name)}"

    if kinds & _LIGHT_TRIGGER_KINDS:
        light_capabilities = [c for c in entity.capabilities if c.kind in _LIGHT_CONSUMED_KINDS]
        leftover = [c for c in entity.capabilities if c.kind not in _LIGHT_CONSUMED_KINDS]
        entities = [
            HaEntity(
                domain="light",
                unique_id=base_id,
                name=entity.name,
                config=_light_config(light_capabilities),
            )
        ]
        entities.extend(_sensor_fallback(base_id, entity.name, leftover))
        return entities

    if kinds == {"switch"}:
        capability = entity.capabilities[0]
        if capability.command_group_address is not None:
            return [
                HaEntity(
                    domain="switch",
                    unique_id=base_id,
                    name=entity.name,
                    config=_switch_config(capability),
                )
            ]
        return [
            HaEntity(
                domain="binary_sensor",
                unique_id=base_id,
                name=entity.name,
                config=_binary_sensor_config(capability),
            )
        ]

    return _sensor_fallback(base_id, entity.name, list(entity.capabilities))


def _light_config(capabilities: list[Capability]) -> dict[str, str]:
    config: dict[str, str] = {}
    for capability in capabilities:
        if capability.kind == "switch":
            if capability.command_group_address:
                config["address"] = capability.command_group_address
            if capability.status_group_address:
                config["state_address"] = capability.status_group_address
        elif capability.kind == "scaling":
            if capability.command_group_address:
                config["brightness_address"] = capability.command_group_address
            if capability.status_group_address:
                config["brightness_state_address"] = capability.status_group_address
        elif capability.kind == "absoluteColourTemperature":
            if capability.command_group_address:
                config["color_temperature_address"] = capability.command_group_address
            if capability.status_group_address:
                config["color_temperature_state_address"] = capability.status_group_address
    return config


def _switch_config(capability: Capability) -> dict[str, str]:
    config: dict[str, str] = {}
    if capability.command_group_address is not None:
        config["address"] = capability.command_group_address
    if capability.status_group_address is not None:
        config["state_address"] = capability.status_group_address
    return config


def _binary_sensor_config(capability: Capability) -> dict[str, str]:
    config: dict[str, str] = {}
    if capability.status_group_address is not None:
        config["state_address"] = capability.status_group_address
    return config


def _sensor_config(capability: Capability) -> dict[str, str]:
    address = capability.status_group_address or capability.command_group_address
    config: dict[str, str] = {"type": capability.kind}
    if address is not None:
        config["state_address"] = address
    return config


def _sensor_fallback(base_id: str, name: str, capabilities: list[Capability]) -> list[HaEntity]:
    """One sensor per leftover capability, so nothing is ever silently dropped.

    `unique_id` is always suffixed by capability kind, even for a single
    capability: this can be called alongside an already-built light/cover
    entity sharing `base_id` (for capabilities that don't fit that domain),
    so a bare `base_id` here would risk colliding with it.
    """
    return [
        HaEntity(
            domain="sensor",
            unique_id=f"{base_id}_{_slugify(capability.kind)}",
            name=f"{name} {capability.kind}" if len(capabilities) > 1 else name,
            config=_sensor_config(capability),
        )
        for capability in capabilities
    ]


def _build_scene(villa_slug: str, scene: Scene) -> HaScene | None:
    if scene.number is None or scene.control_group_address is None:
        return None
    return HaScene(
        unique_id=f"{villa_slug}_scene_{scene.number}",
        name=f"Scene {scene.number}",
        address=scene.control_group_address,
        scene_number=scene.number,
    )


def _build_scene_script(villa_slug: str, scene: Scene) -> HaScript | None:
    if scene.number is None:
        return None
    scene_unique_id = f"{villa_slug}_scene_{scene.number}"
    return HaScript(
        unique_id=f"{villa_slug}_activate_scene_{scene.number}",
        name=f"Activate Scene {scene.number}",
        sequence=(
            {"service": "scene.turn_on", "target": {"entity_id": f"scene.{scene_unique_id}"}},
        ),
    )

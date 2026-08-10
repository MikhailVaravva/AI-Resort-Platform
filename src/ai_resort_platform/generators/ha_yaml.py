from pathlib import Path
from typing import Any

import yaml

from ai_resort_platform.generators.ha_package import (
    Dashboard,
    DashboardCard,
    DashboardView,
    HaEntity,
    HaMediaPlayer,
    HaSelect,
    HaTemplateSensor,
    HomeAssistantPackage,
)


def package_to_yaml(package: HomeAssistantPackage) -> str:
    """Serialize a HomeAssistantPackage as HA `packages/` YAML.

    Entity domains (light, cover, switch, sensor, binary_sensor) and `scene`
    (the KNX integration's own scene-recall platform, not HA's core `scene:`
    component) are all KNX-integration config and must live under a
    top-level `knx:` key, each as a plain list - that's the current KNX
    integration YAML schema; the old per-domain top-level keys
    (`switch:`/`light:`/...) are the pre-2021.12 platform-config schema and
    are not loaded by a current Home Assistant. `script` is a genuinely
    separate, core HA integration (calls `scene.turn_on`, not KNX-specific)
    and stays top-level, as a mapping keyed by unique_id per its own schema.

    `unique_id` is NOT emitted for any KNX entity or scene: verified against
    the official KNX integration documentation (home-assistant.io/
    integrations/knx/) - it's not a documented option for any KNX platform
    (switch/light/sensor/cover/binary_sensor/scene all list only `name`,
    `default_entity_id`, `entity_category` plus their own address fields).
    """
    data: dict[str, Any] = {}

    knx: dict[str, Any] = {}
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for entity in package.entities:
        by_domain.setdefault(entity.domain, []).append(_entity_dict(entity))
    knx.update(by_domain)

    if package.scenes:
        knx["scene"] = [
            {"name": scene.name, "address": scene.address, "scene_number": scene.scene_number}
            for scene in package.scenes
        ]

    if package.selects:
        knx["select"] = [_select_dict(select) for select in package.selects]

    if knx:
        data["knx"] = knx

    if package.scripts:
        data["script"] = {
            script.unique_id: {"alias": script.name, "sequence": list(script.sequence)}
            for script in package.scripts
        }

    if package.media_players:
        data["media_player"] = [_media_player_dict(mp) for mp in package.media_players]

    if package.template_sensors:
        # `template: - sensor: [...]` (home-assistant.io/integrations/
        # template/) - core HA config, not KNX-specific.
        data["template"] = [
            {"sensor": [_template_sensor_dict(s) for s in package.template_sensors]}
        ]

    if package.automations:
        # Plural `triggers`/`actions` - the current official automation
        # schema (home-assistant.io/docs/automation/yaml/), not the older
        # singular `trigger`/`action` keys.
        data["automation"] = [
            {
                "alias": automation.name,
                "triggers": list(automation.triggers),
                "actions": list(automation.actions),
            }
            for automation in package.automations
        ]

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _entity_dict(entity: HaEntity) -> dict[str, Any]:
    return {"name": entity.name, **entity.config}


def _select_dict(select: HaSelect) -> dict[str, Any]:
    """`knx: select:` (home-assistant.io/integrations/knx/#select)."""
    config: dict[str, Any] = {
        "name": select.name,
        "address": select.address,
        "payload_length": select.payload_length,
        "options": [{"option": option, "payload": payload} for option, payload in select.options],
    }
    if select.state_address:
        config["state_address"] = select.state_address
    return config


def _media_player_dict(media_player: HaMediaPlayer) -> dict[str, Any]:
    """`media_player: - platform: universal` (home-assistant.io/
    integrations/universal/) - not a KNX platform, so this is a core HA
    integration entry, not nested under `knx:`."""
    data: dict[str, Any] = {
        "platform": "universal",
        "name": media_player.name,
        "unique_id": media_player.unique_id,
    }
    if media_player.children:
        data["children"] = list(media_player.children)
    data["commands"] = media_player.commands
    data["attributes"] = media_player.attributes
    if media_player.state_template:
        data["state_template"] = media_player.state_template
    return data


def _template_sensor_dict(sensor: HaTemplateSensor) -> dict[str, Any]:
    return {"name": sensor.name, "unique_id": sensor.unique_id, "state": sensor.state}


def write_package(package: HomeAssistantPackage, path: Path) -> None:
    path.write_text(package_to_yaml(package), encoding="utf-8")


def dashboard_to_yaml(dashboard: Dashboard) -> str:
    data = {
        "title": dashboard.title,
        "views": [_view_dict(view) for view in dashboard.views],
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _view_dict(view: DashboardView) -> dict[str, Any]:
    data: dict[str, Any] = {"title": view.title}
    if view.view_id:
        # The documented Lovelace view field for a stable, unique
        # identifier (home-assistant.io/dashboards/views/) - lets two
        # views share the same `title` (see DashboardView) without
        # colliding.
        data["path"] = view.view_id
    data["cards"] = [_card_dict(card) for card in view.cards]
    return data


def _card_dict(card: DashboardCard) -> dict[str, Any]:
    if card.card_type == "media-control":
        return {"type": "media-control", "entity": card.entity}
    return {"type": "entities", "title": card.title, "entities": list(card.entities)}


def write_dashboard(dashboard: Dashboard, path: Path) -> None:
    path.write_text(dashboard_to_yaml(dashboard), encoding="utf-8")

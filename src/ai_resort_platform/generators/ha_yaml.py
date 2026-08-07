from pathlib import Path
from typing import Any

import yaml

from ai_resort_platform.generators.ha_package import Dashboard, HaEntity, HomeAssistantPackage


def package_to_yaml(package: HomeAssistantPackage) -> str:
    """Serialize a HomeAssistantPackage as HA `packages/` YAML.

    All entity domains (light, cover, switch, sensor, binary_sensor) are
    plain lists; `script` is a mapping keyed by unique_id, per HA's own
    schema for that domain.
    """
    data: dict[str, Any] = {}

    by_domain: dict[str, list[dict[str, Any]]] = {}
    for entity in package.entities:
        by_domain.setdefault(entity.domain, []).append(_entity_dict(entity))
    data.update(by_domain)

    if package.scenes:
        data["scene"] = [
            {
                "name": scene.name,
                "unique_id": scene.unique_id,
                "address": scene.address,
                "scene_number": scene.scene_number,
            }
            for scene in package.scenes
        ]

    if package.scripts:
        data["script"] = {
            script.unique_id: {"alias": script.name, "sequence": list(script.sequence)}
            for script in package.scripts
        }

    if package.automations:
        data["automation"] = [
            {
                "alias": automation.name,
                "trigger": list(automation.trigger),
                "action": list(automation.action),
            }
            for automation in package.automations
        ]

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _entity_dict(entity: HaEntity) -> dict[str, Any]:
    return {"name": entity.name, "unique_id": entity.unique_id, **entity.config}


def write_package(package: HomeAssistantPackage, path: Path) -> None:
    path.write_text(package_to_yaml(package), encoding="utf-8")


def dashboard_to_yaml(dashboard: Dashboard) -> str:
    data = {
        "title": dashboard.title,
        "views": [
            {
                "title": view.title,
                "cards": [
                    {"type": "entities", "title": card.title, "entities": list(card.entities)}
                    for card in view.cards
                ],
            }
            for view in dashboard.views
        ],
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def write_dashboard(dashboard: Dashboard, path: Path) -> None:
    path.write_text(dashboard_to_yaml(dashboard), encoding="utf-8")

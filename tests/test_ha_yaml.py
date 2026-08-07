import yaml

from ai_resort_platform.generators.ha_package import (
    Dashboard,
    DashboardCard,
    DashboardView,
    HaEntity,
    HaScene,
    HaScript,
    HomeAssistantPackage,
)
from ai_resort_platform.generators.ha_yaml import (
    dashboard_to_yaml,
    package_to_yaml,
    write_dashboard,
    write_package,
)


def _sample_package() -> HomeAssistantPackage:
    return HomeAssistantPackage(
        villa_id="v-1",
        villa_name="Villa X1",
        entities=(
            HaEntity(
                domain="light", unique_id="villa_x1_g1", name="G1", config={"address": "1/1/0"}
            ),
            HaEntity(
                domain="switch",
                unique_id="villa_x1_stone",
                name="Stone",
                config={"address": "1/1/20"},
            ),
        ),
        scenes=(
            HaScene(
                unique_id="villa_x1_scene_1", name="Scene 1", address="1/1/150", scene_number=1
            ),
        ),
        scripts=(
            HaScript(
                unique_id="villa_x1_activate_scene_1",
                name="Activate Scene 1",
                sequence=(
                    {"service": "scene.turn_on", "target": {"entity_id": "scene.villa_x1_scene_1"}},
                ),
            ),
        ),
    )


def test_package_to_yaml_groups_entities_by_domain():
    data = yaml.safe_load(package_to_yaml(_sample_package()))

    assert data["light"] == [{"name": "G1", "unique_id": "villa_x1_g1", "address": "1/1/0"}]
    assert data["switch"] == [{"name": "Stone", "unique_id": "villa_x1_stone", "address": "1/1/20"}]


def test_package_to_yaml_scene_is_a_list():
    data = yaml.safe_load(package_to_yaml(_sample_package()))

    assert data["scene"] == [
        {
            "name": "Scene 1",
            "unique_id": "villa_x1_scene_1",
            "address": "1/1/150",
            "scene_number": 1,
        }
    ]


def test_package_to_yaml_script_is_a_mapping_keyed_by_unique_id():
    """HA's own `script:` schema is a mapping, not a list - unlike every
    other domain here."""
    data = yaml.safe_load(package_to_yaml(_sample_package()))

    assert data["script"] == {
        "villa_x1_activate_scene_1": {
            "alias": "Activate Scene 1",
            "sequence": [
                {"service": "scene.turn_on", "target": {"entity_id": "scene.villa_x1_scene_1"}}
            ],
        }
    }


def test_package_to_yaml_omits_empty_sections():
    package = HomeAssistantPackage(villa_id="v-1", villa_name="Villa X1")

    data = yaml.safe_load(package_to_yaml(package))

    assert data == {}


def test_write_package_writes_valid_yaml_file(tmp_path):
    path = tmp_path / "villa_x1.yaml"

    write_package(_sample_package(), path)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "light" in data
    assert "switch" in data


def test_dashboard_to_yaml_structure():
    dashboard = Dashboard(
        villa_id="v-1",
        title="Villa X1",
        views=(
            DashboardView(
                title="Villa X1",
                cards=(DashboardCard(title="Lights", entities=("light.villa_x1_g1",)),),
            ),
        ),
    )

    data = yaml.safe_load(dashboard_to_yaml(dashboard))

    assert data["title"] == "Villa X1"
    assert data["views"][0]["title"] == "Villa X1"
    assert data["views"][0]["cards"][0] == {
        "type": "entities",
        "title": "Lights",
        "entities": ["light.villa_x1_g1"],
    }


def test_write_dashboard_writes_valid_yaml_file(tmp_path):
    dashboard = Dashboard(villa_id="v-1", title="Villa X1", views=())
    path = tmp_path / "villa_x1_dashboard.yaml"

    write_dashboard(dashboard, path)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["title"] == "Villa X1"

from ai_resort_platform.generators.ha_package import (
    Dashboard,
    DashboardCard,
    DashboardView,
    HaAutomation,
    HaEntity,
    HaScene,
    HaScript,
    HomeAssistantPackage,
)


def test_home_assistant_package_defaults_to_empty_collections():
    package = HomeAssistantPackage(villa_id="v-1", villa_name="Villa X1")

    assert package.entities == ()
    assert package.scenes == ()
    assert package.scripts == ()
    assert package.automations == ()


def test_ha_entity_config_defaults_to_empty_dict():
    entity = HaEntity(domain="switch", unique_id="villa_x1_test", name="Test")

    assert entity.config == {}


def test_package_holds_its_populated_collections():
    entity = HaEntity(domain="switch", unique_id="e-1", name="Test")
    scene = HaScene(unique_id="s-1", name="Scene 1", address="1/1/150", scene_number=1)
    script = HaScript(unique_id="sc-1", name="Activate Scene 1")
    automation = HaAutomation(unique_id="a-1", name="Unused")

    package = HomeAssistantPackage(
        villa_id="v-1",
        villa_name="Villa X1",
        entities=(entity,),
        scenes=(scene,),
        scripts=(script,),
        automations=(automation,),
    )

    assert package.entities == (entity,)
    assert package.scenes == (scene,)
    assert package.scripts == (script,)
    assert package.automations == (automation,)


def test_dashboard_holds_its_views():
    card = DashboardCard(title="Lights", entities=("light.villa_x1_g1",))
    view = DashboardView(title="Villa X1", cards=(card,))
    dashboard = Dashboard(villa_id="v-1", title="Villa X1", views=(view,))

    assert dashboard.views == (view,)
    assert dashboard.views[0].cards == (card,)

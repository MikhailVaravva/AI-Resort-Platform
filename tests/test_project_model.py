from ai_resort_platform.models.project import (
    CommunicationObject,
    Device,
    GroupAddress,
    ProjectModel,
    Room,
)


def test_project_model_defaults_to_empty_collections():
    project = ProjectModel(project_name="Empty")

    assert project.rooms == ()
    assert project.devices == ()
    assert project.group_addresses == ()
    assert project.communication_objects == ()
    assert project.datapoint_types == ()


def test_project_model_holds_populated_collections():
    room = Room(id="RM-1", name="Villa X1")
    device = Device(id="DI-1", name="Actuator", individual_address="1.1.1")
    ga = GroupAddress(id="GA-1", address="1/1/0", name="Light on/off")
    co = CommunicationObject(id="CO-1", name="Output 1")

    project = ProjectModel(
        project_name="Villa X",
        rooms=(room,),
        devices=(device,),
        group_addresses=(ga,),
        communication_objects=(co,),
        datapoint_types=("switch",),
    )

    assert project.rooms == (room,)
    assert project.devices == (device,)
    assert project.group_addresses == (ga,)
    assert project.communication_objects == (co,)
    assert project.datapoint_types == ("switch",)

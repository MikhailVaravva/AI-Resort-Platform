from pathlib import Path

import pytest

from ai_resort_platform.clone_engine.models import ValidationResult
from ai_resort_platform.generators.ets.models import (
    ProjectChangeSet,
    SerializedProject,
    WriteResult,
)
from ai_resort_platform.generators.ets.writer import (
    EtsSerializer,
    EtsWriter,
    IdentityStrategy,
    ProjectDiffer,
)
from ai_resort_platform.models.project import ProjectModel


@pytest.mark.parametrize(
    "abstract_class", [ProjectDiffer, IdentityStrategy, EtsSerializer, EtsWriter]
)
def test_ets_writer_interfaces_cannot_be_instantiated_directly(abstract_class):
    with pytest.raises(TypeError):
        abstract_class()


class _DummyDiffer(ProjectDiffer):
    def diff(self, original: ProjectModel, updated: ProjectModel) -> ProjectChangeSet:
        return ProjectChangeSet(base_project_guid="guid")


class _DummyIdentityStrategy(IdentityStrategy):
    def mint_id(self, object_kind: str, base_project: ProjectModel) -> str:
        return f"new-{object_kind}-id"


class _DummySerializer(EtsSerializer):
    def serialize(
        self, change_set: ProjectChangeSet, base_project: ProjectModel
    ) -> SerializedProject:
        return SerializedProject(change_set=change_set)


class _DummyWriter(EtsWriter):
    def write(
        self, base_project_path: Path, change_set: ProjectChangeSet, output_path: Path
    ) -> WriteResult:
        return WriteResult(validation=ValidationResult())


def test_concrete_differ_implements_contract():
    differ = _DummyDiffer()

    result = differ.diff(ProjectModel(project_name="A"), ProjectModel(project_name="B"))

    assert isinstance(result, ProjectChangeSet)


def test_concrete_identity_strategy_implements_contract():
    strategy = _DummyIdentityStrategy()

    assert strategy.mint_id("device", ProjectModel(project_name="A")) == "new-device-id"


def test_concrete_serializer_implements_contract():
    serializer = _DummySerializer()
    change_set = ProjectChangeSet(base_project_guid="guid")

    result = serializer.serialize(change_set, ProjectModel(project_name="A"))

    assert isinstance(result, SerializedProject)


def test_concrete_writer_implements_contract():
    writer = _DummyWriter()
    change_set = ProjectChangeSet(base_project_guid="guid")

    result = writer.write(Path("base.knxproj"), change_set, Path("out.knxproj"))

    assert isinstance(result, WriteResult)

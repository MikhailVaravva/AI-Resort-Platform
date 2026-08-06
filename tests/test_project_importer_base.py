from pathlib import Path

import pytest

from ai_resort_platform.models.project import ProjectModel
from ai_resort_platform.readers.base import ProjectImporter, ProjectImportError


class _DummyImporter(ProjectImporter):
    source_name = "dummy"

    def import_project(self, path: Path) -> ProjectModel:
        return ProjectModel(project_name="Dummy")


def test_project_importer_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        ProjectImporter()


def test_concrete_importer_implements_contract():
    importer = _DummyImporter()

    assert importer.source_name == "dummy"
    assert importer.import_project(Path("unused")).project_name == "Dummy"


def test_project_import_error_is_an_exception():
    error = ProjectImportError("bad file")

    assert isinstance(error, Exception)
    assert str(error) == "bad file"

import abc
from pathlib import Path

from ai_resort_platform.models.project import ProjectModel


class ProjectImportError(Exception):
    """Raised when a ProjectImporter cannot read its source file."""


class ProjectImporter(abc.ABC):
    """Contract every project source importer must implement.

    JSON-LD semantic export is the primary source; .knxproj is planned as an
    optional supplementary source for data the semantic export lacks. Both
    populate the same ProjectModel - nothing outside readers/ is allowed to
    know which source format produced a given project.
    """

    source_name: str

    @abc.abstractmethod
    def import_project(self, path: Path) -> ProjectModel:
        """Parse the file at `path` and return it as a ProjectModel."""
        raise NotImplementedError

"""ETS Writer interfaces - design only, see docs/ets-writer-architecture.md.

No method here has a real implementation. The four interfaces are the
Serialization and Update pipelines' stages:

1. ProjectDiffer   - compute the minimal ProjectChangeSet between two
                      ProjectModel snapshots (architecture doc section 4).
2. IdentityStrategy - mint ids for CREATE changes (section 6).
3. EtsSerializer    - turn a ProjectChangeSet into a SerializedProject
                      (section 4).
4. EtsWriter        - the single entry point; orchestrates the full
                      pipeline and applies it to a base .knxproj (sections
                      4 and 5).
"""

import abc
from pathlib import Path

from ai_resort_platform.generators.ets.models import (
    ProjectChangeSet,
    SerializedProject,
    WriteResult,
)
from ai_resort_platform.models.project import ProjectModel


class ProjectDiffer(abc.ABC):
    """Computes the minimal ProjectChangeSet between two ProjectModel snapshots.

    `original` must be exactly what the Reader produced from the base
    .knxproj being edited - the Update pipeline uses this diff, not the
    full `updated` model, to decide what to touch. An object present in
    both with no field differences produces no ObjectChange at all.
    """

    @abc.abstractmethod
    def diff(self, original: ProjectModel, updated: ProjectModel) -> ProjectChangeSet:
        raise NotImplementedError


class IdentityStrategy(abc.ABC):
    """Mints ids for CREATE changes.

    UPDATE/DELETE changes always reuse the id the Reader originally
    captured - never re-minted, since reuse is what makes an edit an edit
    instead of a delete-and-recreate. Distinct from Clone Engine's
    AddressAllocator (Step 5): this mints internal object ids, not bus
    addresses - see architecture doc section 6.
    """

    @abc.abstractmethod
    def mint_id(self, object_kind: str, base_project: ProjectModel) -> str:
        raise NotImplementedError


class EtsSerializer(abc.ABC):
    """Turns a fully id-assigned ProjectChangeSet into a SerializedProject."""

    @abc.abstractmethod
    def serialize(
        self, change_set: ProjectChangeSet, base_project: ProjectModel
    ) -> SerializedProject:
        raise NotImplementedError


class EtsWriter(abc.ABC):
    """Applies a ProjectChangeSet onto a base .knxproj, producing an updated one.

    See docs/ets-writer-architecture.md for the full pipeline and the two
    envisioned implementation strategies (direct XML patching vs. an ETS
    App using the official ETS SDK) - both fit this same interface.
    """

    @abc.abstractmethod
    def write(
        self, base_project_path: Path, change_set: ProjectChangeSet, output_path: Path
    ) -> WriteResult:
        raise NotImplementedError

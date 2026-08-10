"""A villa's deployment recipe: which project, which options, where to write.

Everything build_package needs beyond the ETS project itself used to live
only in whoever's shell history last regenerated the package. That is a
real hazard rather than an inconvenience: regenerating with the defaults
silently produces a working-looking package that has lost the media
source (no artwork, no metadata), the check-in automation, and the
sync_state suppression - and the loss is only noticed when a guest
arrives and the music does not start.

So the recipe is a file, committed next to the code.

The project password is deliberately *not* in it. It names an environment
variable to read instead, because a deployment file belongs in version
control and a password does not.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ai_resort_platform.homeassistant.builder import AudioEqualizerAddresses


class DeploymentError(ValueError):
    """Raised for a recipe that cannot be acted on as written."""


@dataclass(frozen=True, slots=True)
class Deployment:
    """One villa's generation inputs and outputs."""

    project_path: Path
    password_env: str | None = None
    welcome_playlist: int | None = None
    background_playlist: int | None = None
    welcome_volume_percent: float = 50
    welcome_to_background_delay: str = "00:05:00"
    audio_media_source: str | None = None
    audio_equalizer: AudioEqualizerAddresses | None = None
    unresponsive_addresses: tuple[str, ...] = field(default_factory=tuple)
    answers_read_requests: bool = True
    package_output: Path | None = None
    dashboard_output: Path | None = None

    @property
    def password(self) -> str | None:
        """The project password, read from the environment at use time.

        Missing is not an error here: an unprotected project needs none.
        A protected one fails later, in the reader, with its own message.
        """
        if self.password_env is None:
            return None
        return os.environ.get(self.password_env)


def load_deployment(path: Path) -> Deployment:
    """Read a deployment recipe.

    Relative paths inside it resolve against the file's own directory, so
    a recipe can be moved or checked out anywhere without rewriting.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise DeploymentError(f"{path}: not valid TOML: {error}") from error

    base = path.parent

    def resolve(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else (base / candidate).resolve()

    project = data.get("project", {})
    if "path" not in project:
        raise DeploymentError(f"{path}: [project] needs a 'path'")

    package = data.get("package", {})
    output = data.get("output", {})
    equalizer = package.get("audio_equalizer")

    return Deployment(
        project_path=resolve(project["path"]),
        password_env=project.get("password_env"),
        welcome_playlist=package.get("welcome_playlist"),
        background_playlist=package.get("background_playlist"),
        welcome_volume_percent=package.get("welcome_volume_percent", 50),
        welcome_to_background_delay=package.get("welcome_to_background_delay", "00:05:00"),
        audio_media_source=package.get("audio_media_source"),
        audio_equalizer=(
            AudioEqualizerAddresses(
                address=equalizer["address"], state_address=equalizer.get("state_address")
            )
            if equalizer
            else None
        ),
        unresponsive_addresses=tuple(package.get("unresponsive_addresses", ())),
        answers_read_requests=package.get("answers_read_requests", True),
        package_output=resolve(output["package"]) if "package" in output else None,
        dashboard_output=resolve(output["dashboard"]) if "dashboard" in output else None,
    )

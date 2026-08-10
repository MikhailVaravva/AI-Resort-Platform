import argparse
from pathlib import Path

from ai_resort_platform import __version__
from ai_resort_platform.deployment import Deployment, load_deployment
from ai_resort_platform.ets.project import ETSProject
from ai_resort_platform.generators.ha_yaml import write_dashboard, write_package
from ai_resort_platform.homeassistant.builder import build_dashboard, build_package


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-resort-platform")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    build = subparsers.add_parser(
        "build",
        help="generate a villa's Home Assistant package and dashboard from a deployment recipe",
        description=(
            "Reads a deployment recipe (see deployments/) and writes the Home "
            "Assistant package and dashboard it describes. The recipe carries "
            "every option the generated output depends on, so regenerating "
            "cannot silently drop one."
        ),
    )
    build.add_argument("recipe", type=Path, help="path to a deployment .toml")
    build.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be written without writing it",
    )
    return parser


def _describe(deployment: Deployment) -> list[str]:
    lines = [f"project:  {deployment.project_path}"]
    if deployment.audio_media_source:
        lines.append(f"media source: {deployment.audio_media_source}")
    if deployment.unresponsive_addresses:
        lines.append(f"not polled:   {len(deployment.unresponsive_addresses)} addresses")
    if deployment.welcome_playlist is not None:
        lines.append(
            f"check-in:     playlist {deployment.welcome_playlist} "
            f"-> {deployment.background_playlist} "
            f"after {deployment.welcome_to_background_delay}"
        )
    return lines


def _build(recipe: Path, dry_run: bool) -> int:
    deployment = load_deployment(recipe)
    project = ETSProject.open(deployment.project_path, password=deployment.password)
    package = build_package(
        project,
        welcome_playlist=deployment.welcome_playlist,
        background_playlist=deployment.background_playlist,
        welcome_volume_percent=deployment.welcome_volume_percent,
        welcome_to_background_delay=deployment.welcome_to_background_delay,
        audio_equalizer=deployment.audio_equalizer,
        audio_media_source=deployment.audio_media_source,
        unresponsive_addresses=deployment.unresponsive_addresses,
    )

    for line in _describe(deployment):
        print(line)
    print(
        f"built:    {len(package.entities)} entities, {len(package.selects)} selects, "
        f"{len(package.scenes)} scenes, {len(package.automations)} automations"
    )

    if deployment.package_output:
        if dry_run:
            print(f"would write: {deployment.package_output}")
        else:
            write_package(package, deployment.package_output)
            print(f"wrote:    {deployment.package_output}")
    if deployment.dashboard_output:
        dashboard = build_dashboard(package)
        if dry_run:
            print(f"would write: {deployment.dashboard_output}")
        else:
            write_dashboard(dashboard, deployment.dashboard_output)
            print(f"wrote:    {deployment.dashboard_output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        return _build(args.recipe, args.dry_run)
    build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

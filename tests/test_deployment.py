"""The deployment recipe.

Its whole purpose is that regenerating a villa cannot quietly lose an
option, so the tests are mostly about what happens when one is absent.
"""

import pytest

from ai_resort_platform.cli import build_parser, main
from ai_resort_platform.deployment import DeploymentError, load_deployment

RECIPE = """
[project]
path = "villa.knxproj"
password_env = "SOME_PASSWORD"

[package]
welcome_playlist = 1
background_playlist = 2
audio_media_source = "media_player.lms"
unresponsive_addresses = ["1/1/203", "1/1/231"]

[output]
package = "out/villa.yaml"
dashboard = "out/villa_dashboard.yaml"
"""


def _write(tmp_path, text=RECIPE):
    path = tmp_path / "villa.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_every_generation_option_survives_the_round_trip(tmp_path):
    d = load_deployment(_write(tmp_path))

    assert d.welcome_playlist == 1
    assert d.background_playlist == 2
    assert d.audio_media_source == "media_player.lms"
    assert d.unresponsive_addresses == ("1/1/203", "1/1/231")


def test_relative_paths_resolve_against_the_recipe_not_the_caller(tmp_path):
    """So a checkout works from any working directory."""
    d = load_deployment(_write(tmp_path))

    assert d.project_path == tmp_path / "villa.knxproj"
    assert d.package_output == tmp_path / "out" / "villa.yaml"


def test_an_absolute_project_path_is_left_alone(tmp_path):
    d = load_deployment(_write(tmp_path, '[project]\npath = "/mnt/h/villa.knxproj"\n'))

    assert str(d.project_path) == "/mnt/h/villa.knxproj"


def test_the_password_comes_from_the_environment_not_the_file(tmp_path, monkeypatch):
    """A recipe belongs in version control; a password does not."""
    d = load_deployment(_write(tmp_path))
    assert "SOME_PASSWORD" not in RECIPE.replace('password_env = "SOME_PASSWORD"', "")

    monkeypatch.delenv("SOME_PASSWORD", raising=False)
    assert d.password is None

    monkeypatch.setenv("SOME_PASSWORD", "hunter2")
    assert d.password == "hunter2"


def test_a_project_without_a_password_needs_no_variable(tmp_path):
    d = load_deployment(_write(tmp_path, '[project]\npath = "villa.knxproj"\n'))

    assert d.password_env is None
    assert d.password is None


def test_a_recipe_without_a_project_is_rejected(tmp_path):
    with pytest.raises(DeploymentError, match="path"):
        load_deployment(_write(tmp_path, "[package]\nwelcome_playlist = 1\n"))


def test_malformed_toml_names_the_file(tmp_path):
    with pytest.raises(DeploymentError, match="not valid TOML"):
        load_deployment(_write(tmp_path, "[project\n"))


def test_defaults_match_build_package(tmp_path):
    """An option absent from the recipe must land on the same default the
    generator would have used, not a second, divergent one."""
    d = load_deployment(_write(tmp_path, '[project]\npath = "villa.knxproj"\n'))

    assert d.welcome_volume_percent == 50
    assert d.welcome_to_background_delay == "00:05:00"
    assert d.unresponsive_addresses == ()
    assert d.audio_equalizer is None


def test_build_is_a_real_subcommand():
    args = build_parser().parse_args(["build", "recipe.toml", "--dry-run"])

    assert args.command == "build"
    assert args.dry_run is True


def test_bare_invocation_still_exits_cleanly():
    assert main([]) == 0


def test_the_villa_a1_recipe_is_loadable_and_complete():
    """The committed recipe for the live installation.

    Not a style check: this file is the only place the running villa's
    generation options exist, so it is worth failing a build over.
    """
    from pathlib import Path

    recipe = Path(__file__).resolve().parent.parent / "deployments" / "villa_a1.toml"
    d = load_deployment(recipe)

    assert d.password_env, "a protected project needs its password variable named"
    assert d.audio_media_source, "without this the player loses artwork and metadata"
    assert d.welcome_playlist is not None and d.background_playlist is not None
    assert len(d.unresponsive_addresses) == 10
    assert d.package_output is not None and d.dashboard_output is not None


def test_no_recipe_carries_a_password_value():
    """Recipes are committed. Passwords are not."""
    from pathlib import Path

    for recipe in (Path(__file__).resolve().parent.parent / "deployments").glob("*.toml"):
        text = recipe.read_text(encoding="utf-8")
        assert "password =" not in text, recipe
        assert "password_env" in text or "path" in text

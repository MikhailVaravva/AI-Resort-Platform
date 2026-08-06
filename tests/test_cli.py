import pytest

from ai_resort_platform.cli import main


def test_main_with_no_arguments_returns_zero():
    assert main([]) == 0


def test_version_flag_exits_cleanly():
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0

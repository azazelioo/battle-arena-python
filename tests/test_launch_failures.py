import builtins
import runpy
import sys
from unittest.mock import patch

import pytest

from arena.__main__ import main
from arena.application.controller import GameController
from arena.presentation.cli import Console


def rejecting_import(target):
    original = builtins.__import__

    def import_module(name, *args, **kwargs):
        if name == target:
            raise ImportError(f"No module named {name}")
        return original(name, *args, **kwargs)

    return import_module


def test_missing_pytest_has_actionable_message(capsys):
    with patch("builtins.__import__", side_effect=rejecting_import("pytest")):
        with pytest.raises(SystemExit) as error:
            main(["--test"])
    assert error.value.code == 2
    assert "pip install" in capsys.readouterr().err


def test_missing_tkinter_recommends_cli(tmp_path, capsys):
    with patch(
        "builtins.__import__",
        side_effect=rejecting_import("arena.presentation.gui"),
    ):
        with pytest.raises(SystemExit) as error:
            main(["--data-dir", str(tmp_path)])
    assert error.value.code == 2
    assert "--cli" in capsys.readouterr().err


def test_python_module_entrypoint_returns_console_status(
    tmp_path, monkeypatch
):
    monkeypatch.delitem(sys.modules, "arena.__main__", raising=False)
    with patch.object(
        sys, "argv", ["arena", "--cli", "--data-dir", str(tmp_path)]
    ):
        with patch("arena.presentation.cli.Console.run", return_value=0):
            with pytest.raises(SystemExit) as error:
                runpy.run_module("arena", run_name="__main__")
    assert error.value.code == 0


def test_console_displays_startup_warning_and_history_menu(tmp_path):
    controller = GameController(tmp_path)
    controller.warning = "Повреждены настройки"
    answers = iter(["4", "7"])
    messages = []
    assert (
        Console(controller, lambda _: next(answers), messages.append).run()
        == 0
    )
    assert "Повреждены настройки" in messages
    assert "История пуста." in messages


def test_console_no_match_battle_returns_without_prompt(tmp_path):
    controller = GameController(tmp_path)
    Console(
        controller, lambda _: pytest.fail("Unexpected prompt"), print
    ).battle()

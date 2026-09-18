from unittest.mock import patch

import pytest

from arena.__main__ import main
from arena.application.controller import GameController, MatchSetup
from arena.domain.model import Phase
from arena.infrastructure.storage import StorageError
from arena.presentation.cli import Console
from conftest import surrender


def session(controller, inputs):
    iterator = iter(inputs)
    messages = []
    console = Console(controller, lambda _: next(iterator), messages.append)
    return console, messages


def test_menu_continue_without_game_rules_settings_and_exit(tmp_path):
    controller = GameController(tmp_path)
    console, messages = session(controller, ["2", "5", "6", "0", "16", "7"])
    assert console.run() == 0
    assert "Нет активного боя." in messages
    assert controller.settings.bot_delay_ms == 0
    assert controller.settings.font_size == 16
    assert "Настройки сохранены." in messages


def test_menu_load_failure_and_settings_failure_return_to_menu(tmp_path):
    controller = GameController(tmp_path)
    console, messages = session(controller, ["3", "1", "6", "-1", "15", "7"])
    assert console.run() == 0
    assert any("Не удалось прочитать" in line for line in messages)
    assert any("Ожидается целое число" in line for line in messages)


def test_pause_load_restores_state_and_save_failure_keeps_pause(tmp_path):
    controller = GameController(tmp_path)
    original = controller.new_match(MatchSetup(mode="pvp"))
    controller.save(1)
    controller.submit(
        next(o for o in controller.options() if o.available).request(original)
    )
    console, messages = session(controller, ["3", "2", "3", "1"])
    assert console.pause_menu()
    assert controller.snapshot() == original
    assert not controller.paused
    assert any("Не удалось прочитать" in line for line in messages)


def test_pause_save_error_is_reported(tmp_path):
    controller = GameController(tmp_path)
    controller.new_match(MatchSetup(mode="pvp"))
    console, messages = session(controller, ["2", "1", "4"])
    with patch.object(
        controller, "save", side_effect=StorageError("readonly")
    ):
        assert not console.pause_menu()
    assert "readonly" in messages
    assert controller.paused


def test_console_rules_and_cancel_surrender(tmp_path):
    controller = GameController(tmp_path)
    before = controller.new_match(MatchSetup(mode="pvp"))
    console, messages = session(controller, ["r", "q", "нет", "p", "4"])
    console.battle()
    assert controller.snapshot() == before
    assert any("БОЕВАЯ АРЕНА" in message for message in messages)


def test_console_bot_step_then_pause(tmp_path):
    controller = GameController(tmp_path)
    before = controller.new_match(MatchSetup())
    console, messages = session(controller, ["p", "4"])
    console.battle()
    assert controller.snapshot().successful_actions == 1
    assert controller.snapshot().active_id != before.active_id


def test_console_bot_setup(tmp_path):
    controller = GameController(tmp_path)
    console, _ = session(controller, ["1", "A", "3", "2", "B", "2", "3", "2"])
    console.new_match()
    state = controller.snapshot()
    assert state.mode == "bot" and state.strategy == "cautious"
    assert state.fighters[0].archetype == "ranger"
    assert state.fighters[0].equipment == "blade"
    assert state.fighters[1].equipment == "amulet"


def test_history_empty_filtered_and_clear(tmp_path, battle):
    controller = GameController(tmp_path)
    console, messages = session(controller, [])
    console.history()
    assert messages == ["История пуста."]
    surrender(battle)
    controller.repository.add_result(battle.snapshot())
    console, messages = session(controller, ["not-found", "нет"])
    console.history()
    assert not messages
    console, messages = session(controller, ["", "да"])
    console.history()
    assert len(controller.repository.history()) == 0
    assert any("Победитель" in line for line in messages)


def test_result_rematch_warning_and_return_to_menu(tmp_path):
    controller = GameController(tmp_path)
    controller.new_match(MatchSetup(mode="pvp"))
    console, messages = session(controller, ["q", "да", "2", "p", "4"])
    with patch.object(
        controller.repository, "add_result", side_effect=StorageError("disk")
    ):
        console.battle()
    assert controller.snapshot().phase == Phase.WAITING_ACTION
    assert controller.snapshot().successful_actions == 0
    assert any("история не записана" in line for line in messages)


@pytest.mark.parametrize(
    "exit_inputs,saved",
    [(["1", "2"], True), (["2"], False), (["3", "7", "2"], False)],
)
def test_exit_save_discard_cancel(tmp_path, exit_inputs, saved):
    controller = GameController(tmp_path)
    controller.new_match(MatchSetup(mode="pvp"))
    console, _ = session(controller, ["7", *exit_inputs])
    assert console.run() == 0
    assert controller.repository.slot(2).exists() == saved


def test_continue_and_load_from_main_menu(tmp_path):
    controller = GameController(tmp_path)
    before = controller.new_match(MatchSetup(mode="pvp"))
    controller.save(1)
    console, _ = session(
        controller, ["2", "p", "4", "3", "1", "p", "4", "7", "2"]
    )
    assert console.run() == 0
    assert controller.snapshot() == before


def test_main_cli_uses_custom_data_dir(tmp_path):
    with patch("builtins.input", return_value="7"):
        # Console's injected defaults are bound at import, so patch its run boundary.
        with patch(
            "arena.presentation.cli.Console.run", return_value=0
        ) as run:
            assert main(["--cli", "--data-dir", str(tmp_path)]) == 0
            run.assert_called_once()


def test_main_test_mode_returns_runner_status():
    with patch("pytest.main", return_value=3) as runner:
        assert main(["--test"]) == 3
        assert runner.call_args.args[0][0].endswith("tests")


def test_main_mutually_exclusive_modes():
    with pytest.raises(SystemExit) as error:
        main(["--cli", "--test"])
    assert error.value.code == 2


def test_main_help(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0
    assert "--data-dir" in capsys.readouterr().out

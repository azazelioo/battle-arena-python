"""Real-widget smoke checks; skipped only if Tcl/Tk/display is unavailable."""

from unittest.mock import patch

import pytest

tk = pytest.importorskip("tkinter")

from arena.application.controller import (
    FighterSetup,
    GameController,
    MatchSetup,
)
from arena.domain.model import ActionRequest, Phase
from arena.presentation.gui import ArenaWindow


@pytest.fixture
def window(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Нет графической среды: {error}")
    root.withdraw()
    controller = GameController(tmp_path)
    app = ArenaWindow(root, controller)
    yield app
    app.cancel_bot()
    root.destroy()


@pytest.mark.gui
def test_screens_render_and_navigation(window):
    for screen in (
        window.menu,
        window.setup,
        window.rules,
        window.settings,
        window.history,
    ):
        screen()
        window.root.update_idletasks()
        assert window.container.winfo_children()
    window.controller.new_match(MatchSetup(mode="pvp"))
    window.battle()
    window.root.update_idletasks()
    assert window._screen == "battle"
    window.pause()
    assert window.controller.paused
    window.resume()
    assert not window.controller.paused


@pytest.mark.gui
def test_pause_cancels_pending_bot_and_stale_callback(window):
    original = window.controller.new_match(MatchSetup())
    window.battle()
    assert window._callback is not None
    window.pause()
    assert window._callback is None
    window.bot_callback(original.match_id, original.turn)
    assert window.controller.snapshot() == original
    window.controller.new_match(MatchSetup())
    current = window.controller.snapshot()
    window.battle()
    window.bot_callback(original.match_id, original.turn)
    assert window.controller.snapshot() == current


@pytest.mark.gui
def test_gui_and_direct_controller_commands_match(window, tmp_path):
    setup = MatchSetup(mode="pvp")
    state = window.controller.new_match(setup)
    window.controller.save(1)
    reference = GameController(window.controller.repository.directory)
    reference.load(1)
    for action_id in (
        "fireball",
        "defend",
        "attack",
        "heavy_strike",
        "heal",
        "attack",
    ):
        s = window.controller.snapshot()
        request = next(
            o for o in window.controller.options() if o.action_id == action_id
        ).request(s)
        window.submit(request)
        assert reference.submit(request).accepted
        assert window.controller.snapshot() == reference.snapshot()


@pytest.mark.gui
def test_slots_and_result_screens(window):
    state = window.controller.new_match(MatchSetup(mode="pvp"))
    window.controller.save(1)
    window.slots(False, window.menu)
    window.root.update_idletasks()
    assert window._screen == "slots"
    window.controller.resume()
    window.controller.submit(
        ActionRequest(
            state.match_id,
            state.turn,
            state.active_id,
            "surrender",
            state.active_id,
        )
    )
    window.battle()
    assert window._screen == "result"
    window.history()
    assert window._screen == "history"


@pytest.mark.gui
def test_close_cancel_restores_bot_timer(window):
    window.controller.new_match(MatchSetup())
    window.battle()
    with patch("tkinter.messagebox.askyesnocancel", return_value=None):
        window.close()
    assert window._screen == "battle"
    assert window._callback is not None


def widgets(parent, kind):
    result = []
    for child in parent.winfo_children():
        if isinstance(child, kind):
            result.append(child)
        result.extend(widgets(child, kind))
    return result


def click(window, label):
    from tkinter import ttk

    matches = [
        w
        for w in widgets(window.container, ttk.Button)
        if w.cget("text") == label
    ]
    assert matches, label
    matches[0].invoke()
    window.root.update_idletasks()


@pytest.mark.gui
def test_start_form_creates_selected_fighters(window):
    from tkinter import ttk

    window.setup()
    entries = [
        w
        for w in widgets(window.container, ttk.Entry)
        if not isinstance(w, ttk.Combobox)
    ]
    entries[0].delete(0, "end")
    entries[0].insert(0, "Первый")
    combos = widgets(window.container, ttk.Combobox)
    combos[0].set("Два игрока")
    combos[2].set("Следопыт")
    combos[3].set("Учебный клинок")
    click(window, "Начать бой")
    state = window.controller.snapshot()
    assert state.mode == "pvp"
    assert state.fighters[0].name == "Первый"
    assert state.fighters[0].stats.attack == 19
    assert state.active_id == "p1"


@pytest.mark.gui
def test_save_load_slot_buttons(window):
    original = window.controller.new_match(MatchSetup(mode="pvp"))
    window.slots(True, window.pause)
    with patch("tkinter.messagebox.showinfo"):
        click(window, "Сохранить")
    assert window.controller.repository.slot(1).exists()
    window.controller.new_match(MatchSetup(mode="pvp"))
    window.slots(False, window.menu)
    click(window, "Загрузить")
    assert window.controller.snapshot() == original
    assert window._screen == "battle"


@pytest.mark.gui
def test_overwrite_cancel_preserves_slot(window):
    window.controller.new_match(MatchSetup(mode="pvp"))
    window.controller.save(1)
    original_bytes = window.controller.repository.slot(1).read_bytes()
    window.controller.new_match(MatchSetup(mode="pvp"))
    window.slots(True, window.pause)
    with patch("tkinter.messagebox.askyesno", return_value=False):
        click(window, "Сохранить")
    assert window.controller.repository.slot(1).read_bytes() == original_bytes


@pytest.mark.gui
def test_load_bad_slot_keeps_match(window):
    window.controller.new_match(MatchSetup(mode="pvp"))
    original = window.controller.snapshot()
    window.controller.repository.directory.mkdir(exist_ok=True)
    window.controller.repository.slot(1).write_text("broken")
    window.slots(False, window.pause)
    with patch("tkinter.messagebox.showerror") as report:
        click(window, "Загрузить")
        report.assert_called_once()
    assert window.controller.snapshot() == original


@pytest.mark.gui
def test_gui_surrender_rematch_and_history_clear(window):
    from tkinter import ttk

    window.controller.new_match(MatchSetup(mode="pvp"))
    window.battle()
    with patch("tkinter.messagebox.askyesno", return_value=True):
        window.surrender()
    assert window._screen == "result"
    assert window.controller.snapshot().finish_reason == "surrender"
    window.history()
    tree = widgets(window.container, ttk.Treeview)[0]
    tree.selection_set(tree.get_children()[0])
    tree.event_generate("<<TreeviewSelect>>")
    window.root.update()
    assert len(window.controller.repository.history()) == 1
    with patch("tkinter.messagebox.askyesno", return_value=True):
        window.clear_history()
    assert len(window.controller.repository.history()) == 0
    window.rematch()
    assert window.controller.snapshot().successful_actions == 0


@pytest.mark.gui
def test_settings_apply_and_invalid_value(window):
    from tkinter import ttk

    window.settings()
    spinners = widgets(window.container, ttk.Spinbox)
    spinners[0].set("0")
    spinners[1].set("14")
    click(window, "Применить")
    assert window.controller.settings.bot_delay_ms == 0
    assert window.controller.settings.font_size == 14
    window.settings()
    widgets(window.container, ttk.Spinbox)[0].set("bad")
    with patch("tkinter.messagebox.showerror") as report:
        click(window, "Применить")
        report.assert_called_once()


@pytest.mark.gui
def test_valid_bot_callback_advances_once(window):
    state = window.controller.new_match(MatchSetup())
    window.battle()
    window.cancel_bot()
    window.bot_callback(state.match_id, state.turn)
    assert window.controller.snapshot().successful_actions == 1
    assert window._callback is None


@pytest.mark.gui
def test_gui_reports_rejected_request(window):
    state = window.controller.new_match(MatchSetup(mode="pvp"))
    request = ActionRequest(
        state.match_id, 0, state.active_id, "attack", state.opponent.id
    )
    with patch("tkinter.messagebox.showinfo") as report:
        window.submit(request)
        report.assert_called_once()
    assert window.controller.snapshot() == state


@pytest.mark.gui
def test_all_battle_controls_fit_minimum_window(window):
    from tkinter import ttk

    window.controller.new_match(MatchSetup(mode="pvp"))
    window.root.geometry("1000x700")
    window.root.deiconify()
    window.battle()
    window.root.update_idletasks()
    buttons = widgets(window.container, ttk.Button)
    footer_top = next(
        w for w in buttons if w.cget("text") == "Пауза / сохранение"
    ).winfo_rooty()
    actions = [w for w in buttons if w.cget("style") == "Action.TButton"]
    assert len(actions) == 8
    for button in actions:
        assert button.winfo_rooty() + button.winfo_height() <= footer_top
        assert (
            button.winfo_rootx() + button.winfo_width()
            <= window.root.winfo_rootx() + 1000
        )
    assert all(w.winfo_height() >= w.winfo_reqheight() for w in buttons)


@pytest.mark.gui
def test_font_setting_changes_ttk_styles_immediately(window):
    from tkinter import font, ttk
    from arena.infrastructure.records import Settings

    before = window.style.lookup("TButton", "font")
    window.controller.update_settings(Settings(300, 20))
    window.apply_font()
    window.menu()
    after = window.style.lookup("TButton", "font")
    assert before != after
    assert font.Font(window.root, font=after).actual("size") == 20
    window.settings()
    assert widgets(window.container, ttk.Spinbox)


@pytest.mark.gui
def test_large_text_layout_scroll_and_keyboard_reveal(window):
    from types import SimpleNamespace
    from tkinter import ttk
    from arena.infrastructure.records import Settings

    window.root.geometry("1000x700")
    window.root.deiconify()
    window.controller.update_settings(Settings(300, 20))
    window.apply_font()
    window.controller.new_match(MatchSetup(mode="pvp"))
    window.battle()
    window.root.update_idletasks()
    viewport = window.viewport
    assert viewport.content.winfo_height() > viewport.canvas.winfo_height()
    for number, delta in ((4, 0), (5, 0), (0, 120), (0, -120)):
        assert (
            viewport.wheel(SimpleNamespace(num=number, delta=delta)) == "break"
        )
    footer = next(
        w
        for w in widgets(window.container, ttk.Button)
        if w.cget("text") == "Сдаться"
    )
    window.focus_visible(SimpleNamespace(widget=footer))
    window.root.update_idletasks()
    assert viewport.canvas.yview()[1] > 0.9
    assert footer.winfo_rooty() >= viewport.canvas.winfo_rooty()
    window.focus_visible(SimpleNamespace(widget=window.root))
    viewport.reset()
    assert viewport.canvas.yview()[0] == 0


@pytest.mark.gui
def test_history_replay_buttons_and_filters(window):
    from tkinter import ttk

    state = window.controller.new_match(MatchSetup(mode="pvp"))
    window.controller.submit(
        ActionRequest(
            state.match_id,
            state.turn,
            state.active_id,
            "surrender",
            state.active_id,
        )
    )
    window.history()
    click(window, "Просмотреть по ходам")  # no selection is harmless
    assert window._screen == "history"
    tree = widgets(window.container, ttk.Treeview)[0]
    search = next(
        w
        for w in widgets(window.container, ttk.Entry)
        if not isinstance(w, ttk.Combobox)
    )
    search.insert(0, "not found")
    assert not tree.get_children()
    search.delete(0, "end")
    assert len(tree.get_children()) == 1
    filters = widgets(window.container, ttk.Combobox)
    filters[0].set("С ботом")
    assert not tree.get_children()
    filters[0].set("Все режимы")
    filters[1].set("Ничья")
    assert not tree.get_children()
    filters[1].set("Сдача")
    assert len(tree.get_children()) == 1
    click(window, "Следующая страница")
    click(window, "Предыдущая страница")
    tree.selection_set(tree.get_children()[0])
    click(window, "Просмотреть по ходам")
    assert window._screen == "replay"
    click(window, "Следующее событие")
    click(window, "Предыдущее событие")
    click(window, "К итогу")
    assert window.controller.snapshot().finish_reason == "surrender"
    click(window, "Назад к истории")
    assert window._screen == "history"


@pytest.mark.gui
def test_empty_battle_and_history_error_fallback(window):
    from arena.infrastructure.storage import StorageError

    window.battle()
    assert window._screen == "menu"
    with patch.object(
        window.controller.repository,
        "history",
        side_effect=StorageError("history error"),
    ):
        with patch("tkinter.messagebox.showerror") as report:
            window.history()
            report.assert_called_once()
    assert window._screen == "menu"


@pytest.mark.gui
def test_history_clear_declined_and_failed(window):
    from arena.infrastructure.storage import StorageError

    with patch("tkinter.messagebox.askyesno", return_value=False):
        with patch.object(
            window.controller.repository, "clear_history"
        ) as clear:
            window.clear_history()
            clear.assert_not_called()
    with patch("tkinter.messagebox.askyesno", return_value=True):
        with patch.object(
            window.controller.repository,
            "clear_history",
            side_effect=StorageError("write error"),
        ):
            with patch("tkinter.messagebox.showerror") as report:
                window.clear_history()
                report.assert_called_once()


@pytest.mark.gui
def test_result_displays_history_write_warning(window):
    state = window.controller.new_match(MatchSetup(mode="pvp"))
    window.controller.submit(
        ActionRequest(
            state.match_id,
            state.turn,
            state.active_id,
            "surrender",
            state.active_id,
        )
    )
    window.controller.warning = "История не записана"
    window.battle()
    assert window._screen == "result"
    from tkinter import ttk

    assert any(
        w.cget("text") == "История не записана"
        for w in widgets(window.container, ttk.Label)
    )


@pytest.mark.gui
def test_exit_save_path_and_cancel_from_menu(window):
    window.controller.new_match(MatchSetup(mode="pvp"))
    window.menu()
    with patch("tkinter.messagebox.askyesnocancel", return_value=None):
        window.close()
    assert window._screen == "menu"
    with patch.object(window, "destroy") as close:
        with patch("tkinter.messagebox.askyesnocancel", return_value=True):
            window.close()
        assert window._screen == "slots"
        click(window, "Сохранить")
        close.assert_called_once()
    assert window.controller.repository.slot(1).exists()


@pytest.mark.gui
def test_exit_without_save_and_without_match(window):
    window.controller.new_match(MatchSetup(mode="pvp"))
    with patch("tkinter.messagebox.askyesnocancel", return_value=False):
        with patch.object(window, "destroy") as close:
            window.close()
            close.assert_called_once()
    window.controller.abandon()
    with patch.object(window, "destroy") as close:
        window.close()
        close.assert_called_once()


@pytest.mark.gui
def test_surrender_cancel_and_history_empty_selection(window):
    from tkinter import ttk

    window.surrender()
    state = window.controller.new_match(MatchSetup(mode="pvp"))
    with patch("tkinter.messagebox.askyesno", return_value=False):
        window.surrender()
    assert window.controller.snapshot() == state
    window.history()
    tree = widgets(window.container, ttk.Treeview)[0]
    tree.event_generate("<<TreeviewSelect>>")
    window.root.update()
    assert window._screen == "history"


@pytest.mark.gui
def test_startup_warning_is_displayed_and_resources_close(tmp_path):
    controller = GameController(tmp_path)
    controller.warning = "Повреждены настройки"
    root = tk.Tk()
    root.withdraw()
    with patch("tkinter.messagebox.showwarning") as warning:
        app = ArenaWindow(root, controller)
        root.update()
        warning.assert_called_once()
    controller.new_match(MatchSetup())
    app.battle()
    assert app._callback is not None
    app.destroy()
    assert app._callback is None
    assert controller.snapshot() is None


@pytest.mark.gui
def test_gui_entrypoint_success_and_failures(tmp_path, capsys):
    from arena.__main__ import main
    from arena.presentation.gui import run_gui

    controller = GameController(tmp_path)
    root = tk.Tk()
    root.withdraw()
    with patch("arena.presentation.gui.tk.Tk", return_value=root):
        with patch.object(root, "mainloop") as loop:
            assert run_gui(controller) == 0
            loop.assert_called_once()
    root.destroy()
    with patch("arena.presentation.gui.run_gui", return_value=0):
        assert main(["--data-dir", str(tmp_path)]) == 0
    with patch(
        "arena.presentation.gui.run_gui", side_effect=tk.TclError("no display")
    ):
        with pytest.raises(SystemExit) as error:
            main(["--data-dir", str(tmp_path)])
    assert error.value.code == 2
    assert "--cli" in capsys.readouterr().err
    with patch(
        "arena.presentation.gui.run_gui", side_effect=RuntimeError("bug")
    ):
        with pytest.raises(RuntimeError, match="bug"):
            main(["--data-dir", str(tmp_path)])


@pytest.mark.gui
def test_resource_benchmark_counts_callbacks_and_windows(monkeypatch):
    import importlib.util
    from pathlib import Path

    tools = Path(__file__).resolve().parents[1] / "tools"
    monkeypatch.syspath_prepend(str(tools))
    spec = importlib.util.spec_from_file_location(
        "arena_gui_benchmark", tools / "benchmark_gui.py"
    )
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    with pytest.raises(ValueError):
        benchmark.measure(0)
    result = benchmark.measure(2)
    assert result["cycles"] == 2
    assert result["no_widget_growth"]
    assert result["no_pending_callbacks"]
    assert result["python_peak_bytes"] >= result["python_current_bytes"]
    assert result["widgets_after"] == result["widgets_before"]


@pytest.mark.gui
def test_real_after_callback_executes_exactly_one_bot_turn(window):
    from arena.infrastructure.records import Settings

    window.controller.update_settings(Settings(0, 12))
    initial = window.controller.new_match(MatchSetup())
    window.battle()
    assert window._callback is not None
    window.root.update()
    current = window.controller.snapshot()
    assert current.turn == initial.turn + 1
    assert current.successful_actions == 1
    assert not window.controller.is_bot_turn()
    assert window._callback is None
    window.root.update()
    assert window.controller.snapshot() == current


@pytest.mark.gui
def test_pause_cancels_real_zero_delay_callback_before_dispatch(window):
    from arena.infrastructure.records import Settings

    window.controller.update_settings(Settings(0, 12))
    initial = window.controller.new_match(MatchSetup())
    window.battle()
    window.pause()
    window.root.update()
    assert window.controller.snapshot() == initial
    assert window._callback is None
    assert not window.root.tk.call("after", "info")


@pytest.mark.gui
def test_repeated_screen_changes_leave_no_bot_timers(window):
    initial = window.controller.new_match(MatchSetup())
    for _ in range(5):
        window.controller.resume()
        window.battle()
        window.menu()
        window.root.update()
        assert window._callback is None
        assert not window.root.tk.call("after", "info")
    assert window.controller.snapshot() == initial


@pytest.mark.gui
def test_menu_art_redraws_when_window_is_mapped(window):
    from arena.presentation.theme import ArenaArt

    window.root.deiconify()
    window.menu()
    window.root.update()

    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)

    art = next(
        item for item in descendants(window.root) if isinstance(item, ArenaArt)
    )
    initial_count = len(art.find_all())
    assert initial_count > 50
    window.root.geometry("1200x900")
    window.root.update()
    assert len(art.find_all()) == initial_count

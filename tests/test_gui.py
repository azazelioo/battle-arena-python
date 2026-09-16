"""Real-widget smoke checks; skipped only if Tcl/Tk/display is unavailable."""
from unittest.mock import patch

import pytest

tk = pytest.importorskip("tkinter")

from arena.application.controller import FighterSetup, GameController, MatchSetup
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
    for screen in (window.menu, window.setup, window.rules,
                   window.settings, window.history):
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
    for action_id in ("fireball", "defend", "attack", "heavy_strike", "heal", "attack"):
        s = window.controller.snapshot()
        request = next(o for o in window.controller.options() if o.action_id == action_id).request(s)
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
    window.controller.submit(ActionRequest(state.match_id, state.turn,
                                            state.active_id, "surrender", state.active_id))
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
    matches = [w for w in widgets(window.container, ttk.Button) if w.cget("text") == label]
    assert matches, label
    matches[0].invoke()
    window.root.update_idletasks()


@pytest.mark.gui
def test_start_form_creates_selected_fighters(window):
    from tkinter import ttk
    window.setup()
    entries = [w for w in widgets(window.container, ttk.Entry)
               if not isinstance(w, ttk.Combobox)]
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
    request = ActionRequest(state.match_id, 0, state.active_id, "attack", state.opponent.id)
    with patch("tkinter.messagebox.showinfo") as report:
        window.submit(request)
        report.assert_called_once()
    assert window.controller.snapshot() == state

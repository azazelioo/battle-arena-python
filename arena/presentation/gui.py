"""Tkinter screens. Every mutation goes through GameController."""
from __future__ import annotations

import tkinter as tk
from tkinter import font, messagebox, ttk
from typing import Callable, Literal
from functools import partial

from arena.application.controller import FighterSetup, GameController, MatchSetup
from arena.domain.catalog import CHARACTERS, EQUIPMENT, final_stats
from arena.domain.model import ActionRequest, BattleSnapshot, Phase
from arena.infrastructure.records import Settings
from arena.infrastructure.storage import StorageError, load_match
from .formatting import RULES, event_text, fighter_text, result_text


class ArenaWindow:
    def __init__(self, root: tk.Tk, controller: GameController) -> None:
        self.root = root
        self.controller = controller
        self._callback: str | None = None
        self._screen = "menu"
        root.title("Боевая арена")
        root.geometry("1100x800")
        root.minsize(1000, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self.style.configure("TFrame", background="#f3f0e8")
        self.style.configure("TLabel", background="#f3f0e8", foreground="#202c38")
        self.style.configure("TButton", padding=(12, 8))
        self.style.configure("Health.Horizontal.TProgressbar", background="#48836b")
        self.style.configure("Energy.Horizontal.TProgressbar", background="#5488a2")
        self.style.configure("Title.TLabel", font=("Helvetica", 28, "bold"))
        self.style.configure("Heading.TLabel", font=("Helvetica", 16, "bold"))
        self.container = ttk.Frame(root, padding=24)
        self.container.pack(fill="both", expand=True)
        self.apply_font()
        self.menu()
        if controller.warning:
            root.after_idle(lambda: messagebox.showwarning(
                "Настройки", controller.warning, parent=root))

    def apply_font(self) -> None:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            font.nametofont(name).configure(size=self.controller.settings.font_size)

    def cancel_bot(self) -> None:
        if self._callback is not None:
            self.root.after_cancel(self._callback)
            self._callback = None

    def clear(self, screen: str) -> None:
        self.cancel_bot()
        self._screen = screen
        for child in self.container.winfo_children():
            child.destroy()

    def title(self, text: str, subtitle: str = "") -> None:
        ttk.Label(self.container, text=text, style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        if subtitle:
            ttk.Label(self.container, text=subtitle, wraplength=950).pack(anchor="w", pady=(0, 18))

    def button(self, parent: tk.Misc, text: str,
               command: Callable[[], object],
               state: Literal["normal", "disabled"] = "normal") -> ttk.Button:
        # Widget packing stays explicit at call sites to keep screens readable.
        return ttk.Button(parent, text=text, command=command, state=state)

    def text_panel(self, parent: tk.Misc, text: str, height: int = 12) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=10)
        field = tk.Text(frame, wrap="word", height=height, padx=14, pady=12,
                        background="#fffdf7", foreground="#202c38", relief="flat",
                        font=("Helvetica", self.controller.settings.font_size))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=field.yview)
        field.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        field.pack(side="left", fill="both", expand=True)
        field.insert("1.0", text)
        field.configure(state="disabled")
        return field

    def menu(self) -> None:
        self.controller.pause()
        self.clear("menu")
        self.title("БОЕВАЯ АРЕНА", "Один ход. Одно решение. Воин, маг или следопыт — выберите свой стиль боя.")
        controls = ttk.Frame(self.container)
        controls.pack(anchor="w", pady=20)
        self.button(controls, "Новый бой", self.setup).pack(fill="x", pady=5)
        snapshot = self.controller.snapshot()
        self.button(controls, "Продолжить", self.resume,
                    state="normal" if snapshot else "disabled").pack(fill="x", pady=5)
        self.button(controls, "Загрузить бой", lambda: self.slots(False, self.menu)).pack(fill="x", pady=5)
        for label, command in (("История матчей", self.history), ("Правила", self.rules),
                               ("Настройки", self.settings), ("Выход", self.close)):
            self.button(controls, label, command).pack(fill="x", pady=5)
        ttk.Label(self.container, text="Локальная игра · Без аккаунтов и подключения к сети").pack(side="bottom", anchor="w")

    def setup(self) -> None:
        self.clear("setup")
        self.title("Новый бой", "Снаряжение применяется до начала боя. Итоговые характеристики показаны ниже.")
        current = self.controller.last_setup
        mode = tk.StringVar(value="Против бота" if current.mode == "bot" else "Два игрока")
        strategy = tk.StringVar(value="Осторожная" if current.strategy == "cautious" else "Агрессивная")
        bar = ttk.Frame(self.container)
        bar.pack(fill="x", pady=10)
        ttk.Label(bar, text="Режим").pack(side="left")
        ttk.Combobox(bar, textvariable=mode, state="readonly", width=18,
                     values=("Против бота", "Два игрока")).pack(side="left", padx=12)
        ttk.Label(bar, text="Стратегия бота").pack(side="left")
        ttk.Combobox(bar, textvariable=strategy, state="readonly", width=18,
                     values=("Осторожная", "Агрессивная")).pack(side="left", padx=12)
        cards = ttk.Frame(self.container)
        cards.pack(fill="x", pady=20)
        values: list[tuple[tk.StringVar, tk.StringVar, tk.StringVar]] = []
        classes = {value.name: key for key, value in CHARACTERS.items()}
        gear = {value.name: key for key, value in EQUIPMENT.items()}
        for index, fighter in enumerate((current.first, current.second)):
            frame = ttk.LabelFrame(cards, text=f"Сторона {index + 1}", padding=18)
            frame.pack(side="left", fill="both", expand=True, padx=8)
            name = tk.StringVar(value=fighter.name)
            archetype = tk.StringVar(value=CHARACTERS[fighter.archetype].name)
            equipment = tk.StringVar(value=EQUIPMENT[fighter.equipment].name)
            values.append((name, archetype, equipment))
            ttk.Label(frame, text="Имя (до 24 символов)").pack(anchor="w")
            ttk.Entry(frame, textvariable=name).pack(fill="x", pady=(4, 12))
            ttk.Label(frame, text="Архетип").pack(anchor="w")
            ttk.Combobox(frame, textvariable=archetype, state="readonly",
                         values=tuple(classes)).pack(fill="x", pady=(4, 12))
            ttk.Label(frame, text="Снаряжение").pack(anchor="w")
            ttk.Combobox(frame, textvariable=equipment, state="readonly",
                         values=tuple(gear)).pack(fill="x", pady=(4, 12))
            preview = ttk.Label(frame, justify="left")
            preview.pack(anchor="w", pady=16)

            def refresh(*args: object, a: tk.StringVar = archetype,
                        e: tk.StringVar = equipment, label: ttk.Label = preview) -> None:
                stats = final_stats(classes[a.get()], gear[e.get()])
                label.configure(text=(f"Здоровье  {stats.max_hp}     Энергия  {stats.max_energy}\n"
                                      f"Атака  {stats.attack}     Магия  {stats.magic}\n"
                                      f"Броня  {stats.armor}     Скорость  {stats.speed}"))

            archetype.trace_add("write", refresh)
            equipment.trace_add("write", refresh)
            refresh()

        def start() -> None:
            fighters = [FighterSetup(n.get(), classes[a.get()], gear[e.get()])
                        for n, a, e in values]
            self.controller.new_match(MatchSetup(
                fighters[0], fighters[1], "bot" if mode.get() == "Против бота" else "pvp",
                "cautious" if strategy.get() == "Осторожная" else "aggressive"))
            self.battle()

        self.button(self.container, "Начать бой", start).pack(anchor="w", pady=10)
        self.button(self.container, "Назад", self.menu).pack(anchor="w")

    def resume(self) -> None:
        self.controller.resume()
        self.battle()

    def battle(self) -> None:
        snapshot = self.controller.snapshot()
        if snapshot is None:
            self.menu()
            return
        if snapshot.phase == Phase.FINISHED:
            self.result(snapshot)
            return
        self.clear("battle")
        bot_turn = self.controller.is_bot_turn()
        caption = "Ход бота" if bot_turn else "Ваш ход"
        self.title(f"Ход {snapshot.turn} · Раунд {snapshot.round}",
                   f"{caption}: {snapshot.active.name} [{snapshot.active_id}]")
        cards = ttk.Frame(self.container)
        cards.pack(fill="x", pady=8)
        for fighter in snapshot.fighters:
            active = " · АКТИВНЫЙ" if fighter.id == snapshot.active_id else ""
            card = ttk.LabelFrame(cards, text=f"{fighter.name} [{fighter.id}]{active}", padding=14)
            card.pack(side="left", fill="both", expand=True, padx=6)
            ttk.Label(card, text=fighter_text(fighter), justify="left").pack(anchor="w")
            ttk.Progressbar(card, style="Health.Horizontal.TProgressbar", maximum=fighter.stats.max_hp, value=fighter.hp).pack(fill="x", pady=(12, 3))
            ttk.Progressbar(card, style="Energy.Horizontal.TProgressbar", maximum=max(1, fighter.stats.max_energy), value=fighter.energy).pack(fill="x", pady=3)
        actions = ttk.Frame(self.container)
        actions.pack(fill="x", pady=12)
        for index, option in enumerate(self.controller.options()):
            row, column = divmod(index, 4)
            box = ttk.Frame(actions)
            box.grid(row=row, column=column, sticky="nsew", padx=4, pady=3)
            actions.columnconfigure(column, weight=1)
            request = option.request(snapshot)
            self.button(box, f"{option.name} · {option.cost} Э",
                        partial(self.submit, request),
                        state="normal" if option.available and not bot_turn else "disabled").pack(fill="x")
            preview = (f"Урон {option.damage}" if option.damage else
                       f"HP +{option.healing}" if option.healing else
                       f"Энергия +{option.energy}" if option.energy else "")
            ttk.Label(box, text=option.reason or preview, wraplength=220).pack(anchor="w")
        field = self.text_panel(self.container, "\n".join(event_text(e, snapshot) for e in snapshot.events), 8)
        field.see("end")
        footer = ttk.Frame(self.container)
        footer.pack(fill="x")
        self.button(footer, "Пауза / сохранение", self.pause).pack(side="left", padx=4)
        self.button(footer, "Сдаться", self.surrender,
                    state="disabled" if bot_turn else "normal").pack(side="left", padx=4)
        if bot_turn and not self.controller.paused:
            self._callback = self.root.after(
                self.controller.settings.bot_delay_ms,
                lambda: self.bot_callback(snapshot.match_id, snapshot.turn))

    def submit(self, request: ActionRequest) -> None:
        result = self.controller.submit(request)
        if not result.accepted:
            messagebox.showinfo("Действие недоступно", result.message, parent=self.root)
        self.battle()

    def bot_callback(self, match_id: str, turn: int) -> None:
        self._callback = None
        if self._screen != "battle" or self.controller.paused:
            return
        result = self.controller.bot_step(match_id, turn)
        if result.accepted:
            self.battle()

    def pause(self) -> None:
        self.controller.pause()
        self.clear("pause")
        snapshot = self.controller.snapshot()
        self.title("Пауза", f"Ход {snapshot.turn if snapshot else '—'} сохранён в памяти.")
        for text, command in (
            ("Продолжить", self.resume),
            ("Сохранить", lambda: self.slots(True, self.pause)),
            ("Загрузить", lambda: self.slots(False, self.pause)),
            ("Главное меню", self.menu),
        ):
            self.button(self.container, text, command).pack(anchor="w", pady=8)

    def slots(self, saving: bool, back: Callable[[], None],
              after_save: Callable[[], None] | None = None) -> None:
        self.cancel_bot()
        self.controller.pause()
        self.clear("slots")
        self.title("Сохранить бой" if saving else "Загрузить бой",
                   "Три независимых слота. Запись заменяет выбранный слот.")
        for index in range(1, 4):
            path = self.controller.repository.slot(index)
            detail = "Пустой слот"
            if path.exists():
                try:
                    state = load_match(path)
                    names = " / ".join(f.name for f in state.fighters)
                    from datetime import datetime
                    stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                    detail = f"{names} · ход {state.turn} · {stamp}"
                except (StorageError, OSError):
                    detail = "Повреждённый или недоступный файл"
            row = ttk.LabelFrame(self.container, text=f"Слот {index}", padding=18)
            row.pack(fill="x", pady=10)
            ttk.Label(row, text=detail).pack(side="left")

            def select(slot: int = index) -> None:
                try:
                    if saving:
                        if self.controller.repository.slot(slot).exists() and not messagebox.askyesno(
                                "Заменить сохранение?", f"Перезаписать слот {slot}?", parent=self.root):
                            return
                        self.controller.save(slot)
                        if after_save:
                            after_save()
                            return
                        messagebox.showinfo("Сохранено", "Бой сохранён.", parent=self.root)
                        back()
                    else:
                        self.controller.load(slot)
                        self.battle()
                except StorageError as error:
                    messagebox.showerror("Ошибка файла", str(error), parent=self.root)

            self.button(row, "Сохранить" if saving else "Загрузить", select,
                        state="normal" if saving or path.exists() else "disabled").pack(side="right")
        self.button(self.container, "Назад", back).pack(anchor="w", pady=10)

    def surrender(self) -> None:
        snapshot = self.controller.snapshot()
        if snapshot and messagebox.askyesno("Сдаться?", "Завершить бой поражением?", parent=self.root):
            self.submit(ActionRequest(snapshot.match_id, snapshot.turn,
                                      snapshot.active_id, "surrender", snapshot.active_id))

    def result(self, snapshot: BattleSnapshot) -> None:
        self.clear("result")
        self.title("Бой завершён")
        self.text_panel(self.container, result_text(snapshot))
        if self.controller.warning:
            ttk.Label(self.container, text=self.controller.warning, wraplength=950).pack(anchor="w")
        self.button(self.container, "Реванш", self.rematch).pack(anchor="w", pady=6)
        self.button(self.container, "Новые настройки", self.setup).pack(anchor="w", pady=6)
        self.button(self.container, "Главное меню", self.menu).pack(anchor="w", pady=6)

    def rematch(self) -> None:
        self.controller.new_match(self.controller.last_setup)
        self.battle()

    def history(self) -> None:
        self.clear("history")
        self.title("История матчей", "Последние 50 завершённых боёв. Выберите строку для просмотра результата.")
        try:
            entries = list(reversed(list(self.controller.repository.history())))
        except StorageError as error:
            messagebox.showerror("История недоступна", str(error), parent=self.root)
            self.menu()
            return
        query = tk.StringVar()
        filter_row = ttk.Frame(self.container)
        filter_row.pack(fill="x")
        ttk.Label(filter_row, text="Фильтр по имени или исходу").pack(side="left")
        ttk.Entry(filter_row, textvariable=query).pack(side="left", padx=12, fill="x", expand=True)
        tree = ttk.Treeview(self.container, columns=("date", "fighters", "outcome"), show="headings", height=9)
        for key, label, width in (("date", "Дата", 180), ("fighters", "Участники", 400), ("outcome", "Исход", 240)):
            tree.heading(key, text=label)
            tree.column(key, width=width)
        tree.pack(fill="x", pady=12)
        detail = self.text_panel(self.container, "Выберите матч в списке.", 8)

        def refresh(*args: object) -> None:
            for child in tree.get_children():
                tree.delete(child)
            for index, entry in enumerate(entries):
                state = entry.snapshot
                names = " / ".join(f.name for f in state.fighters)
                outcome = state.fighter(state.winner_id).name if state.winner_id else "Ничья"
                if query.get().casefold() in f"{names} {outcome}".casefold():
                    tree.insert("", "end", iid=str(index), values=(entry.completed_at[:16], names, outcome))

        def select(event: tk.Event[tk.Misc]) -> None:
            selection = tree.selection()
            if selection:
                state = entries[int(selection[0])].snapshot
                detail.configure(state="normal")
                detail.delete("1.0", "end")
                detail.insert("1.0", result_text(state) + "\n\n" + "\n".join(event_text(e, state) for e in state.events))
                detail.configure(state="disabled")

        query.trace_add("write", refresh)
        tree.bind("<<TreeviewSelect>>", select)
        refresh()
        self.button(self.container, "Очистить историю", self.clear_history).pack(anchor="w", pady=5)
        self.button(self.container, "Назад", self.menu).pack(anchor="w", pady=5)

    def clear_history(self) -> None:
        if messagebox.askyesno("Очистить историю?", "Удалить все результаты матчей?", parent=self.root):
            try:
                self.controller.repository.clear_history()
                self.history()
            except StorageError as error:
                messagebox.showerror("Ошибка", str(error), parent=self.root)

    def rules(self) -> None:
        self.clear("rules")
        self.title("Правила")
        self.text_panel(self.container, RULES)
        self.button(self.container, "Назад", self.menu).pack(anchor="w")

    def settings(self) -> None:
        self.clear("settings")
        self.title("Настройки", "Задержка применяется только к графическому интерфейсу.")
        delay = tk.StringVar(value=str(self.controller.settings.bot_delay_ms))
        size = tk.StringVar(value=str(self.controller.settings.font_size))
        for label, variable, low, high in (("Задержка бота, мс", delay, 0, 3000),
                                          ("Размер текста", size, 10, 20)):
            ttk.Label(self.container, text=label).pack(anchor="w", pady=(16, 4))
            ttk.Spinbox(self.container, textvariable=variable, from_=low, to=high, width=12).pack(anchor="w")

        def apply() -> None:
            try:
                self.controller.update_settings(Settings(int(delay.get()), int(size.get())))
                self.apply_font()
                self.menu()
            except (ValueError, StorageError) as error:
                messagebox.showerror("Ошибка настроек", str(error), parent=self.root)

        self.button(self.container, "Применить", apply).pack(anchor="w", pady=20)
        self.button(self.container, "Отмена", self.menu).pack(anchor="w")

    def destroy(self) -> None:
        self.cancel_bot()
        self.controller.abandon()
        self.root.destroy()

    def close(self) -> None:
        self.cancel_bot()
        snapshot = self.controller.snapshot()
        if snapshot and snapshot.phase == Phase.WAITING_ACTION:
            answer = messagebox.askyesnocancel(
                "Выход", "Сохранить незаконченный бой перед выходом?", parent=self.root)
            if answer is None:
                if self._screen == "battle":
                    self.battle()
                return
            if answer:
                self.slots(True, self.pause, after_save=self.destroy)
                return
        self.destroy()


def run_gui(controller: GameController) -> int:
    root = tk.Tk()
    ArenaWindow(root, controller)
    root.mainloop()
    return 0

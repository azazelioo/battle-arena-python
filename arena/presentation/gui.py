"""Tkinter screens. Every mutation goes through GameController."""

from __future__ import annotations

import tkinter as tk
from tkinter import font, messagebox, ttk
from typing import Callable, Literal
from functools import partial

from arena.application.controller import (
    FighterSetup,
    GameController,
    MatchSetup,
)
from arena.domain.catalog import CHARACTERS, EQUIPMENT, final_stats
from arena.domain.model import (
    ActionRequest,
    BattleSnapshot,
    CharacterSnapshot,
    Phase,
)
from arena.infrastructure.records import Settings
from arena.infrastructure.storage import StorageError, load_match
from .formatting import RULES, event_text, result_text
from . import theme
from .viewport import ScrollViewport
from arena.application.history import (
    BattleReplay,
    HistoryBrowser,
    HistoryFilter,
)


class ArenaWindow:
    def __init__(self, root: tk.Tk, controller: GameController) -> None:
        self.root = root
        self.controller = controller
        self._callback: str | None = None
        self._screen = "menu"
        root.title("Боевая арена")
        root.geometry("1180x820")
        root.minsize(1000, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.style, self.display_font, self.body_font = theme.configure(
            root, controller.settings.font_size
        )
        self.viewport = ScrollViewport(root)
        self.viewport.pack(fill="both", expand=True)
        self.container = self.viewport.content
        root.bind("<FocusIn>", self.focus_visible)
        self.apply_font()
        self.menu()
        if controller.warning:
            root.after_idle(
                lambda: messagebox.showwarning(
                    "Настройки", controller.warning, parent=root
                )
            )

    def focus_visible(self, event: tk.Event[tk.Misc]) -> None:
        if isinstance(event.widget, tk.Widget):
            self.viewport.reveal(event.widget)

    def apply_font(self) -> None:
        self.style, self.display_font, self.body_font = theme.configure(
            self.root, self.controller.settings.font_size
        )
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            font.nametofont(name).configure(
                family=self.body_font, size=self.controller.settings.font_size
            )

    def cancel_bot(self) -> None:
        if self._callback is not None:
            self.root.after_cancel(self._callback)
            self._callback = None

    def clear(self, screen: str) -> None:
        self.cancel_bot()
        self._screen = screen
        self.viewport.reset()
        for child in self.container.winfo_children():
            child.destroy()

    def title(self, text: str, subtitle: str = "") -> None:
        ttk.Label(self.container, text=text, style="Title.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        if subtitle:
            ttk.Label(
                self.container,
                text=subtitle,
                wraplength=950,
                style="Muted.TLabel",
            ).pack(anchor="w", pady=(0, 18))

    def button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], object],
        state: Literal["normal", "disabled"] = "normal",
    ) -> ttk.Button:
        # Widget packing stays explicit at call sites to keep screens readable.
        return ttk.Button(
            parent,
            text=text,
            command=command,
            state=state,
            style=(
                "Primary.TButton"
                if text
                in (
                    "Новый бой",
                    "Начать бой",
                    "Продолжить",
                    "Применить",
                    "Реванш",
                )
                else "TButton"
            ),
        )

    def text_panel(
        self, parent: tk.Misc, text: str, height: int = 12
    ) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=10)
        field = tk.Text(
            frame,
            wrap="word",
            width=1,
            height=height,
            padx=14,
            pady=12,
            background=theme.SURFACE,
            foreground=theme.MUTED,
            relief="flat",
            selectbackground=theme.LINE,
            selectforeground=theme.TEXT,
            highlightthickness=0,
            borderwidth=0,
            spacing1=3,
            spacing3=5,
            font=(self.body_font, self.controller.settings.font_size),
        )
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
        shell = ttk.Frame(self.container)
        shell.pack(fill="both", expand=True)
        left = ttk.Frame(shell, padding=(14, 15, 0, 12))
        left.pack(side="left", fill="both", expand=True)
        theme.ArenaArt(shell).pack(
            side="right", fill="both", expand=True, padx=(30, 10)
        )
        ttk.Label(
            left,
            text="Боевая\nарена",
            font=(self.display_font, 46),
            foreground=theme.TEXT,
        ).pack(anchor="w", pady=(0, 18))
        ttk.Label(
            left,
            text=(
                "Выберите героя. Продумайте ход.\n"
                "Победите на своей стороне арены."
            ),
            style="Muted.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(0, 28))
        controls = ttk.Frame(left)
        controls.pack(fill="x", padx=(0, 35))
        self.button(controls, "Новый бой", self.setup).pack(fill="x", pady=5)
        snapshot = self.controller.snapshot()
        self.button(
            controls,
            "Продолжить",
            self.resume,
            state="normal" if snapshot else "disabled",
        ).pack(fill="x", pady=5)
        self.button(
            controls, "Загрузить бой", lambda: self.slots(False, self.menu)
        ).pack(fill="x", pady=5)
        links = ttk.Frame(controls)
        links.pack(fill="x", pady=(18, 0))
        for index, (label, command) in enumerate(
            (
                ("История матчей", self.history),
                ("Правила", self.rules),
                ("Настройки", self.settings),
                ("Выход", self.close),
            )
        ):
            self.button(links, label, command).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=3, pady=4
            )
            links.columnconfigure(index % 2, weight=1)
        ttk.Label(
            self.container,
            text="Пошаговые поединки    •    Два игрока или бой с ботом",
            style="Muted.TLabel",
        ).pack(anchor="w", padx=14, pady=(16, 0))

    def setup(self) -> None:
        self.clear("setup")
        self.title(
            "Новый бой",
            "Снаряжение применяется до начала боя. "
            "Итоговые характеристики показаны ниже.",
        )
        current = self.controller.last_setup
        mode = tk.StringVar(
            value="Против бота" if current.mode == "bot" else "Два игрока"
        )
        strategy = tk.StringVar(
            value=(
                "Осторожная"
                if current.strategy == "cautious"
                else "Агрессивная"
            )
        )
        bar = ttk.Frame(self.container)
        bar.pack(fill="x", pady=10)
        ttk.Label(bar, text="Режим").pack(side="left")
        ttk.Combobox(
            bar,
            textvariable=mode,
            state="readonly",
            width=18,
            values=("Против бота", "Два игрока"),
        ).pack(side="left", padx=12)
        ttk.Label(bar, text="Стратегия бота").pack(side="left")
        ttk.Combobox(
            bar,
            textvariable=strategy,
            state="readonly",
            width=18,
            values=("Осторожная", "Агрессивная"),
        ).pack(side="left", padx=12)
        cards = ttk.Frame(self.container)
        cards.pack(fill="x", pady=20)
        values: list[tuple[tk.StringVar, tk.StringVar, tk.StringVar]] = []
        classes = {value.name: key for key, value in CHARACTERS.items()}
        gear = {value.name: key for key, value in EQUIPMENT.items()}
        for index, fighter in enumerate((current.first, current.second)):
            frame = ttk.LabelFrame(
                cards, text=f"Сторона {index + 1}", padding=18
            )
            frame.pack(side="left", fill="both", expand=True, padx=8)
            name = tk.StringVar(value=fighter.name)
            archetype = tk.StringVar(value=CHARACTERS[fighter.archetype].name)
            equipment = tk.StringVar(value=EQUIPMENT[fighter.equipment].name)
            values.append((name, archetype, equipment))
            ttk.Label(frame, text="Имя (до 24 символов)").pack(anchor="w")
            ttk.Entry(frame, textvariable=name).pack(fill="x", pady=(4, 12))
            ttk.Label(frame, text="Архетип").pack(anchor="w")
            ttk.Combobox(
                frame,
                textvariable=archetype,
                state="readonly",
                values=tuple(classes),
            ).pack(fill="x", pady=(4, 12))
            ttk.Label(frame, text="Снаряжение").pack(anchor="w")
            ttk.Combobox(
                frame,
                textvariable=equipment,
                state="readonly",
                values=tuple(gear),
            ).pack(fill="x", pady=(4, 12))
            preview = ttk.Label(frame, justify="left")
            preview.pack(anchor="w", pady=16)

            def refresh(
                *args: object,
                a: tk.StringVar = archetype,
                e: tk.StringVar = equipment,
                label: ttk.Label = preview,
            ) -> None:
                stats = final_stats(classes[a.get()], gear[e.get()])
                label.configure(
                    text=(
                        f"Здоровье  {stats.max_hp}     "
                        f"Энергия  {stats.max_energy}\n"
                        f"Атака  {stats.attack}     Магия  {stats.magic}\n"
                        f"Броня  {stats.armor}     Скорость  {stats.speed}"
                    )
                )

            archetype.trace_add("write", refresh)
            equipment.trace_add("write", refresh)
            refresh()

        def start() -> None:
            fighters = [
                FighterSetup(n.get(), classes[a.get()], gear[e.get()])
                for n, a, e in values
            ]
            self.controller.new_match(
                MatchSetup(
                    fighters[0],
                    fighters[1],
                    "bot" if mode.get() == "Против бота" else "pvp",
                    (
                        "cautious"
                        if strategy.get() == "Осторожная"
                        else "aggressive"
                    ),
                )
            )
            self.battle()

        self.button(self.container, "Начать бой", start).pack(
            anchor="w", pady=10
        )
        self.button(self.container, "Назад", self.menu).pack(anchor="w")

    def resume(self) -> None:
        self.controller.resume()
        self.battle()

    def fighter_card(
        self, parent: tk.Misc, fighter: CharacterSnapshot, active: bool
    ) -> None:
        border = tk.Frame(
            parent,
            background=theme.GOLD if active else theme.LINE,
            padx=1,
            pady=1,
        )
        border.pack(side="left", fill="both", expand=True, padx=5)
        card = ttk.Frame(border, style="Card.TFrame", padding=12)
        card.pack(fill="both", expand=True)
        heading = ttk.Frame(card, style="Card.TFrame")
        heading.pack(fill="x")
        theme.Emblem(heading, fighter.archetype, 64).pack(
            side="left", padx=(0, 16)
        )
        names = ttk.Frame(heading, style="Card.TFrame")
        names.pack(side="left", fill="x", expand=True)
        ttk.Label(
            names,
            text=f"{CHARACTERS[fighter.archetype].name}   /   {fighter.id}",
            style="CardMuted.TLabel",
        ).pack(anchor="w")
        ttk.Label(names, text=fighter.name, style="CardName.TLabel").pack(
            anchor="w", pady=3
        )
        ttk.Label(
            names,
            text="Сейчас ходит" if active else "Ожидает хода",
            style="CardMuted.TLabel",
            foreground=theme.GOLD if active else theme.MUTED,
        ).pack(anchor="w")
        for label, value, maximum, style in (
            ("Здоровье", fighter.hp, fighter.stats.max_hp, "Health"),
            ("Энергия", fighter.energy, fighter.stats.max_energy, "Energy"),
        ):
            row = ttk.Frame(card, style="Card.TFrame")
            row.pack(fill="x", pady=(6, 3))
            ttk.Label(row, text=label, style="CardMuted.TLabel").pack(
                side="left"
            )
            ttk.Label(
                row, text=f"{value} / {maximum}", style="Card.TLabel"
            ).pack(side="right")
            ttk.Progressbar(
                card,
                style=f"{style}.Horizontal.TProgressbar",
                maximum=max(1, maximum),
                value=value,
            ).pack(fill="x")
        stats = fighter.stats
        ttk.Label(
            card,
            text=(
                f"Атака {stats.attack}     Магия {stats.magic}"
                + (
                    "\n"
                    if self.controller.settings.font_size > 14
                    else "     "
                )
                + f"Броня {stats.armor}     Скорость {stats.speed}"
            ),
            style="CardMuted.TLabel",
        ).pack(anchor="w", pady=(8, 4))
        effects = " · ".join(
            "Защита" if e.effect_id == "guard" else f"Яд: {e.remaining}"
            for e in fighter.effects
        )
        ttk.Label(
            card,
            text=effects or EQUIPMENT[fighter.equipment].name,
            style="CardMuted.TLabel",
            foreground=theme.GOLD if effects else theme.MUTED,
        ).pack(anchor="w")

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
        top = ttk.Frame(self.container)
        top.pack(fill="x", pady=(0, 14))
        ttk.Label(
            top, text=f"Раунд {snapshot.round}", style="Title.TLabel"
        ).pack(side="left")
        ttk.Label(
            top,
            text=f"Ход {snapshot.turn} / 100   ·   "
            + (
                "Бот выбирает действие"
                if bot_turn
                else f"Ваш ход, {snapshot.active.name}"
            ),
            style="Gold.TLabel",
        ).pack(side="right")
        cards = ttk.Frame(self.container)
        cards.pack(fill="x", pady=(0, 18))
        for fighter in snapshot.fighters:
            self.fighter_card(cards, fighter, fighter.id == snapshot.active_id)
        footer = ttk.Frame(self.container)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        self.button(footer, "Пауза / сохранение", self.pause).pack(side="left")
        self.button(
            footer,
            "Сдаться",
            self.surrender,
            state="disabled" if bot_turn else "normal",
        ).pack(side="right")
        lower = ttk.Frame(self.container)
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=3, uniform="lower")
        lower.columnconfigure(1, weight=2, uniform="lower")
        lower.rowconfigure(0, weight=1)
        command_panel = ttk.Frame(lower)
        command_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        ttk.Label(
            command_panel, text="Ваше действие", style="Heading.TLabel"
        ).pack(anchor="w", pady=(0, 12))
        actions = ttk.Frame(command_panel)
        actions.pack(fill="x")
        columns = 2 if self.controller.settings.font_size > 14 else 3
        for index, option in enumerate(self.controller.options()):
            row, column = divmod(index, columns)
            box = ttk.Frame(actions)
            box.grid(
                row=row, column=column, sticky="nsew", padx=(0, 7), pady=(0, 9)
            )
            actions.columnconfigure(column, weight=1, uniform="action")
            short_names = {
                "recover": "Восстановить",
                "health_potion": "Зелье здоровья",
                "energy_potion": "Зелье энергии",
                "poison_arrow": "Ядовитая стрела",
            }
            name = short_names.get(
                option.item_id or option.action_id, option.name
            )
            request = option.request(snapshot)
            ttk.Button(
                box,
                text=name,
                style="Action.TButton",
                command=partial(self.submit, request),
                state=(
                    "normal"
                    if option.available and not bot_turn
                    else "disabled"
                ),
            ).pack(fill="x")
            preview = (
                f"Урон {option.damage}"
                if option.damage
                else (
                    f"Здоровье +{option.healing}"
                    if option.healing
                    else (
                        f"Энергия +{option.energy}"
                        if option.energy
                        else (
                            "Защитная стойка"
                            if option.action_id == "defend"
                            else "Снятие яда"
                        )
                    )
                )
            )
            ttk.Label(
                box,
                text=option.reason or f"{option.cost} Э · {preview}",
                style="Muted.TLabel",
                font=(
                    self.body_font,
                    max(10, self.controller.settings.font_size - 2),
                ),
                wraplength=240 if columns == 2 else 170,
            ).pack(anchor="w", pady=(3, 0))
        journal = ttk.Frame(lower)
        journal.grid(row=0, column=1, sticky="nsew")
        ttk.Label(journal, text="Хроника боя", style="Heading.TLabel").pack(
            anchor="w"
        )
        field = self.text_panel(
            journal,
            "\n".join(event_text(e, snapshot) for e in snapshot.events),
            6,
        )
        field.configure(
            font=(
                self.body_font,
                max(10, self.controller.settings.font_size - 1),
            )
        )
        field.see("end")
        if bot_turn and not self.controller.paused:
            self._callback = self.root.after(
                self.controller.settings.bot_delay_ms,
                lambda: self.bot_callback(snapshot.match_id, snapshot.turn),
            )

    def submit(self, request: ActionRequest) -> None:
        result = self.controller.submit(request)
        if not result.accepted:
            messagebox.showinfo(
                "Действие недоступно", result.message, parent=self.root
            )
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
        self.title(
            "Пауза",
            f"Ход {snapshot.turn if snapshot else '—'} сохранён в памяти.",
        )
        for text, command in (
            ("Продолжить", self.resume),
            ("Сохранить", lambda: self.slots(True, self.pause)),
            ("Загрузить", lambda: self.slots(False, self.pause)),
            ("Главное меню", self.menu),
        ):
            self.button(self.container, text, command).pack(anchor="w", pady=8)

    def slots(
        self,
        saving: bool,
        back: Callable[[], None],
        after_save: Callable[[], None] | None = None,
    ) -> None:
        self.cancel_bot()
        self.controller.pause()
        self.clear("slots")
        self.title(
            "Сохранить бой" if saving else "Загрузить бой",
            "Три независимых слота. Запись заменяет выбранный слот.",
        )
        for index in range(1, 4):
            path = self.controller.repository.slot(index)
            detail = "Пустой слот"
            if path.exists():
                try:
                    state = load_match(path)
                    names = " / ".join(f.name for f in state.fighters)
                    from datetime import datetime

                    stamp = datetime.fromtimestamp(
                        path.stat().st_mtime
                    ).strftime("%d.%m.%Y %H:%M")
                    detail = f"{names} · ход {state.turn} · {stamp}"
                except (StorageError, OSError):
                    detail = "Повреждённый или недоступный файл"
            row = ttk.LabelFrame(
                self.container, text=f"Слот {index}", padding=18
            )
            row.pack(fill="x", pady=10)
            ttk.Label(row, text=detail).pack(side="left")

            def select(slot: int = index) -> None:
                try:
                    if saving:
                        if self.controller.repository.slot(
                            slot
                        ).exists() and not messagebox.askyesno(
                            "Заменить сохранение?",
                            f"Перезаписать слот {slot}?",
                            parent=self.root,
                        ):
                            return
                        self.controller.save(slot)
                        if after_save:
                            after_save()
                            return
                        messagebox.showinfo(
                            "Сохранено", "Бой сохранён.", parent=self.root
                        )
                        back()
                    else:
                        self.controller.load(slot)
                        self.battle()
                except StorageError as error:
                    messagebox.showerror(
                        "Ошибка файла", str(error), parent=self.root
                    )

            self.button(
                row,
                "Сохранить" if saving else "Загрузить",
                select,
                state="normal" if saving or path.exists() else "disabled",
            ).pack(side="right")
        self.button(self.container, "Назад", back).pack(anchor="w", pady=10)

    def surrender(self) -> None:
        snapshot = self.controller.snapshot()
        if snapshot and messagebox.askyesno(
            "Сдаться?", "Завершить бой поражением?", parent=self.root
        ):
            self.submit(
                ActionRequest(
                    snapshot.match_id,
                    snapshot.turn,
                    snapshot.active_id,
                    "surrender",
                    snapshot.active_id,
                )
            )

    def result(self, snapshot: BattleSnapshot) -> None:
        self.clear("result")
        self.title("Бой завершён")
        self.text_panel(self.container, result_text(snapshot))
        if self.controller.warning:
            ttk.Label(
                self.container, text=self.controller.warning, wraplength=950
            ).pack(anchor="w")
        self.button(self.container, "Реванш", self.rematch).pack(
            anchor="w", pady=6
        )
        self.button(self.container, "Новые настройки", self.setup).pack(
            anchor="w", pady=6
        )
        self.button(self.container, "Главное меню", self.menu).pack(
            anchor="w", pady=6
        )

    def rematch(self) -> None:
        self.controller.new_match(self.controller.last_setup)
        self.battle()

    def history(self) -> None:
        self.clear("history")
        self.title(
            "История матчей",
            "Последние 50 завершённых боёв. "
            "Выберите строку для просмотра результата.",
        )
        try:
            browser = HistoryBrowser(self.controller.repository.history())
        except StorageError as error:
            messagebox.showerror(
                "История недоступна", str(error), parent=self.root
            )
            self.menu()
            return
        query = tk.StringVar()
        filter_row = ttk.Frame(self.container)
        filter_row.pack(fill="x")
        ttk.Label(filter_row, text="Фильтр по имени или исходу").pack(
            side="left"
        )
        ttk.Entry(filter_row, textvariable=query).pack(
            side="left", padx=12, fill="x", expand=True
        )
        tree = ttk.Treeview(
            self.container,
            columns=("date", "fighters", "outcome"),
            show="headings",
            height=9,
        )
        for key, label, width in (
            ("date", "Дата", 180),
            ("fighters", "Участники", 400),
            ("outcome", "Исход", 240),
        ):
            tree.heading(key, text=label)
            tree.column(key, width=width)
        tree.pack(fill="x", pady=12)
        detail = self.text_panel(self.container, "Выберите матч в списке.", 8)

        mode = tk.StringVar(value="Все режимы")
        outcome_filter = tk.StringVar(value="Все исходы")
        modes = {"Все режимы": "all", "Два игрока": "pvp", "С ботом": "bot"}
        outcomes = {
            "Все исходы": "all",
            "Победа": "win",
            "Ничья": "draw",
            "Сдача": "surrender",
        }
        filters = ttk.Frame(self.container)
        filters.pack(fill="x")
        ttk.Combobox(
            filters,
            textvariable=mode,
            values=tuple(modes),
            state="readonly",
            width=18,
        ).pack(side="left", padx=(0, 8))
        ttk.Combobox(
            filters,
            textvariable=outcome_filter,
            values=tuple(outcomes),
            state="readonly",
            width=18,
        ).pack(side="left")

        def refresh(*args: object) -> None:
            browser.apply_filter(
                HistoryFilter(
                    query.get(),
                    modes[mode.get()],
                    outcomes[outcome_filter.get()],
                )
            )
            populate()

        def populate() -> None:
            for child in tree.get_children():
                tree.delete(child)
            for index, entry in enumerate(browser.page_entries()):
                state = entry.snapshot
                names = " / ".join(f.name for f in state.fighters)
                outcome = (
                    state.fighter(state.winner_id).name
                    if state.winner_id
                    else "Ничья"
                )
                tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(entry.completed_at[:16], names, outcome),
                )
            page_label.configure(
                text=(
                    f"Страница {browser.page + 1}/{browser.page_count}; "
                    f"матчей {browser.count}"
                )
            )

        def select(event: tk.Event[tk.Misc]) -> None:
            selection = tree.selection()
            if selection:
                state = browser.select(int(selection[0])).snapshot
                detail.configure(state="normal")
                detail.delete("1.0", "end")
                detail.insert(
                    "1.0",
                    result_text(state)
                    + "\n\n"
                    + "\n".join(event_text(e, state) for e in state.events),
                )
                detail.configure(state="disabled")

        pages = ttk.Frame(self.container)
        pages.pack(fill="x", pady=4)
        page_label = ttk.Label(pages, style="Muted.TLabel")
        page_label.pack(side="right")

        def change_page(direction: int) -> None:
            browser.move(direction)
            populate()

        self.button(
            pages, "Предыдущая страница", partial(change_page, -1)
        ).pack(side="left")
        self.button(pages, "Следующая страница", partial(change_page, 1)).pack(
            side="left", padx=8
        )
        query.trace_add("write", refresh)
        mode.trace_add("write", refresh)
        outcome_filter.trace_add("write", refresh)
        tree.bind("<<TreeviewSelect>>", select)
        refresh()

        def open_replay() -> None:
            selected = tree.selection()
            if selected:
                self.replay(browser.select(int(selected[0])).snapshot)

        self.button(self.container, "Просмотреть по ходам", open_replay).pack(
            anchor="w", pady=5
        )
        self.button(
            self.container, "Очистить историю", self.clear_history
        ).pack(anchor="w", pady=5)
        self.button(self.container, "Назад", self.menu).pack(
            anchor="w", pady=5
        )

    def replay(self, snapshot: BattleSnapshot) -> None:
        self.clear("replay")
        self.title(
            "Просмотр боя", "Записанные события; исходный бой не меняется."
        )
        replay = BattleReplay(snapshot)
        info = ttk.Label(self.container, style="Gold.TLabel")
        info.pack(anchor="w", pady=10)
        resource = ttk.Label(self.container, justify="left")
        resource.pack(anchor="w", pady=10)
        description = self.text_panel(self.container, "", 6)
        controls = ttk.Frame(self.container)
        controls.pack(fill="x")

        def render() -> None:
            frame = replay.current
            info.configure(
                text=f"Событие {frame.position} / {replay.length - 1}"
            )
            lines = []
            for value in frame.resources:
                fighter = snapshot.fighter(value.fighter_id)
                lines.append(
                    f"{fighter.name}: HP {value.hp}, энергия {value.energy}"
                )
            resource.configure(text="\n".join(lines))
            description.configure(state="normal")
            description.delete("1.0", "end")
            description.insert(
                "1.0",
                (
                    event_text(frame.event, snapshot)
                    if frame.event
                    else "Состояние до первого события"
                ),
            )
            description.configure(state="disabled")
            previous.configure(
                state="normal" if replay.position else "disabled"
            )
            following.configure(
                state=(
                    "normal"
                    if replay.position < replay.length - 1
                    else "disabled"
                )
            )

        def move(direction: int) -> None:
            replay.step(direction)
            render()

        def last() -> None:
            replay.seek(replay.length - 1)
            render()

        previous = self.button(
            controls, "Предыдущее событие", partial(move, -1)
        )
        previous.pack(side="left", padx=4)
        following = self.button(
            controls, "Следующее событие", partial(move, 1)
        )
        following.pack(side="left", padx=4)
        self.button(controls, "К итогу", last).pack(side="left", padx=4)
        self.button(self.container, "Назад к истории", self.history).pack(
            anchor="w", pady=12
        )
        render()

    def clear_history(self) -> None:
        if messagebox.askyesno(
            "Очистить историю?",
            "Удалить все результаты матчей?",
            parent=self.root,
        ):
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
        self.title(
            "Настройки",
            "Задержка применяется только к графическому интерфейсу.",
        )
        delay = tk.StringVar(value=str(self.controller.settings.bot_delay_ms))
        size = tk.StringVar(value=str(self.controller.settings.font_size))
        for label, variable, low, high in (
            ("Задержка бота, мс", delay, 0, 3000),
            ("Размер текста", size, 10, 20),
        ):
            ttk.Label(self.container, text=label).pack(
                anchor="w", pady=(16, 4)
            )
            ttk.Spinbox(
                self.container,
                textvariable=variable,
                from_=low,
                to=high,
                width=12,
            ).pack(anchor="w")

        def apply() -> None:
            try:
                self.controller.update_settings(
                    Settings(int(delay.get()), int(size.get()))
                )
                self.apply_font()
                self.menu()
            except (ValueError, StorageError) as error:
                messagebox.showerror(
                    "Ошибка настроек", str(error), parent=self.root
                )

        self.button(self.container, "Применить", apply).pack(
            anchor="w", pady=20
        )
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
                "Выход",
                "Сохранить незаконченный бой перед выходом?",
                parent=self.root,
            )
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

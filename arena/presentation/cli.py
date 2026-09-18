from __future__ import annotations

from typing import Callable

from arena.application.history import (
    BattleReplay,
    HistoryBrowser,
    HistoryFilter,
)

from arena.application.controller import (
    FighterSetup,
    GameController,
    MatchSetup,
)
from arena.domain.catalog import CHARACTERS, EQUIPMENT, final_stats
from arena.domain.model import ActionRequest, Phase
from arena.infrastructure.records import Settings
from arena.infrastructure.storage import StorageError
from .formatting import RULES, event_text, fighter_text, result_text


class Console:
    def __init__(
        self,
        controller: GameController,
        read: Callable[[str], str] = input,
        write: Callable[[str], None] = print,
    ) -> None:
        self.controller = controller
        self.read = read
        self.write = write

    def choice(self, prompt: str, options: list[str]) -> int:
        for index, option in enumerate(options, 1):
            self.write(f"{index}. {option}")
        while True:
            value = self.read(prompt).strip()
            if value.isdecimal() and 1 <= int(value) <= len(options):
                return int(value) - 1
            self.write("Введите номер из списка.")

    def setup_fighter(self, number: int) -> FighterSetup:
        name = self.read(f"Имя игрока {number}: ")
        classes = list(CHARACTERS)
        archetype = classes[
            self.choice("Архетип: ", [CHARACTERS[k].name for k in classes])
        ]
        equipment_ids = list(EQUIPMENT)
        equipment = equipment_ids[
            self.choice(
                "Снаряжение: ", [EQUIPMENT[k].name for k in equipment_ids]
            )
        ]
        stats = final_stats(archetype, equipment)
        self.write(
            f"Итог: HP {stats.max_hp}, энергия {stats.max_energy}, "
            f"атака {stats.attack}, магия {stats.magic}, "
            f"броня {stats.armor}, скорость {stats.speed}"
        )
        return FighterSetup(name, archetype, equipment)

    def new_match(self) -> None:
        mode = ("bot", "pvp")[
            self.choice("Режим: ", ["Против бота", "Два игрока"])
        ]
        first = self.setup_fighter(1)
        second = self.setup_fighter(2)
        strategy = "aggressive"
        if mode == "bot":
            strategy = ("aggressive", "cautious")[
                self.choice("Стратегия: ", ["Агрессивная", "Осторожная"])
            ]
        self.controller.new_match(MatchSetup(first, second, mode, strategy))

    def slot(self) -> int:
        return self.choice("Слот: ", ["Слот 1", "Слот 2", "Слот 3"]) + 1

    def pause_menu(self) -> bool:
        self.controller.pause()
        while True:
            selection = self.choice(
                "Пауза: ",
                [
                    "Продолжить",
                    "Сохранить",
                    "Загрузить",
                    "Главное меню",
                ],
            )
            try:
                if selection == 0:
                    self.controller.resume()
                    return True
                if selection == 1:
                    self.controller.save(self.slot())
                    self.write("Бой сохранён.")
                elif selection == 2:
                    self.controller.load(self.slot())
                    return True
                else:
                    return False
            except StorageError as error:
                self.write(str(error))

    def battle(self) -> None:
        while (snapshot := self.controller.snapshot()) is not None:
            self.write(f"\nХод {snapshot.turn} · Раунд {snapshot.round}")
            for fighter in snapshot.fighters:
                self.write(fighter_text(fighter))
            if snapshot.phase == Phase.FINISHED:
                self.write(result_text(snapshot))
                if self.controller.warning:
                    self.write(self.controller.warning)
                selection = self.choice("Далее: ", ["Меню", "Реванш"])
                if selection == 1:
                    self.controller.new_match(self.controller.last_setup)
                    continue
                return
            if self.controller.is_bot_turn():
                result = self.controller.bot_step(
                    snapshot.match_id, snapshot.turn
                )
            else:
                options = self.controller.options()
                for index, option in enumerate(options, 1):
                    detail = (
                        f"урон {option.damage}, HP +{option.healing}, "
                        f"энергия +{option.energy}"
                    )
                    self.write(
                        f"{index}. {option.name} ({option.cost} энергии): "
                        f"{detail if option.available else option.reason}"
                    )
                self.write("p — пауза, q — сдаться, r — правила")
                value = self.read(
                    f"Ход {snapshot.active.name} [{snapshot.active_id}]: "
                ).strip()
                if value == "p":
                    if not self.pause_menu():
                        return
                    continue
                if value == "r":
                    self.write(RULES)
                    continue
                if value == "q":
                    if (
                        self.read("Сдаться? (да/нет): ").strip().lower()
                        != "да"
                    ):
                        continue
                    request = ActionRequest(
                        snapshot.match_id,
                        snapshot.turn,
                        snapshot.active_id,
                        "surrender",
                        snapshot.active_id,
                    )
                elif value.isdecimal() and 1 <= int(value) <= len(options):
                    request = options[int(value) - 1].request(snapshot)
                else:
                    self.write("Неизвестная команда.")
                    continue
                result = self.controller.submit(request)
            if not result.accepted:
                self.write(result.message)
            else:
                current = self.controller.snapshot()
                assert current is not None
                for event in result.events:
                    self.write(event_text(event, current))

    def review(self, replay: BattleReplay) -> None:
        while True:
            frame = replay.current
            self.write(f"Событие {frame.position}/{replay.length - 1}")
            for value in frame.resources:
                fighter = replay.snapshot.fighter(value.fighter_id)
                self.write(
                    f"{fighter.name}: HP {value.hp}, энергия {value.energy}"
                )
            if frame.event:
                self.write(event_text(frame.event, replay.snapshot))
            command = self.read(
                "Enter — далее, p — назад, end — итог, q — выход: "
            ).strip()
            if command == "q":
                return
            if command == "":
                replay.step(1)
            elif command == "p":
                replay.step(-1)
            elif command == "end":
                replay.seek(replay.length - 1)
            else:
                self.write("Неизвестная команда просмотра.")

    def history(self) -> None:
        entries = self.controller.repository.history()
        if not entries:
            self.write("История пуста.")
            return
        browser = HistoryBrowser(entries)
        query = self.read("Фильтр по имени или исходу (Enter — все): ")
        browser.apply_filter(HistoryFilter(query))
        while True:
            for index, entry in enumerate(browser.page_entries(), 1):
                self.write(
                    f"{index}. {entry.completed_at}\n"
                    + result_text(entry.snapshot)
                )
            command = (
                self.read(
                    "Номер — просмотр; n/p — страницы; s — статистика; "
                    "да — очистить; нет — назад: "
                )
                .strip()
                .lower()
            )
            if command in ("нет", "", "q"):
                return
            if command == "да":
                self.controller.repository.clear_history()
                return
            if command in ("n", "p"):
                browser.move(1 if command == "n" else -1)
                self.write(f"Страница {browser.page + 1}/{browser.page_count}")
            elif command == "s":
                stats = browser.statistics()
                self.write(
                    f"Матчей: {stats.matches}; ничьих: {stats.draws}; "
                    f"сдач: {stats.surrenders}; "
                    f"средняя длина: {stats.average_actions:.1f}"
                )
                self.write(
                    f"Урон: {stats.direct_damage}; яд: {stats.poison_damage}; "
                    f"лечение: {stats.healing}; предметы: {stats.items_used}"
                )
            elif command.isdecimal():
                try:
                    entry = browser.select(int(command) - 1)
                except (ValueError, IndexError):
                    self.write("Нет матча с таким номером на странице.")
                else:
                    self.review(BattleReplay(entry.snapshot))
            else:
                self.write("Неизвестная команда истории.")

    def run(self) -> int:
        self.write("БОЕВАЯ АРЕНА · Python")
        if self.controller.warning:
            self.write(self.controller.warning)
        try:
            while True:
                choice = self.choice(
                    "Меню: ",
                    [
                        "Новый бой",
                        "Продолжить",
                        "Загрузить",
                        "История",
                        "Правила",
                        "Настройки",
                        "Выход",
                    ],
                )
                try:
                    if choice == 0:
                        self.new_match()
                        self.battle()
                    elif choice == 1:
                        if self.controller.snapshot() is None:
                            self.write("Нет активного боя.")
                        else:
                            self.controller.resume()
                            self.battle()
                    elif choice == 2:
                        self.controller.load(self.slot())
                        self.battle()
                    elif choice == 3:
                        self.history()
                    elif choice == 4:
                        self.write(RULES)
                    elif choice == 5:
                        delay = int(
                            self.read("Задержка бота в GUI (0–3000 мс): ")
                        )
                        size = int(self.read("Размер текста GUI (10–20): "))
                        self.controller.update_settings(Settings(delay, size))
                        self.write("Настройки сохранены.")
                    else:
                        snapshot = self.controller.snapshot()
                        if snapshot and snapshot.phase == Phase.WAITING_ACTION:
                            answer = self.choice(
                                "Перед выходом: ",
                                [
                                    "Сохранить и выйти",
                                    "Выйти без сохранения",
                                    "Отмена",
                                ],
                            )
                            if answer == 2:
                                continue
                            if answer == 0:
                                self.controller.save(self.slot())
                        return 0
                except (StorageError, ValueError) as error:
                    self.write(str(error))
        except (EOFError, KeyboardInterrupt):
            self.write("\nВвод завершён. Последние изменения не сохранены.")
            return 0

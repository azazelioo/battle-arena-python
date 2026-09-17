"""Application lifecycle, input ownership, pause and persistence boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arena.domain.battle import BattleEngine
from arena.domain.catalog import CHARACTERS, EQUIPMENT
from arena.domain.character import Character
from arena.domain.model import (
    ActionOption,
    ActionRequest,
    ActionResult,
    BattleSnapshot,
    Phase,
)
from arena.infrastructure.records import (
    MatchRepository,
    Settings,
    load_settings,
    save_settings,
)
from arena.infrastructure.storage import StorageError, load_match, save_match
from arena.infrastructure.errors import StorageCode
from .bot import BOTS


@dataclass(frozen=True)
class FighterSetup:
    name: str = ""
    archetype: str = "warrior"
    equipment: str = "none"

    def __post_init__(self) -> None:
        if self.archetype not in CHARACTERS or self.equipment not in EQUIPMENT:
            raise ValueError("Неизвестный архетип или снаряжение")


@dataclass(frozen=True)
class MatchSetup:
    first: FighterSetup = FighterSetup("Игрок 1", "warrior")
    second: FighterSetup = FighterSetup("Игрок 2", "mage")
    mode: str = "bot"
    strategy: str = "cautious"

    def __post_init__(self) -> None:
        if self.mode not in ("pvp", "bot") or self.strategy not in BOTS:
            raise ValueError("Неизвестный режим или стратегия")


class GameController:
    def __init__(self, data_dir: Path) -> None:
        self.repository = MatchRepository(data_dir)
        self._engine: BattleEngine | None = None
        self._paused = False
        self.last_setup = MatchSetup()
        self.warning = ""
        try:
            self.settings = load_settings(self.repository.settings_path)
        except StorageError as error:
            self.settings = Settings()
            self.warning = str(error)

    @property
    def paused(self) -> bool:
        return self._paused

    def snapshot(self) -> BattleSnapshot | None:
        return None if self._engine is None else self._engine.snapshot()

    def new_match(self, setup: MatchSetup) -> BattleSnapshot:
        first = Character(
            "p1",
            setup.first.name,
            setup.first.archetype,
            setup.first.equipment,
        )
        second = Character(
            "p2",
            setup.second.name,
            setup.second.archetype,
            setup.second.equipment,
        )
        engine = BattleEngine(first, second, setup.mode, setup.strategy)
        self._engine = engine
        self.last_setup = setup
        self._paused = False
        self.warning = ""
        return engine.snapshot()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def abandon(self) -> None:
        self._engine = None
        self._paused = False

    def is_bot_turn(self) -> bool:
        snapshot = self.snapshot()
        return bool(
            snapshot
            and snapshot.mode == "bot"
            and snapshot.active_id == snapshot.fighters[1].id
            and snapshot.phase == Phase.WAITING_ACTION
        )

    def options(self) -> tuple[ActionOption, ...]:
        if self._engine is None:
            return ()
        return self._engine.action_options(self._engine.snapshot().active_id)

    def submit(
        self, request: ActionRequest, *, from_bot: bool = False
    ) -> ActionResult:
        if self._engine is None:
            return ActionResult(False, "no_match", "Нет активного матча")
        if self._paused:
            return ActionResult(False, "paused", "Игра на паузе")
        if from_bot != self.is_bot_turn():
            return ActionResult(
                False, "wrong_controller", "Сейчас ход другого участника"
            )
        result = self._engine.submit(request)
        if result.accepted:
            self._record_result()
        return result

    def bot_step(self, match_id: str, expected_turn: int) -> ActionResult:
        snapshot = self.snapshot()
        if (
            not snapshot
            or snapshot.match_id != match_id
            or snapshot.turn != expected_turn
            or not self.is_bot_turn()
        ):
            return ActionResult(False, "stale_callback", "Ответ бота устарел")
        bot = BOTS[snapshot.strategy]()
        return self.submit(
            bot.choose_action(snapshot, self.options()), from_bot=True
        )

    def save(self, slot: int) -> None:
        snapshot = self.snapshot()
        if snapshot is None:
            raise StorageError(
                "Нет матча для сохранения", StorageCode.NO_MATCH
            )
        save_match(self.repository.slot(slot), snapshot)

    def load(self, slot: int) -> BattleSnapshot:
        # Construct first, replace last: a broken file cannot destroy the match.
        snapshot = load_match(self.repository.slot(slot))
        engine = BattleEngine.from_snapshot(snapshot)
        self._engine = engine
        self.last_setup = MatchSetup(
            FighterSetup(
                snapshot.fighters[0].name,
                snapshot.fighters[0].archetype,
                snapshot.fighters[0].equipment,
            ),
            FighterSetup(
                snapshot.fighters[1].name,
                snapshot.fighters[1].archetype,
                snapshot.fighters[1].equipment,
            ),
            snapshot.mode,
            snapshot.strategy,
        )
        self._paused = False
        self.warning = ""
        self._record_result()
        return snapshot

    def _record_result(self) -> None:
        snapshot = self.snapshot()
        if snapshot and snapshot.phase == Phase.FINISHED:
            try:
                self.repository.add_result(snapshot)
            except StorageError as error:
                self.warning = f"Бой завершён, но история не записана: {error}"

    def update_settings(self, settings: Settings) -> None:
        save_settings(self.repository.settings_path, settings)
        self.settings = settings

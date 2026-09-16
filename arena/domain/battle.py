"""The single transaction boundary for all game commands."""
from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from .actions import Action, ActionContext, action_registry
from .catalog import ACTION_LIMIT, CHARACTERS, ITEMS
from .character import Character
from .model import (
    ActionOption, ActionRequest, ActionResult, BattleEvent, BattleSnapshot, Phase,
)


class BattleEngine:
    def __init__(self, first: Character, second: Character,
                 mode: str = "pvp", strategy: str = "aggressive",
                 match_id: str | None = None) -> None:
        if first.id == second.id or not first.alive or not second.alive:
            raise ValueError("Для боя нужны два разных живых участника")
        if mode not in ("pvp", "bot") or strategy not in ("aggressive", "cautious"):
            raise ValueError("Неизвестный режим или стратегия")
        self._fighters = (first, second)
        self._match_id = match_id or str(uuid4())
        self._mode = mode
        self._strategy = strategy
        self._active = 0 if first.stats.speed >= second.stats.speed else 1
        self._turn = 1
        self._count = 0
        self._phase = Phase.WAITING_ACTION
        self._events: list[BattleEvent] = []
        self._winner: str | None = None
        self._reason = ""
        self._actions = action_registry()
        self._begin_turn()

    @property
    def _actor(self) -> Character:
        return self._fighters[self._active]

    @property
    def _opponent(self) -> Character:
        return self._fighters[1 - self._active]

    def _record(self, event: BattleEvent) -> None:
        self._events.append(replace(event, number=len(self._events) + 1))

    def _context(self, action: Action,
                 item_id: str | None = None) -> ActionContext:
        target = self._actor if action.self_target else self._opponent
        return ActionContext(self._actor, target, self._turn, action.id,
                             self._record, item_id)

    def _allowed(self) -> tuple[str, ...]:
        return ("attack", "defend", "heal", "recover",
                CHARACTERS[self._actor.archetype].special, "use_item")

    def action_options(self, actor_id: str) -> tuple[ActionOption, ...]:
        if self._phase != Phase.WAITING_ACTION or actor_id != self._actor.id:
            return ()
        options: list[ActionOption] = []
        for action_id in self._allowed():
            action = self._actions[action_id]
            items: tuple[str | None, ...] = (
                tuple(ITEMS) if action_id == "use_item" else (None,))
            for item_id in items:
                options.append(action.option(self._context(action, item_id)))
        return tuple(options)

    def submit(self, request: ActionRequest) -> ActionResult:
        checks = (
            (self._phase != Phase.WAITING_ACTION,
             "finished", "Бой не ожидает действия"),
            (request.match_id != self._match_id,
             "wrong_match", "Команда другого матча"),
            (type(request.expected_turn) is not int or
             request.expected_turn != self._turn,
             "stale_turn", "Команда устарела"),
            (request.actor_id != self._actor.id,
             "wrong_actor", "Сейчас ход другого участника"),
        )
        for invalid, code, message in checks:
            if invalid:
                return ActionResult(False, code, message)
        if request.action_id == "surrender":
            if request.target_id != self._actor.id or request.item_id is not None:
                return ActionResult(False, "wrong_target", "Неверная цель")
            start = len(self._events)
            self._finish(self._opponent.id, "surrender")
            return ActionResult(True, events=tuple(self._events[start:]))
        if request.action_id not in self._allowed():
            return ActionResult(False, "unknown_action", "Действие недоступно архетипу")
        action = self._actions[request.action_id]
        context = self._context(action, request.item_id)
        if request.target_id != context.target.id:
            return ActionResult(False, "wrong_target", "Неверная цель действия")
        if request.action_id != "use_item" and request.item_id is not None:
            return ActionResult(False, "unexpected_item", "Лишний предмет в команде")
        reason = action.availability(context)
        if reason:
            return ActionResult(False, "unavailable", reason)
        start = len(self._events)
        self._phase = Phase.RESOLVING
        self._actor.spend_energy(action.cost)
        context.emit("action")
        action.execute(context)
        self._actor.last_action_id = action.id
        self._count += 1
        if not self._opponent.alive:
            self._finish(self._actor.id, "defeat")
        elif self._count >= ACTION_LIMIT:
            self._finish(None, "limit")
        else:
            self._active = 1 - self._active
            self._turn += 1
            self._begin_turn()
        return ActionResult(True, events=tuple(self._events[start:]))

    def _begin_turn(self) -> None:
        context = ActionContext(self._actor, self._opponent, self._turn,
                                "", self._record)
        context.emit("turn", target=self._actor)
        for effect in sorted(self._actor.effects(), key=lambda e: e.priority):
            effect.on_turn_start(context)
            if not self._actor.alive:
                self._finish(self._opponent.id, "poison")
                return
        self._phase = Phase.WAITING_ACTION

    def _finish(self, winner_id: str | None, reason: str) -> None:
        self._phase = Phase.FINISHED
        self._winner = winner_id
        self._reason = reason
        self._record(BattleEvent(
            0, self._turn, "finished", winner_id or "", self._actor.id, reason,
        ))

    def snapshot(self) -> BattleSnapshot:
        return BattleSnapshot(
            self._match_id, self._mode, self._strategy, self._phase,
            self._actor.id, self._turn, self._count,
            (self._fighters[0].snapshot(), self._fighters[1].snapshot()),
            tuple(self._events), len(self._events) + 1, self._winner, self._reason,
        )

    @classmethod
    def from_snapshot(cls, snapshot: BattleSnapshot) -> BattleEngine:
        # Deliberately skip __init__: WAITING_ACTION already includes start ticks.
        from .validation import validate_snapshot
        validate_snapshot(snapshot)
        engine = cls.__new__(cls)
        engine._fighters = (Character.from_snapshot(snapshot.fighters[0]),
                            Character.from_snapshot(snapshot.fighters[1]))
        engine._match_id = snapshot.match_id
        engine._mode = snapshot.mode
        engine._strategy = snapshot.strategy
        engine._active = 0 if snapshot.active_id == engine._fighters[0].id else 1
        engine._turn = snapshot.turn
        engine._count = snapshot.successful_actions
        engine._phase = snapshot.phase
        engine._events = list(snapshot.events)
        engine._winner = snapshot.winner_id
        engine._reason = snapshot.finish_reason
        engine._actions = action_registry()
        return engine

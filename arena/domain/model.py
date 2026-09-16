"""Value objects shared by the engine, persistence and both interfaces."""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Generic, Iterator, TypeVar, final, overload


def integer(value: int, low: int = 0, high: int = 100000) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"Ожидается целое число от {low} до {high}")
    return value


@dataclass(frozen=True)
class StatBonus:
    max_hp: int = 0
    max_energy: int = 0
    attack: int = 0
    magic: int = 0
    armor: int = 0
    speed: int = 0

    def __post_init__(self) -> None:
        for field in fields(self):
            integer(getattr(self, field.name))


@final
@dataclass(frozen=True)
class Stats:
    max_hp: int
    max_energy: int
    attack: int
    magic: int
    armor: int
    speed: int

    def __post_init__(self) -> None:
        for field in fields(self):
            integer(getattr(self, field.name), 1 if field.name == "max_hp" else 0)

    def __add__(self, bonus: StatBonus) -> Stats:
        return Stats(**{
            field.name: getattr(self, field.name) + getattr(bonus, field.name)
            for field in fields(self)
        })


class Phase(StrEnum):
    WAITING_ACTION = "WAITING_ACTION"
    RESOLVING = "RESOLVING"
    FINISHED = "FINISHED"


@dataclass(frozen=True)
class EffectSnapshot:
    effect_id: str
    source_id: str
    remaining: int


@dataclass(frozen=True)
class CombatStats:
    direct_damage: int = 0
    poison_damage: int = 0
    healing: int = 0
    items_used: int = 0


@dataclass(frozen=True)
class CharacterSnapshot:
    id: str
    name: str
    archetype: str
    equipment: str
    stats: Stats
    hp: int
    energy: int
    inventory: tuple[tuple[str, int], ...]
    effects: tuple[EffectSnapshot, ...]
    last_action_id: str
    totals: CombatStats

    def quantity(self, item_id: str) -> int:
        return dict(self.inventory).get(item_id, 0)

    def effect(self, effect_id: str) -> EffectSnapshot | None:
        return next((e for e in self.effects if e.effect_id == effect_id), None)


@dataclass(frozen=True)
class BattleEvent:
    number: int
    turn: int
    kind: str
    actor_id: str
    target_id: str
    action_id: str = ""
    calculated: int = 0
    actual: int = 0
    remaining: int = 0


@dataclass(frozen=True)
class BattleSnapshot:
    match_id: str
    mode: str
    strategy: str
    phase: Phase
    active_id: str
    turn: int
    successful_actions: int
    fighters: tuple[CharacterSnapshot, CharacterSnapshot]
    events: tuple[BattleEvent, ...]
    next_event: int
    winner_id: str | None
    finish_reason: str

    @property
    def active(self) -> CharacterSnapshot:
        return self.fighter(self.active_id)

    def fighter(self, fighter_id: str) -> CharacterSnapshot:
        return next(f for f in self.fighters if f.id == fighter_id)

    @property
    def opponent(self) -> CharacterSnapshot:
        return next(f for f in self.fighters if f.id != self.active_id)

    @property
    def round(self) -> int:
        return (self.turn + 1) // 2


@dataclass(frozen=True)
class ActionRequest:
    match_id: str
    expected_turn: int
    actor_id: str
    action_id: str
    target_id: str
    item_id: str | None = None


@dataclass(frozen=True)
class ActionOption:
    action_id: str
    name: str
    cost: int
    available: bool
    reason: str
    target_id: str
    damage: int = 0
    healing: int = 0
    energy: int = 0
    item_id: str | None = None

    def request(self, snapshot: BattleSnapshot) -> ActionRequest:
        return ActionRequest(
            snapshot.match_id, snapshot.turn, snapshot.active_id,
            self.action_id, self.target_id, self.item_id,
        )


@dataclass(frozen=True)
class ActionResult:
    accepted: bool
    code: str = "ok"
    message: str = ""
    events: tuple[BattleEvent, ...] = ()


T = TypeVar("T")


class History(Generic[T]):
    """Bounded collection; slicing returns a copy rather than live storage."""

    def __init__(self, capacity: int = 50) -> None:
        self._capacity = integer(capacity, 1)
        self._entries: list[T] = []

    def append(self, entry: T) -> None:
        self._entries.append(entry)
        self._entries = self._entries[-self._capacity:]

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[T]:
        return iter(tuple(self._entries))

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> list[T]: ...

    def __getitem__(self, index: int | slice) -> T | list[T]:
        return self._entries[index]

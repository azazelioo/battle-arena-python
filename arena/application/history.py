from __future__ import annotations

from dataclasses import dataclass

from arena.domain.actions import action_registry
from arena.domain.model import BattleEvent, BattleSnapshot, History, integer
from arena.infrastructure.records import MatchSummary


@dataclass(frozen=True)
class HistoryFilter:
    query: str = ""
    mode: str = "all"
    outcome: str = "all"

    def __post_init__(self) -> None:
        if self.mode not in ("all", "pvp", "bot"):
            raise ValueError("Неизвестный фильтр режима")
        if self.outcome not in ("all", "win", "draw", "surrender"):
            raise ValueError("Неизвестный фильтр исхода")

    def matches(self, summary: MatchSummary) -> bool:
        state = summary.snapshot
        if self.mode != "all" and state.mode != self.mode:
            return False
        if self.outcome == "draw" and state.winner_id is not None:
            return False
        if self.outcome == "win" and state.winner_id is None:
            return False
        if self.outcome == "surrender" and state.finish_reason != "surrender":
            return False
        winner = (
            state.fighter(state.winner_id).name if state.winner_id else "Ничья"
        )
        text = " ".join(
            [f.name for f in state.fighters] + [winner, state.match_id]
        )
        return self.query.strip().casefold() in text.casefold()


@dataclass(frozen=True)
class HistoryStatistics:
    matches: int
    draws: int
    surrenders: int
    actions: int
    direct_damage: int
    poison_damage: int
    healing: int
    items_used: int

    @property
    def average_actions(self) -> float:
        return self.actions / self.matches if self.matches else 0.0


class HistoryBrowser:
    """An independent bounded view with real History indexing and slicing."""

    def __init__(
        self, history: History[MatchSummary], page_size: int = 10
    ) -> None:
        self._source: History[MatchSummary] = History(50)
        for index in range(len(history) - 1, -1, -1):
            self._source.append(history[index])
        self.page_size = integer(page_size, 1, 50)
        self._filter = HistoryFilter()
        self._visible: History[MatchSummary] = History(50)
        self._page = 0
        self.apply_filter(self._filter)

    @property
    def count(self) -> int:
        return len(self._visible)

    @property
    def page(self) -> int:
        return self._page

    @property
    def page_count(self) -> int:
        return max(1, (self.count + self.page_size - 1) // self.page_size)

    def apply_filter(self, criterion: HistoryFilter) -> None:
        self._filter = criterion
        self._visible = History(50)
        for entry in self._source:
            if criterion.matches(entry):
                self._visible.append(entry)
        self._page = 0

    def page_entries(self) -> tuple[MatchSummary, ...]:
        start = self.page * self.page_size
        return tuple(self._visible[start : start + self.page_size])

    def move(self, direction: int) -> None:
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError("Направление страницы должно быть -1 или 1")
        self._page = max(0, min(self.page_count - 1, self.page + direction))

    def select(self, row: int) -> MatchSummary:
        integer(row, 0, self.page_size - 1)
        index = self.page * self.page_size + row
        if index >= self.count:
            raise IndexError("В этой строке нет матча")
        return self._visible[index]

    def statistics(self) -> HistoryStatistics:
        states = [entry.snapshot for entry in self._visible]
        totals = [
            fighter.totals for state in states for fighter in state.fighters
        ]
        return HistoryStatistics(
            self.count,
            sum(state.winner_id is None for state in states),
            sum(state.finish_reason == "surrender" for state in states),
            sum(state.successful_actions for state in states),
            sum(value.direct_damage for value in totals),
            sum(value.poison_damage for value in totals),
            sum(value.healing for value in totals),
            sum(value.items_used for value in totals),
        )


@dataclass(frozen=True)
class ReplayResources:
    fighter_id: str
    hp: int
    energy: int


@dataclass(frozen=True)
class ReplayFrame:
    position: int
    event: BattleEvent | None
    resources: tuple[ReplayResources, ReplayResources]


class BattleReplay:
    """Inspect recorded resource changes without executing game actions again.

    Position zero is the state before the first recorded event. Initial values
    are recovered from final values and actual deltas, so partially damaged
    fixtures and capped healing remain truthful. This is a journal viewer,
    not an alternative engine and not an editable playable match.
    """

    def __init__(self, snapshot: BattleSnapshot) -> None:
        self.snapshot = snapshot
        self.position = 0
        self._costs = {
            key: value.cost for key, value in action_registry().items()
        }
        initial = {f.id: [f.hp, f.energy] for f in snapshot.fighters}
        for event in reversed(snapshot.events):
            self._apply(initial, event, -1)
        self._frames = [self._frame(initial, 0, None)]
        for index, event in enumerate(snapshot.events, 1):
            self._apply(initial, event, 1)
            self._frames.append(self._frame(initial, index, event))

    def _apply(
        self, values: dict[str, list[int]], event: BattleEvent, direction: int
    ) -> None:
        if event.kind in ("damage", "poison"):
            values[event.target_id][0] -= direction * event.actual
        elif event.kind == "healing":
            values[event.target_id][0] += direction * event.actual
        elif event.kind == "energy":
            values[event.target_id][1] += direction * event.actual
        elif event.kind == "action":
            values[event.actor_id][1] -= (
                direction * self._costs[event.action_id]
            )

    def _frame(
        self,
        values: dict[str, list[int]],
        position: int,
        event: BattleEvent | None,
    ) -> ReplayFrame:
        first, second = self.snapshot.fighters
        return ReplayFrame(
            position,
            event,
            (
                ReplayResources(first.id, *values[first.id]),
                ReplayResources(second.id, *values[second.id]),
            ),
        )

    @property
    def length(self) -> int:
        return len(self._frames)

    @property
    def current(self) -> ReplayFrame:
        return self._frames[self.position]

    def seek(self, position: int) -> ReplayFrame:
        self.position = integer(position, 0, self.length - 1)
        return self.current

    def step(self, direction: int) -> ReplayFrame:
        if type(direction) is not int or direction not in (-1, 1):
            raise ValueError("Направление должно быть -1 или 1")
        return self.seek(
            max(0, min(self.length - 1, self.position + direction))
        )

    def turn(self, number: int) -> ReplayFrame:
        integer(number, 1, self.snapshot.turn)
        for frame in self._frames:
            if frame.event and frame.event.turn == number:
                return self.seek(frame.position)
        raise ValueError("В журнале нет этого хода")

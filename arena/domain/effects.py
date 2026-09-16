"""Polymorphic effect hooks. The engine controls when each hook runs."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, override

from .catalog import POISON_DAMAGE, POISON_TICKS
from .model import EffectSnapshot, integer

if TYPE_CHECKING:
    from .actions import ActionContext


class StatusEffect(ABC):
    id: str
    priority: int

    def __init__(self, source_id: str, remaining: int) -> None:
        self.source_id = source_id
        self.remaining = integer(remaining, 1, POISON_TICKS)

    @abstractmethod
    def on_turn_start(self, context: ActionContext) -> None:
        """Apply or expire an effect owned by context.actor."""

    def on_direct_hit(self, context: ActionContext) -> None:
        """By default, a direct hit does not consume this effect."""

    def snapshot(self) -> EffectSnapshot:
        return EffectSnapshot(self.id, self.source_id, self.remaining)


class GuardEffect(StatusEffect):
    id = "guard"
    priority = 0

    def __init__(self, source_id: str, remaining: int = 1) -> None:
        super().__init__(source_id, integer(remaining, 1, 1))

    @override
    def on_turn_start(self, context: ActionContext) -> None:
        context.actor.remove_effect(self.id)
        context.emit("guard_expired", target=context.actor)

    @override
    def on_direct_hit(self, context: ActionContext) -> None:
        context.target.remove_effect(self.id)
        context.emit("guard_used")


class PoisonEffect(StatusEffect):
    id = "poison"
    priority = 1

    def __init__(self, source_id: str, remaining: int = POISON_TICKS) -> None:
        super().__init__(source_id, remaining)

    @override
    def on_turn_start(self, context: ActionContext) -> None:
        actual = context.actor.take_damage(POISON_DAMAGE)
        context.target.credit(poison_damage=actual)
        self.remaining -= 1
        context.emit("poison", calculated=POISON_DAMAGE, actual=actual,
                     target=context.actor, source_id=self.source_id,
                     remaining=self.remaining)
        if self.remaining == 0:
            context.actor.remove_effect(self.id)


def effect_from_snapshot(snapshot: EffectSnapshot) -> StatusEffect:
    factories: dict[str, type[StatusEffect]] = {
        "guard": GuardEffect, "poison": PoisonEffect,
    }
    if snapshot.effect_id not in factories:
        raise ValueError("Неизвестный эффект")
    return factories[snapshot.effect_id](snapshot.source_id, snapshot.remaining)

"""Commands share one availability/preview/execute contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, override

from .catalog import HEAL_BASE, HEAL_COST, ITEMS, RECOVER_AMOUNT, direct_damage
from .character import Character
from .effects import GuardEffect, PoisonEffect
from .model import ActionOption, BattleEvent


@dataclass
class ActionContext:
    actor: Character
    target: Character
    turn: int
    action_id: str
    record: Callable[[BattleEvent], None]
    item_id: str | None = None

    def emit(
        self,
        kind: str,
        calculated: int = 0,
        actual: int = 0,
        target: Character | None = None,
        source_id: str | None = None,
        remaining: int = 0,
    ) -> None:
        self.record(
            BattleEvent(
                0,
                self.turn,
                kind,
                source_id or self.actor.id,
                (target or self.target).id,
                self.action_id,
                calculated,
                actual,
                remaining,
            )
        )

    def hit(self, power: int, magical: bool = False) -> None:
        calculated = direct_damage(
            power,
            self.target.stats.armor,
            magical,
            self.target.has_effect("guard"),
        )
        for effect in self.target.effects():
            effect.on_direct_hit(self)
        actual = self.target.take_damage(calculated)
        self.actor.credit(direct_damage=actual)
        self.emit("damage", calculated, actual)


class Action(ABC):
    id: str
    name: str
    cost = 0
    self_target = False

    def availability(self, context: ActionContext) -> str:
        if not context.actor.alive or not context.target.alive:
            return "Участник побеждён"
        if context.actor.energy < self.cost:
            return "Недостаточно энергии"
        return ""

    def preview(self, context: ActionContext) -> tuple[int, int, int]:
        return (0, 0, 0)

    def option(self, context: ActionContext) -> ActionOption:
        reason = self.availability(context)
        damage, healing, energy = self.preview(context)
        return ActionOption(
            self.id,
            self.name,
            self.cost,
            not reason,
            reason,
            context.target.id,
            damage,
            healing,
            energy,
            context.item_id,
        )

    @abstractmethod
    def execute(self, context: ActionContext) -> None:
        """Called only after the engine has checked availability."""


class AttackAction(Action):
    id = "attack"
    name = "Атака"
    magical = False
    bonus = 0

    def power(self, context: ActionContext) -> int:
        return context.actor.stats.attack + self.bonus

    @override
    def preview(self, context: ActionContext) -> tuple[int, int, int]:
        damage = direct_damage(
            self.power(context),
            context.target.stats.armor,
            self.magical,
            context.target.has_effect("guard"),
        )
        return min(damage, context.target.hp), 0, 0

    @override
    def execute(self, context: ActionContext) -> None:
        context.hit(self.power(context), self.magical)


class HeavyStrikeAction(AttackAction):
    id = "heavy_strike"
    name = "Тяжёлый удар"
    cost = 12
    bonus = 10


class FireballAction(AttackAction):
    id = "fireball"
    name = "Огненный шар"
    cost = 18
    magical = True

    @override
    def power(self, context: ActionContext) -> int:
        return context.actor.stats.magic + 14


class PoisonArrowAction(AttackAction):
    id = "poison_arrow"
    name = "Отравленная стрела"
    cost = 14
    bonus = 4

    @override
    def execute(self, context: ActionContext) -> None:
        super().execute(context)
        if context.target.alive:
            effect = PoisonEffect(context.actor.id)
            context.target.add_effect(effect)
            context.emit("poison_applied", remaining=effect.remaining)


class DefendAction(Action):
    id = "defend"
    name = "Защита"
    self_target = True

    @override
    def execute(self, context: ActionContext) -> None:
        context.actor.add_effect(GuardEffect(context.actor.id))
        context.emit("guard_applied")


class HealAction(Action):
    id = "heal"
    name = "Лечение"
    cost = HEAL_COST
    self_target = True

    @override
    def availability(self, context: ActionContext) -> str:
        return super().availability(context) or (
            "Полное здоровье"
            if context.actor.hp == context.actor.stats.max_hp
            else ""
        )

    @override
    def preview(self, context: ActionContext) -> tuple[int, int, int]:
        return (
            0,
            min(
                HEAL_BASE + context.actor.stats.magic // 2,
                context.actor.stats.max_hp - context.actor.hp,
            ),
            0,
        )

    @override
    def execute(self, context: ActionContext) -> None:
        amount = HEAL_BASE + context.actor.stats.magic // 2
        actual = context.actor.heal(amount)
        context.actor.credit(healing=actual)
        context.emit("healing", amount, actual)


class RecoverEnergyAction(Action):
    id = "recover"
    name = "Восстановление энергии"
    self_target = True

    @override
    def availability(self, context: ActionContext) -> str:
        return super().availability(context) or (
            "Полная энергия"
            if context.actor.energy == context.actor.stats.max_energy
            else ""
        )

    @override
    def preview(self, context: ActionContext) -> tuple[int, int, int]:
        return (
            0,
            0,
            min(
                RECOVER_AMOUNT,
                context.actor.stats.max_energy - context.actor.energy,
            ),
        )

    @override
    def execute(self, context: ActionContext) -> None:
        actual = context.actor.restore_energy(RECOVER_AMOUNT)
        context.emit("energy", RECOVER_AMOUNT, actual)


class UseItemAction(Action):
    id = "use_item"
    name = "Предмет"
    self_target = True

    @override
    def availability(self, context: ActionContext) -> str:
        common = super().availability(context)
        if common:
            return common
        if context.item_id not in ITEMS:
            return "Неизвестный предмет"
        assert context.item_id is not None
        item = ITEMS[context.item_id]
        if context.actor.inventory.quantity(context.item_id) == 0:
            return "Предмет закончился"
        if (
            item.resource == "hp"
            and context.actor.hp == context.actor.stats.max_hp
        ):
            return "Полное здоровье"
        if (
            item.resource == "energy"
            and context.actor.energy == context.actor.stats.max_energy
        ):
            return "Полная энергия"
        if item.resource == "poison" and not context.actor.has_effect(
            "poison"
        ):
            return "Нет отравления"
        return ""

    @override
    def preview(self, context: ActionContext) -> tuple[int, int, int]:
        if context.item_id not in ITEMS:
            return (0, 0, 0)
        assert context.item_id is not None
        item = ITEMS[context.item_id]
        if item.resource == "hp":
            return (
                0,
                min(
                    item.amount, context.actor.stats.max_hp - context.actor.hp
                ),
                0,
            )
        if item.resource == "energy":
            return (
                0,
                0,
                min(
                    item.amount,
                    context.actor.stats.max_energy - context.actor.energy,
                ),
            )
        return (0, 0, 0)

    @override
    def option(self, context: ActionContext) -> ActionOption:
        from dataclasses import replace

        option = super().option(context)
        if context.item_id in ITEMS:
            assert context.item_id is not None
            return replace(option, name=ITEMS[context.item_id].name)
        return option

    @override
    def execute(self, context: ActionContext) -> None:
        assert context.item_id is not None
        item = ITEMS[context.item_id]
        if item.resource == "hp":
            actual = context.actor.heal(item.amount)
            context.actor.credit(healing=actual)
            context.emit("healing", item.amount, actual)
        elif item.resource == "energy":
            actual = context.actor.restore_energy(item.amount)
            context.emit("energy", item.amount, actual)
        else:
            context.actor.remove_effect("poison")
            context.emit("poison_removed")
        context.actor.inventory.consume(context.item_id)
        context.actor.credit(items_used=1)
        context.emit("item_used")


def action_registry() -> dict[str, Action]:
    actions: tuple[Action, ...] = (
        AttackAction(),
        DefendAction(),
        HealAction(),
        RecoverEnergyAction(),
        HeavyStrikeAction(),
        FireballAction(),
        PoisonArrowAction(),
        UseItemAction(),
    )
    return {action.id: action for action in actions}

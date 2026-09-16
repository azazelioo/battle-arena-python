"""Mutable combat entities; snapshots never expose their live collections."""
from __future__ import annotations

from dataclasses import replace

from .catalog import ITEMS, final_stats
from .model import CharacterSnapshot, CombatStats, Stats, integer
from .effects import StatusEffect, effect_from_snapshot


class Inventory:
    def __init__(self, quantities: dict[str, int] | None = None) -> None:
        source = quantities if quantities is not None else dict.fromkeys(ITEMS, 1)
        if set(source) != set(ITEMS):
            raise ValueError("Неизвестный или отсутствующий предмет")
        self._items = {key: integer(value, 0, 3) for key, value in source.items()}

    def quantity(self, item_id: str) -> int:
        return self._items.get(item_id, 0)

    def consume(self, item_id: str) -> None:
        if self.quantity(item_id) <= 0:
            raise ValueError("Предмет закончился")
        self._items[item_id] -= 1

    def snapshot(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self._items.items()))


class Character:
    def __init__(self, fighter_id: str, name: str, archetype: str,
                 equipment: str = "none") -> None:
        if not fighter_id:
            raise ValueError("Пустой идентификатор бойца")
        self._id = fighter_id
        self._name = name.strip()[:24] or f"Игрок {fighter_id[-1]}"
        self._archetype = archetype
        self._equipment = equipment
        self._stats = final_stats(archetype, equipment)
        self._hp = self._stats.max_hp
        self._energy = self._stats.max_energy
        self.inventory = Inventory()
        self._effects: dict[str, StatusEffect] = {}
        self.last_action_id = ""
        self._totals = CombatStats()

    @property
    def id(self) -> str:
        return self._id

    @property
    def stats(self) -> Stats:
        return self._stats

    @property
    def hp(self) -> int:
        return self._hp

    @property
    def energy(self) -> int:
        return self._energy

    @property
    def archetype(self) -> str:
        return self._archetype

    @property
    def alive(self) -> bool:
        return self._hp > 0

    def take_damage(self, amount: int) -> int:
        actual = min(self._hp, integer(amount))
        self._hp -= actual
        return actual

    def heal(self, amount: int) -> int:
        integer(amount)
        if not self.alive:
            raise ValueError("Нельзя лечить побеждённого")
        actual = min(amount, self.stats.max_hp - self.hp)
        self._hp += actual
        return actual

    def spend_energy(self, amount: int) -> None:
        if integer(amount) > self.energy:
            raise ValueError("Недостаточно энергии")
        self._energy -= amount

    def restore_energy(self, amount: int) -> int:
        actual = min(integer(amount), self.stats.max_energy - self.energy)
        self._energy += actual
        return actual

    def add_effect(self, effect: StatusEffect) -> None:
        self._effects[effect.id] = effect

    def remove_effect(self, effect_id: str) -> None:
        self._effects.pop(effect_id, None)

    def has_effect(self, effect_id: str) -> bool:
        return effect_id in self._effects

    def effects(self) -> tuple[StatusEffect, ...]:
        return tuple(self._effects.values())

    def credit(self, **amounts: int) -> None:
        self._totals = replace(self._totals, **{
            key: getattr(self._totals, key) + integer(value)
            for key, value in amounts.items()
        })

    def snapshot(self) -> CharacterSnapshot:
        return CharacterSnapshot(
            self.id, self._name, self.archetype, self._equipment, self.stats,
            self.hp, self.energy, self.inventory.snapshot(),
            tuple(e.snapshot() for e in self.effects()), self.last_action_id,
            self._totals,
        )

    @classmethod
    def from_snapshot(cls, snapshot: CharacterSnapshot) -> Character:
        result = cls(snapshot.id, snapshot.name, snapshot.archetype,
                     snapshot.equipment)
        if result.stats != snapshot.stats:
            raise ValueError("Характеристики не соответствуют снаряжению")
        result._hp = integer(snapshot.hp, 0, result.stats.max_hp)
        result._energy = integer(snapshot.energy, 0, result.stats.max_energy)
        result.inventory = Inventory(dict(snapshot.inventory))
        result._effects = {
            e.effect_id: effect_from_snapshot(e) for e in snapshot.effects
        }
        result.last_action_id = snapshot.last_action_id
        result._totals = snapshot.totals
        return result

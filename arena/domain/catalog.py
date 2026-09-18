from dataclasses import dataclass
from types import MappingProxyType

from .model import StatBonus, Stats


@dataclass(frozen=True)
class CharacterDefinition:
    id: str
    name: str
    stats: Stats
    special: str


@dataclass(frozen=True)
class EquipmentDefinition:
    name: str
    bonus: StatBonus


@dataclass(frozen=True)
class ItemDefinition:
    name: str
    resource: str
    amount: int


CHARACTERS = MappingProxyType(
    {
        "warrior": CharacterDefinition(
            "warrior", "Воин", Stats(140, 40, 18, 8, 8, 6), "heavy_strike"
        ),
        "mage": CharacterDefinition(
            "mage", "Маг", Stats(95, 70, 10, 22, 3, 8), "fireball"
        ),
        "ranger": CharacterDefinition(
            "ranger", "Следопыт", Stats(110, 50, 16, 12, 5, 12), "poison_arrow"
        ),
    }
)
EQUIPMENT = MappingProxyType(
    {
        "none": EquipmentDefinition("Без снаряжения", StatBonus()),
        "blade": EquipmentDefinition("Учебный клинок", StatBonus(attack=3)),
        "amulet": EquipmentDefinition(
            "Амулет", StatBonus(max_energy=15, magic=3)
        ),
        "shield": EquipmentDefinition("Щит", StatBonus(armor=3)),
    }
)
ITEMS = MappingProxyType(
    {
        "health_potion": ItemDefinition("Лечебное зелье", "hp", 40),
        "energy_potion": ItemDefinition("Энергетическое зелье", "energy", 25),
        "antidote": ItemDefinition("Противоядие", "poison", 0),
    }
)
HEAL_COST = 20
HEAL_BASE = 25
RECOVER_AMOUNT = 15
POISON_DAMAGE = 7
POISON_TICKS = 2
ACTION_LIMIT = 100


def final_stats(archetype: str, equipment: str) -> Stats:
    return CHARACTERS[archetype].stats + EQUIPMENT[equipment].bonus


def direct_damage(power: int, armor: int, magical: bool, guarded: bool) -> int:
    damage = max(1, power if magical else power - armor)
    return max(1, damage // 2) if guarded else damage

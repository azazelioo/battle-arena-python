from arena.domain.actions import action_registry
from arena.domain.catalog import CHARACTERS, EQUIPMENT
from arena.domain.model import BattleEvent, BattleSnapshot, CharacterSnapshot

ACTION_NAMES = {key: value.name for key, value in action_registry().items()}
REASONS = {
    "defeat": "здоровье противника исчерпано",
    "poison": "противник погиб от отравления",
    "surrender": "противник сдался",
    "limit": "достигнут предел 100 действий",
}
RULES = """БОЕВАЯ АРЕНА

Первым ходит боец с большей скоростью. При равенстве — сторона 1.
Затем стороны чередуются. Один выбор действия занимает один ход.

Атака: max(1, атака − броня противника).
Защита: следующее прямое попадание наносит max(1, урон // 2).
Неиспользованная защита истекает в начале собственного хода.
Лечение: до 25 + магия // 2 HP за 20 энергии.
Восстановление: до 15 энергии, бесплатно.

Воин: тяжёлый удар, атака + 10, цена 12 энергии.
Маг: огненный шар, магия + 14, игнорирует броню, цена 18.
Следопыт: отравленная стрела, атака + 4, цена 14.
Яд снимает 7 HP в начале двух следующих ходов цели.
Повторная стрела обновляет длительность, но не складывает урон.
Яд проходит через защиту. Смерть от яда наступает до выбора действия.

Зелье здоровья: до 40 HP. Зелье энергии: до 25 энергии.
Противоядие: снимает оставшееся отравление.
У каждого бойца по одному расходнику каждого вида.
Предмет не расходует энергию, но занимает ход.

При нуле HP — поражение. Можно сдаться на своём ходу.
После 100 успешных действий — ничья; победа на сотом имеет приоритет.
Пауза позволяет сохранить бой в один из трёх слотов.
Загрузка продолжает тот же ход без повторного срабатывания эффектов.
"""


def fighter_text(fighter: CharacterSnapshot) -> str:
    stats = fighter.stats
    effects = (
        ", ".join(
            (
                "Защита"
                if e.effect_id == "guard"
                else f"Яд: осталось {e.remaining}"
            )
            for e in fighter.effects
        )
        or "Нет эффектов"
    )
    return (
        f"{fighter.name} [{fighter.id}] · "
        f"{CHARACTERS[fighter.archetype].name}\n"
        f"HP {fighter.hp}/{stats.max_hp} · "
        f"Энергия {fighter.energy}/{stats.max_energy}\n"
        f"Атака {stats.attack} · Магия {stats.magic} · "
        f"Броня {stats.armor} · Скорость {stats.speed}\n"
        f"{EQUIPMENT[fighter.equipment].name} · {effects}"
    )


def event_text(event: BattleEvent, snapshot: BattleSnapshot) -> str:
    names = {f.id: f"{f.name} [{f.id}]" for f in snapshot.fighters}
    actor = names.get(event.actor_id, "Ничья")
    target = names.get(event.target_id, event.target_id)
    action = ACTION_NAMES.get(event.action_id, event.action_id)
    messages = {
        "turn": f"Ход {event.turn}: {actor}",
        "action": f"{actor}: {action}",
        "damage": (
            f"{target} теряет {event.actual} HP "
            f"(расчёт: {event.calculated})"
        ),
        "healing": f"{target} восстанавливает {event.actual} HP",
        "energy": f"{target} восстанавливает {event.actual} энергии",
        "guard_applied": f"{target} принимает защитную стойку",
        "guard_used": f"Защита {target} поглощает часть попадания и исчезает",
        "guard_expired": f"Защита {target} истекла",
        "poison_applied": (
            f"{target} отравлен на {event.remaining} срабатывания"
        ),
        "poison": (
            f"Яд от {actor}: {target} теряет {event.actual} HP; "
            f"осталось {event.remaining}"
        ),
        "poison_removed": f"{target} снимает отравление",
        "item_used": f"{actor} расходует предмет",
        "finished": (
            f"Итог: {actor}; "
            f"{REASONS.get(event.action_id, event.action_id)}"
        ),
    }
    return f"{event.number:03d}  {messages.get(event.kind, event.kind)}"


def result_text(snapshot: BattleSnapshot) -> str:
    title = (
        f"Победитель: {snapshot.fighter(snapshot.winner_id).name} "
        f"[{snapshot.winner_id}]"
        if snapshot.winner_id
        else "Ничья"
    )
    lines = [
        title,
        REASONS.get(snapshot.finish_reason, ""),
        f"Успешных действий: {snapshot.successful_actions}",
    ]
    for fighter in snapshot.fighters:
        totals = fighter.totals
        lines.extend(
            (
                f"\n{fighter.name} [{fighter.id}]",
                f"Прямой урон: {totals.direct_damage}; "
                f"яд: {totals.poison_damage}",
                f"Лечение: {totals.healing}; предметы: {totals.items_used}",
            )
        )
    return "\n".join(lines)

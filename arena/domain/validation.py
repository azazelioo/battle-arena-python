from .actions import action_registry
from .catalog import ACTION_LIMIT, CHARACTERS, ITEMS, final_stats
from .model import BattleSnapshot, Phase, integer


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_snapshot(snapshot: BattleSnapshot) -> None:
    require(
        bool(snapshot.match_id) and len(snapshot.match_id) <= 100,
        "Некорректный идентификатор матча",
    )
    require(snapshot.mode in ("pvp", "bot"), "Неизвестный режим")
    require(snapshot.strategy in ("aggressive", "cautious"), "Неизвестный бот")
    require(
        snapshot.phase in (Phase.WAITING_ACTION, Phase.FINISHED),
        "Сохранена промежуточная фаза",
    )
    require(len(snapshot.fighters) == 2, "Нужны два участника")
    ids = {f.id for f in snapshot.fighters}
    require(len(ids) == 2 and all(ids), "Идентификаторы должны различаться")
    require(snapshot.active_id in ids, "Неизвестный активный участник")
    integer(snapshot.turn, 1, ACTION_LIMIT + 1)
    integer(snapshot.successful_actions, 0, ACTION_LIMIT)
    actions = action_registry()
    for fighter in snapshot.fighters:
        require(
            0 < len(fighter.name) <= 24
            and fighter.name == fighter.name.strip(),
            "Некорректное имя",
        )
        require(
            fighter.stats == final_stats(fighter.archetype, fighter.equipment),
            "Характеристики не соответствуют каталогу",
        )
        integer(fighter.hp, 0, fighter.stats.max_hp)
        integer(fighter.energy, 0, fighter.stats.max_energy)
        require(
            len(fighter.inventory) == len(ITEMS)
            and set(dict(fighter.inventory)) == set(ITEMS),
            "Неверный инвентарь",
        )
        for _, amount in fighter.inventory:
            integer(amount, 0, 3)
        require(
            fighter.last_action_id
            in (
                "",
                "attack",
                "defend",
                "heal",
                "recover",
                "use_item",
                CHARACTERS[fighter.archetype].special,
            ),
            "Неизвестное последнее действие",
        )
        effect_ids: set[str] = set()
        for effect in fighter.effects:
            require(
                effect.effect_id in ("poison", "guard"), "Неизвестный эффект"
            )
            require(effect.effect_id not in effect_ids, "Дублирующийся эффект")
            effect_ids.add(effect.effect_id)
            require(effect.source_id in ids, "Неизвестный источник эффекта")
            if effect.effect_id == "guard":
                integer(effect.remaining, 1, 1)
                require(effect.source_id == fighter.id, "Чужая защита")
                require(
                    not (
                        snapshot.phase == Phase.WAITING_ACTION
                        and fighter.id == snapshot.active_id
                    ),
                    "Защита должна истечь в начале хода",
                )
            else:
                integer(effect.remaining, 1, 2)
                require(effect.source_id != fighter.id, "Самоотравление")
        for value in (
            fighter.totals.direct_damage,
            fighter.totals.poison_damage,
            fighter.totals.healing,
            fighter.totals.items_used,
        ):
            integer(value, 0, 100000)
    integer(snapshot.next_event, 1, 2000)
    require(
        snapshot.next_event == len(snapshot.events) + 1,
        "Нарушен номер следующего события",
    )
    known_kinds = {
        "action",
        "damage",
        "healing",
        "energy",
        "guard_applied",
        "guard_used",
        "guard_expired",
        "poison",
        "poison_applied",
        "poison_removed",
        "item_used",
        "turn",
        "finished",
    }
    action_count = 0
    last_turn = 1
    for index, event in enumerate(snapshot.events, 1):
        require(event.number == index, "Нарушен порядок событий")
        integer(event.turn, last_turn, snapshot.turn)
        last_turn = event.turn
        require(event.kind in known_kinds, "Неизвестное событие")
        require(
            event.actor_id in ids
            or (event.kind == "finished" and event.actor_id == ""),
            "Неизвестный автор события",
        )
        require(event.target_id in ids, "Неизвестная цель события")
        require(
            event.action_id in actions
            or event.action_id
            in ("", "defeat", "poison", "limit", "surrender"),
            "Неизвестное действие события",
        )
        integer(event.calculated)
        integer(event.actual, 0, event.calculated)
        integer(event.remaining, 0, 2)
        action_count += event.kind == "action"
    require(
        action_count == snapshot.successful_actions,
        "Счётчик действий не совпадает",
    )
    require(
        bool(snapshot.events) and snapshot.events[0].kind == "turn",
        "Отсутствует начало боя",
    )
    first = max(snapshot.fighters, key=lambda f: f.stats.speed)
    other = next(f for f in snapshot.fighters if f.id != first.id)
    expected_active = first.id if snapshot.turn % 2 else other.id
    require(
        snapshot.active_id == expected_active, "Нарушено чередование ходов"
    )
    validate_recorded_statistics(snapshot)
    dead = [f.id for f in snapshot.fighters if f.hp == 0]
    if snapshot.phase == Phase.WAITING_ACTION:
        require(
            not dead and snapshot.successful_actions < ACTION_LIMIT,
            "Невозможный продолжающийся бой",
        )
        require(
            snapshot.turn == snapshot.successful_actions + 1,
            "Неверный номер хода",
        )
        require(
            snapshot.winner_id is None and not snapshot.finish_reason,
            "Итог у незаконченного боя",
        )
        require(
            not any(e.kind == "finished" for e in snapshot.events),
            "Событие завершения в продолжающемся бое",
        )
        return
    require(
        snapshot.events[-1].kind == "finished", "Отсутствует событие итога"
    )
    require(
        sum(e.kind == "finished" for e in snapshot.events) == 1,
        "Повторное завершение",
    )
    require(
        snapshot.events[-1].actor_id == (snapshot.winner_id or "")
        and snapshot.events[-1].action_id == snapshot.finish_reason,
        "Итог не совпадает с журналом",
    )
    reason = snapshot.finish_reason
    if reason == "limit":
        require(
            not dead
            and snapshot.winner_id is None
            and snapshot.successful_actions == ACTION_LIMIT
            and snapshot.turn == ACTION_LIMIT,
            "Неверная ничья",
        )
    elif reason in ("defeat", "poison"):
        require(
            len(dead) == 1 and snapshot.winner_id in ids - set(dead),
            "Победа не соответствует HP",
        )
        expected_turn = snapshot.successful_actions + (reason == "poison")
        require(snapshot.turn == expected_turn, "Неверный ход победы")
        if reason == "poison":
            require(
                snapshot.successful_actions < ACTION_LIMIT,
                "После лимита следующий тик не начинается",
            )
            require(
                snapshot.active_id in dead, "Яд должен убить активного бойца"
            )
        else:
            require(
                snapshot.active_id == snapshot.winner_id,
                "Прямой удар должен завершиться победой атакующего",
            )
    elif reason == "surrender":
        require(
            snapshot.successful_actions < ACTION_LIMIT
            and not dead
            and snapshot.winner_id in ids - {snapshot.active_id}
            and snapshot.turn == snapshot.successful_actions + 1,
            "Неверная сдача",
        )
    else:
        raise ValueError("Неизвестная причина завершения")


def validate_recorded_statistics(snapshot: BattleSnapshot) -> None:
    """Counters must agree with recorded actual deltas, not calculated power."""
    keys = ("direct_damage", "poison_damage", "healing", "items_used")
    totals = {
        fighter.id: dict.fromkeys(keys, 0) for fighter in snapshot.fighters
    }
    last_actions = dict.fromkeys(totals, "")
    resource_events = {
        "damage": "direct_damage",
        "poison": "poison_damage",
        "healing": "healing",
    }
    for event in snapshot.events:
        if event.kind in resource_events:
            require(
                event.actor_id in totals, "Неизвестный источник статистики"
            )
            key = resource_events[event.kind]
            totals[event.actor_id][key] += event.actual
        elif event.kind == "item_used":
            require(event.actor_id in totals, "Неизвестный владелец предмета")
            totals[event.actor_id]["items_used"] += 1
        elif event.kind == "action":
            require(event.actor_id in totals, "Неизвестный автор действия")
            last_actions[event.actor_id] = event.action_id
    for fighter in snapshot.fighters:
        require(
            fighter.last_action_id == last_actions[fighter.id],
            "Последнее действие не соответствует журналу",
        )
        for key in keys:
            require(
                getattr(fighter.totals, key) == totals[fighter.id][key],
                "Статистика не соответствует журналу",
            )

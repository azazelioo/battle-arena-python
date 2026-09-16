from dataclasses import FrozenInstanceError, replace

import pytest

from arena.domain.actions import ActionContext, AttackAction, HealAction, action_registry
from arena.domain.battle import BattleEngine
from arena.domain.catalog import CHARACTERS, EQUIPMENT, final_stats
from arena.domain.character import Character, Inventory
from arena.domain.effects import GuardEffect, PoisonEffect
from arena.domain.model import ActionRequest, History, Phase, StatBonus, Stats
from conftest import act, surrender


def test_six_turn_reference_example(battle):
    for action in ("fireball", "defend", "attack", "heavy_strike", "heal", "attack"):
        assert act(battle, action).accepted
    s = battle.snapshot()
    warrior, mage = s.fighters
    assert (warrior.hp, warrior.energy) == (103, 28)
    assert (mage.hp, mage.energy) == (80, 32)
    assert (s.turn, s.successful_actions, s.active_id) == (7, 6, "p2")
    assert s.phase == Phase.WAITING_ACTION
    assert not warrior.effects and not mage.effects
    assert all(q == 1 for f in s.fighters for _, q in f.inventory)


@pytest.mark.parametrize("value", [-1, 0, True, 1.5, "10"])
def test_invalid_max_hp(value):
    with pytest.raises(ValueError):
        Stats(value, 1, 1, 1, 1, 1)


@pytest.mark.parametrize("field", ["max_energy", "attack", "magic", "armor", "speed"])
@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_invalid_stats(field, value):
    data = dict(max_hp=1, max_energy=0, attack=0, magic=0, armor=0, speed=0)
    data[field] = value
    with pytest.raises(ValueError):
        Stats(**data)


@pytest.mark.parametrize("archetype", CHARACTERS)
@pytest.mark.parametrize("equipment", EQUIPMENT)
def test_equipment_preview_is_actual_state(archetype, equipment):
    original = CHARACTERS[archetype].stats
    fighter = Character("p1", " A ", archetype, equipment)
    assert fighter.stats == final_stats(archetype, equipment)
    assert fighter.hp == fighter.stats.max_hp
    assert fighter.energy == fighter.stats.max_energy
    assert fighter.snapshot().name == "A"
    assert CHARACTERS[archetype].stats is original


def test_stats_addition_and_frozen_values():
    stats = Stats(10, 10, 3, 2, 1, 4)
    result = stats + StatBonus(attack=3)
    assert result.attack == 6 and stats.attack == 3
    with pytest.raises(FrozenInstanceError):
        result.attack = 9
    with pytest.raises(ValueError):
        StatBonus(attack=-1)


def test_character_resource_limits_and_inventory_independence():
    first = Character("p1", "", "warrior")
    second = Character("p2", "x" * 50, "warrior")
    assert first.snapshot().name == "Игрок 1"
    assert len(second.snapshot().name) == 24
    assert first.take_damage(10) == 10
    assert first.heal(30) == 10
    first.spend_energy(40)
    assert first.restore_energy(80) == 40
    before = first.energy
    with pytest.raises(ValueError):
        first.spend_energy(41)
    assert first.energy == before
    first.inventory.consume("health_potion")
    assert second.inventory.quantity("health_potion") == 1
    assert first.take_damage(999) == 140
    assert first.hp == 0
    with pytest.raises(ValueError):
        first.heal(1)


@pytest.mark.parametrize("operation", ["take_damage", "heal", "spend_energy", "restore_energy"])
@pytest.mark.parametrize("value", [-1, True, 0.5])
def test_resource_mutators_reject_invalid_numbers(operation, value):
    fighter = Character("p1", "x", "mage")
    before = fighter.snapshot()
    with pytest.raises(ValueError):
        getattr(fighter, operation)(value)
    assert fighter.snapshot() == before


def test_inventory_validation_and_exhaustion():
    with pytest.raises(ValueError):
        Inventory({"alien": 1})
    with pytest.raises(ValueError):
        Inventory(dict(health_potion=4, energy_potion=1, antidote=1))
    items = Inventory()
    items.consume("antidote")
    with pytest.raises(ValueError):
        items.consume("antidote")
    assert items.quantity("antidote") == 0
    assert items.quantity("alien") == 0


@pytest.mark.parametrize("action,item", [("heal", None), ("recover", None),
    ("use_item", "health_potion"), ("use_item", "energy_potion"), ("use_item", "antidote")])
def test_unavailable_commands_are_atomic(battle, action, item):
    before = battle.snapshot()
    result = act(battle, action, item)
    assert not result.accepted
    assert battle.snapshot() == before


@pytest.mark.parametrize("changes,code", [
    ({"match_id": "other"}, "wrong_match"),
    ({"expected_turn": 0}, "stale_turn"),
    ({"expected_turn": True}, "stale_turn"),
    ({"actor_id": "p1"}, "wrong_actor"),
    ({"action_id": "heavy_strike"}, "unknown_action"),
    ({"action_id": "alien"}, "unknown_action"),
    ({"target_id": "p2"}, "wrong_target"),
    ({"item_id": "antidote"}, "unexpected_item"),
])
def test_bad_requests_do_not_change_state(battle, changes, code):
    before = battle.snapshot()
    request = ActionRequest(before.match_id, before.turn, "p2", "attack", "p1")
    result = battle.submit(replace(request, **changes))
    assert result.code == code
    assert battle.snapshot() == before


def test_double_click_is_rejected(battle):
    s = battle.snapshot()
    request = ActionRequest(s.match_id, s.turn, s.active_id, "fireball", "p1")
    assert battle.submit(request).accepted
    after = battle.snapshot()
    assert not battle.submit(request).accepted
    assert battle.snapshot() == after


def test_guard_halves_odd_damage_and_is_consumed():
    first = Character("p1", "Воин", "warrior")
    second = Character("p2", "Маг", "mage")
    engine = BattleEngine(first, second)
    act(engine, "defend")
    act(engine, "attack")
    assert second.hp == 88  # 15 // 2 = 7
    assert not second.has_effect("guard")
    assert any(e.kind == "guard_used" for e in engine.snapshot().events)


def test_unused_guard_expires(battle):
    act(battle, "defend")
    act(battle, "defend")
    s = battle.snapshot()
    assert s.active.effect("guard") is None
    assert s.opponent.effect("guard") is not None
    assert any(e.kind == "guard_expired" for e in s.events)


def test_physical_minimum_and_actual_overkill():
    actor = Character("p1", "Маг", "mage")
    target = Character("p2", "Щит", "warrior", "shield")
    target.take_damage(139)
    engine = BattleEngine(actor, target)
    act(engine, "attack")
    s = engine.snapshot()
    assert s.phase == Phase.FINISHED
    damage = next(e for e in s.events if e.kind == "damage")
    assert damage.actual == damage.calculated == 1
    assert s.fighters[0].totals.direct_damage == 1


def test_fireball_ignores_armor_and_energy_boundary():
    mage = Character("p1", "Маг", "mage")
    warrior = Character("p2", "Воин", "warrior", "shield")
    mage.spend_energy(52)
    engine = BattleEngine(mage, warrior)
    assert act(engine, "fireball").accepted
    assert warrior.hp == 104 and mage.energy == 0
    act(engine, "defend")
    before = engine.snapshot()
    assert not act(engine, "fireball").accepted
    assert engine.snapshot() == before


def test_heal_partial_and_full_cost():
    mage = Character("p1", "Маг", "mage")
    mage.take_damage(2)
    mage.spend_energy(50)
    engine = BattleEngine(mage, Character("p2", "Воин", "warrior"))
    assert act(engine, "heal").accepted
    assert mage.hp == 95 and mage.energy == 0
    assert mage.snapshot().totals.healing == 2


def test_heal_at_19_energy_rejected():
    mage = Character("p1", "Маг", "mage")
    mage.take_damage(10)
    mage.spend_energy(51)
    engine = BattleEngine(mage, Character("p2", "Воин", "warrior"))
    before = engine.snapshot()
    assert act(engine, "heal").message == "Недостаточно энергии"
    assert engine.snapshot() == before


def test_poison_reference_two_ticks_and_source():
    ranger = Character("p1", "Следопыт", "ranger")
    mage = Character("p2", "Маг", "mage")
    engine = BattleEngine(ranger, mage)
    act(engine, "poison_arrow")
    s = engine.snapshot()
    assert mage.hp == 71 and ranger.energy == 36
    assert s.active.effect("poison").remaining == 1
    act(engine, "defend")
    act(engine, "defend")
    assert mage.hp == 64
    assert not mage.has_effect("poison")
    assert not mage.has_effect("guard")
    assert ranger.snapshot().totals.poison_damage == 14


def test_poison_refresh_does_not_stack():
    ranger = Character("p1", "Следопыт", "ranger")
    mage = Character("p2", "Маг", "mage")
    engine = BattleEngine(ranger, mage)
    act(engine, "poison_arrow")
    act(engine, "defend")
    act(engine, "poison_arrow")
    poison = engine.snapshot().active.effect("poison")
    assert poison.remaining == 1
    assert len(mage.effects()) == 1
    assert ranger.snapshot().totals.poison_damage == 14


def test_poison_death_before_action():
    ranger = Character("p1", "Следопыт", "ranger")
    mage = Character("p2", "Маг", "mage")
    mage.take_damage(71)  # 24 HP -> direct 17 -> tick 7 -> dead
    engine = BattleEngine(ranger, mage)
    act(engine, "poison_arrow")
    s = engine.snapshot()
    assert s.phase == Phase.FINISHED and s.finish_reason == "poison"
    assert s.turn == 2 and s.successful_actions == 1
    assert s.winner_id == "p1"
    assert engine.action_options("p2") == ()


def test_direct_poison_arrow_kill_does_not_apply_effect():
    ranger = Character("p1", "Следопыт", "ranger")
    mage = Character("p2", "Маг", "mage")
    mage.take_damage(90)
    engine = BattleEngine(ranger, mage)
    act(engine, "poison_arrow")
    s = engine.snapshot()
    assert s.finish_reason == "defeat"
    assert not s.fighters[1].effects
    assert s.fighters[0].totals.direct_damage == 5
    assert s.fighters[0].totals.poison_damage == 0


def test_antidote_removes_future_tick_only():
    engine = BattleEngine(Character("p1", "Следопыт", "ranger"),
                          Character("p2", "Маг", "mage"))
    act(engine, "poison_arrow")
    assert act(engine, "use_item", "antidote").accepted
    mage = engine.snapshot().fighters[1]
    assert mage.hp == 71 and mage.effect("poison") is None
    assert mage.quantity("antidote") == 0
    assert mage.totals.items_used == 1


@pytest.mark.parametrize("item,resource,loss,restored", [
    ("health_potion", "hp", 50, 40), ("health_potion", "hp", 5, 5),
    ("energy_potion", "energy", 40, 25), ("energy_potion", "energy", 5, 5),
])
def test_potion_caps_and_consumption(item, resource, loss, restored):
    mage = Character("p1", "Маг", "mage")
    if resource == "hp":
        mage.take_damage(loss)
    else:
        mage.spend_energy(loss)
    before = getattr(mage, resource)
    engine = BattleEngine(mage, Character("p2", "Воин", "warrior"))
    assert act(engine, "use_item", item).accepted
    assert getattr(mage, resource) == before + restored
    assert mage.inventory.quantity(item) == 0
    assert engine.snapshot().successful_actions == 1


def test_initiative_and_tie():
    for first_kind, second_kind, expected in (("warrior", "mage", "p2"),
                                             ("ranger", "mage", "p1"),
                                             ("mage", "mage", "p1")):
        engine = BattleEngine(Character("p1", "A", first_kind),
                              Character("p2", "A", second_kind))
        assert engine.snapshot().active_id == expected
        act(engine, "defend")
        assert engine.snapshot().active_id != expected


def test_draw_on_100th_action_no_next_turn(battle):
    for _ in range(100):
        assert act(battle, "defend").accepted
    s = battle.snapshot()
    assert (s.phase, s.finish_reason, s.winner_id) == (Phase.FINISHED, "limit", None)
    assert s.turn == 100 and s.successful_actions == 100
    before = s
    assert not battle.submit(ActionRequest(s.match_id, s.turn, s.active_id,
                                          "attack", s.opponent.id)).accepted
    assert battle.snapshot() == before


def test_victory_on_100th_action_beats_draw():
    mage = Character("p1", "Маг", "mage")
    warrior = Character("p2", "Воин", "warrior")
    engine = BattleEngine(mage, warrior)
    for _ in range(99):
        act(engine, "defend")
    mage.take_damage(94)
    act(engine, "attack")
    s = engine.snapshot()
    assert s.successful_actions == 100 and s.finish_reason == "defeat"
    assert s.winner_id == "p2"


def test_surrender_does_not_spend_resources_or_action(battle):
    before = battle.snapshot()
    assert surrender(battle).accepted
    after = battle.snapshot()
    assert after.successful_actions == before.successful_actions
    assert after.fighters == before.fighters
    assert after.winner_id == "p1" and after.finish_reason == "surrender"


def test_preview_does_not_consume_guard_or_resources(battle):
    act(battle, "defend")
    before = battle.snapshot()
    for _ in range(10):
        options = battle.action_options(before.active_id)
        assert next(o for o in options if o.action_id == "attack").damage == 7
    assert battle.snapshot() == before
    assert battle.action_options(before.opponent.id) == ()


def test_snapshot_restores_independent_objects(battle):
    s = battle.snapshot()
    restored = BattleEngine.from_snapshot(s)
    act(restored, "fireball")
    assert battle.snapshot() == s
    assert restored.snapshot() != s


def test_history_generic_collection_contract():
    history = History[str](2)
    history.append("a")
    history.append("b")
    history.append("c")
    assert len(history) == 2
    assert history[0] == "b" and history[-1] == "c"
    copy = history[:]
    copy.clear()
    assert list(history) == ["b", "c"]
    with pytest.raises(IndexError):
        _ = history[2]
    with pytest.raises(ValueError):
        History(0)


def test_registry_has_real_polymorphic_actions():
    registry = action_registry()
    assert len(registry) == 8
    actor = Character("p1", "Маг", "mage")
    target = Character("p2", "Воин", "warrior")
    events = []
    context = ActionContext(actor, target, 1, "attack", events.append)
    assert registry["attack"].preview(context) == (2, 0, 0)
    actor.take_damage(10)
    self_context = ActionContext(actor, actor, 1, "heal", events.append)
    assert registry["heal"].preview(self_context) == (0, 10, 0)
    assert isinstance(registry["fireball"], AttackAction)
    assert isinstance(registry["heal"], HealAction)

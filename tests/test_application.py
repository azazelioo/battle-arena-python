from dataclasses import replace
from unittest.mock import patch

import pytest

from arena.application.bot import AggressiveBot, CautiousBot
from arena.application.controller import FighterSetup, GameController, MatchSetup
from arena.domain.battle import BattleEngine
from arena.domain.character import Character
from arena.domain.effects import PoisonEffect
from arena.domain.model import ActionRequest, Phase
from arena.infrastructure.records import Settings
from arena.infrastructure.storage import StorageError
from arena.presentation.cli import Console
from arena.presentation.formatting import RULES, event_text, fighter_text, result_text
from conftest import act, surrender


@pytest.mark.parametrize("first", ["warrior", "mage", "ranger"])
@pytest.mark.parametrize("second", ["warrior", "mage", "ranger"])
@pytest.mark.parametrize("bot_type", [AggressiveBot, CautiousBot])
def test_bot_matches_always_terminate(first, second, bot_type):
    engine = BattleEngine(Character("p1", "A", first), Character("p2", "B", second))
    bot = bot_type()
    while engine.snapshot().phase != Phase.FINISHED:
        before = engine.snapshot()
        options = engine.action_options(before.active_id)
        request = bot.choose_action(before, options)
        assert engine.snapshot() == before
        assert engine.submit(request).accepted
        assert engine.snapshot().successful_actions <= 100
    assert engine.snapshot().successful_actions > 0


@pytest.mark.parametrize("bot", [AggressiveBot(), CautiousBot()])
def test_lethal_action_priority(bot):
    mage = Character("p1", "M", "mage")
    warrior = Character("p2", "W", "warrior")
    mage.take_damage(80)
    warrior.take_damage(110)
    engine = BattleEngine(mage, warrior)
    s = engine.snapshot()
    request = bot.choose_action(s, engine.action_options(s.active_id))
    assert request.action_id == "fireball"
    engine.submit(request)
    assert engine.snapshot().winner_id == "p1"


def test_aggressive_uses_max_damage_and_free_fallback():
    mage = Character("p1", "M", "mage")
    engine = BattleEngine(mage, Character("p2", "W", "warrior"))
    s = engine.snapshot()
    assert AggressiveBot().choose_action(s, engine.action_options(s.active_id)).action_id == "fireball"
    mage.spend_energy(70)
    s = engine.snapshot()
    assert AggressiveBot().choose_action(s, engine.action_options(s.active_id)).action_id == "attack"


def test_cautious_antidote_before_heal_when_next_tick_lethal():
    mage = Character("p1", "M", "mage")
    warrior = Character("p2", "W", "warrior")
    mage.take_damage(82)  # 13 HP, start-of-turn poison leaves 6
    mage.add_effect(PoisonEffect("p2", 2))
    engine = BattleEngine(mage, warrior)
    s = engine.snapshot()
    assert s.active.hp == 6
    request = CautiousBot().choose_action(s, engine.action_options(s.active_id))
    assert request.item_id == "antidote"


def test_cautious_prefers_largest_heal():
    mage = Character("p1", "M", "mage")
    mage.take_damage(70)
    engine = BattleEngine(mage, Character("p2", "W", "warrior"))
    s = engine.snapshot()
    request = CautiousBot().choose_action(s, engine.action_options(s.active_id))
    assert request.item_id == "health_potion"  # 40 > spell's 36


def test_cautious_healing_tie_prefers_spell():
    mage = Character("p1", "M", "mage")
    mage.take_damage(70)
    engine = BattleEngine(mage, Character("p2", "W", "warrior"))
    s = engine.snapshot()
    options = tuple(replace(o, healing=36) if o.item_id == "health_potion" else o
                    for o in engine.action_options(s.active_id))
    assert CautiousBot().choose_action(s, options).action_id == "heal"


def test_cautious_no_consecutive_guards_without_healing():
    mage = Character("p1", "M", "mage")
    mage.take_damage(80)
    mage.spend_energy(70)
    mage.inventory.consume("health_potion")
    engine = BattleEngine(mage, Character("p2", "W", "warrior"))
    s = engine.snapshot()
    request = CautiousBot().choose_action(s, engine.action_options(s.active_id))
    assert request.action_id == "defend"
    engine.submit(request)
    act(engine, "defend")
    s = engine.snapshot()
    request = CautiousBot().choose_action(s, engine.action_options(s.active_id))
    assert request.action_id == "attack"


def test_cautious_recovers_if_it_unlocks_special():
    mage = Character("p1", "M", "mage")
    mage.spend_energy(65)
    engine = BattleEngine(mage, Character("p2", "W", "warrior"))
    s = engine.snapshot()
    assert CautiousBot().choose_action(s, engine.action_options(s.active_id)).action_id == "recover"
    mage.spend_energy(5)
    s = engine.snapshot()
    assert CautiousBot().choose_action(s, engine.action_options(s.active_id)).action_id == "attack"


def test_bot_rejects_empty_legal_options(battle):
    with pytest.raises(ValueError):
        AggressiveBot().choose_action(battle.snapshot(), ())


def test_controller_pause_and_input_ownership(tmp_path):
    controller = GameController(tmp_path)
    s = controller.new_match(MatchSetup())
    assert controller.is_bot_turn()
    request = next(o for o in controller.options() if o.available).request(s)
    assert controller.submit(request).code == "wrong_controller"
    controller.pause()
    assert controller.bot_step(s.match_id, s.turn).code == "paused"
    assert controller.snapshot() == s
    controller.resume()
    assert controller.bot_step(s.match_id, s.turn).accepted
    assert not controller.is_bot_turn()
    assert controller.bot_step(s.match_id, s.turn).code == "stale_callback"


def test_callback_from_previous_match_rejected(tmp_path):
    controller = GameController(tmp_path)
    old = controller.new_match(MatchSetup())
    new = controller.new_match(MatchSetup())
    assert controller.bot_step(old.match_id, old.turn).code == "stale_callback"
    assert controller.snapshot() == new


def test_controller_load_restores_setup_and_resumes(tmp_path):
    controller = GameController(tmp_path)
    setup = MatchSetup(FighterSetup("A", "ranger", "blade"),
                       FighterSetup("B", "warrior", "shield"), "pvp", "aggressive")
    before = controller.new_match(setup)
    controller.pause()
    controller.save(2)
    controller.new_match(MatchSetup())
    assert controller.load(2) == before
    assert controller.last_setup == setup
    assert not controller.paused


def test_controller_without_match(tmp_path):
    controller = GameController(tmp_path)
    assert controller.snapshot() is None
    assert controller.options() == ()
    assert not controller.is_bot_turn()
    assert controller.submit(ActionRequest("x", 1, "p1", "attack", "p2")).code == "no_match"
    with pytest.raises(StorageError):
        controller.save(1)
    controller.new_match(MatchSetup())
    controller.abandon()
    assert controller.snapshot() is None


def test_settings_failed_write_does_not_apply(tmp_path):
    controller = GameController(tmp_path)
    previous = controller.settings
    with patch("arena.application.controller.save_settings", side_effect=StorageError("disk")):
        with pytest.raises(StorageError):
            controller.update_settings(Settings(0, 20))
    assert controller.settings == previous


@pytest.mark.parametrize("setup", [lambda: FighterSetup(archetype="alien"),
    lambda: FighterSetup(equipment="alien"), lambda: MatchSetup(mode="online"),
    lambda: MatchSetup(strategy="random")])
def test_invalid_setup(setup):
    with pytest.raises(ValueError):
        setup()


def test_console_full_match_save_load_and_surrender(tmp_path):
    controller = GameController(tmp_path)
    # New PvP, warrior vs mage, pause/save slot1/resume, fireball, surrender.
    inputs = iter([
        "1", "2", "Alice", "1", "1", "Bob", "2", "1",
        "p", "2", "1", "1", "5", "q", "да", "1", "7",
    ])
    output = []
    console = Console(controller, lambda _: next(inputs), output.append)
    assert console.run() == 0
    assert controller.repository.slot(1).exists()
    assert len(controller.repository.history()) == 1
    assert any("Бой сохранён" in line for line in output)
    assert any("Победитель" in line for line in output)


def test_console_invalid_input_and_eof(tmp_path):
    controller = GameController(tmp_path)
    inputs = iter(["wrong", "0", "8", "7"])
    output = []
    assert Console(controller, lambda _: next(inputs), output.append).run() == 0
    assert output.count("Введите номер из списка.") == 3
    def eof(_):
        raise EOFError
    assert Console(controller, eof, output.append).run() == 0
    assert "не сохранены" in output[-1]


def test_console_unavailable_move_does_not_take_turn(tmp_path):
    controller = GameController(tmp_path)
    initial = controller.new_match(MatchSetup(mode="pvp"))
    inputs = iter(["3", "nonsense", "p", "4"])
    output = []
    Console(controller, lambda _: next(inputs), output.append).battle()
    assert controller.snapshot() == initial
    assert any("Полное здоровье" in line for line in output)
    assert "Неизвестная команда." in output


def test_formatters_cover_battle_and_result(battle):
    act(battle, "fireball")
    surrender(battle)
    snapshot = battle.snapshot()
    assert "Победитель" in result_text(snapshot)
    assert "HP" in fighter_text(snapshot.active)
    assert "100" in RULES
    assert all(event_text(e, snapshot).startswith(f"{e.number:03d}") for e in snapshot.events)

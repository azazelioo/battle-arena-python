"""History browsing is a read-only application scenario, not a second engine."""

from dataclasses import replace

import pytest

from arena.application.controller import GameController
from arena.application.history import (
    BattleReplay,
    HistoryBrowser,
    HistoryFilter,
)
from arena.domain.battle import BattleEngine
from arena.domain.character import Character
from arena.domain.model import History
from arena.infrastructure.records import MatchSummary
from arena.presentation.cli import Console
from conftest import act, surrender


def summary(index=0, *, mode="pvp", finish="surrender"):
    engine = BattleEngine(
        Character("p1", "Анна", "ranger"),
        Character("p2", "Борис", "mage"),
        mode=mode,
        match_id=f"match-{index}",
    )
    if finish == "surrender":
        surrender(engine)
    elif finish == "limit":
        for _ in range(100):
            act(engine, "defend")
    else:
        while engine.snapshot().finish_reason == "":
            act(engine, "attack")
    return MatchSummary.from_snapshot(engine.snapshot())


def history_of(*entries):
    history = History(50)
    for entry in entries:
        history.append(entry)
    return history


def test_browser_uses_independent_reverse_chronological_view():
    entries = [summary(index) for index in range(3)]
    original = history_of(*entries)
    browser = HistoryBrowser(original, page_size=2)
    assert browser.count == 3
    assert browser.page_count == 2
    assert browser.page == 0
    assert browser.page_entries() == (entries[2], entries[1])
    assert browser.select(0) is entries[2]
    original.append(summary(4))
    assert browser.count == 3
    browser.move(1)
    assert browser.page_entries() == (entries[0],)
    assert browser.select(0) is entries[0]
    browser.move(1)
    assert browser.page == 1
    browser.move(-1)
    browser.move(-1)
    assert browser.page == 0


def test_browser_empty_page_and_out_of_range_selection():
    browser = HistoryBrowser(History())
    assert browser.count == 0 and browser.page_count == 1
    assert browser.page_entries() == ()
    browser.move(1)
    assert browser.page == 0
    with pytest.raises(IndexError):
        browser.select(0)
    with pytest.raises(ValueError):
        browser.select(-1)
    with pytest.raises(ValueError):
        browser.select(True)
    with pytest.raises(ValueError):
        browser.select(browser.page_size)
    assert browser.statistics().average_actions == 0


@pytest.mark.parametrize("direction", [0, 2, True, "1"])
def test_browser_rejects_invalid_movement(direction):
    browser = HistoryBrowser(History())
    with pytest.raises(ValueError):
        browser.move(direction)
    assert browser.page == 0


@pytest.mark.parametrize("size", [0, 51, True, 1.5])
def test_invalid_page_size(size):
    with pytest.raises(ValueError):
        HistoryBrowser(History(), size)


@pytest.mark.parametrize("mode,outcome", [("online", "all"), ("all", "loss")])
def test_invalid_filters(mode, outcome):
    with pytest.raises(ValueError):
        HistoryFilter(mode=mode, outcome=outcome)


def test_filters_combine_name_mode_and_outcome():
    pvp = summary(0)
    bot = summary(1, mode="bot")
    draw = summary(2, finish="limit")
    victory = summary(3, finish="defeat")
    browser = HistoryBrowser(history_of(pvp, bot, draw, victory), 1)
    browser.move(1)
    browser.apply_filter(HistoryFilter("  АННА  ", mode="bot"))
    assert browser.page == 0
    assert browser.page_entries() == (bot,)
    browser.apply_filter(HistoryFilter(outcome="draw"))
    assert browser.page_entries() == (draw,)
    browser.apply_filter(HistoryFilter(outcome="win"))
    assert browser.count == 3
    browser.apply_filter(HistoryFilter(outcome="surrender"))
    assert browser.count == 2
    browser.apply_filter(HistoryFilter("match-3"))
    assert browser.page_entries() == (victory,)
    browser.apply_filter(HistoryFilter("Ничья"))
    assert browser.page_entries() == (draw,)
    browser.apply_filter(HistoryFilter("not found"))
    assert browser.count == 0


def test_statistics_aggregate_only_visible_matches():
    engine = BattleEngine(
        Character("p1", "А", "ranger"), Character("p2", "Б", "mage")
    )
    act(engine, "poison_arrow")
    act(engine, "use_item", "health_potion")
    surrender(engine)
    entry = MatchSummary.from_snapshot(engine.snapshot())
    browser = HistoryBrowser(history_of(entry, summary(1, finish="limit")))
    stats = browser.statistics()
    assert stats.matches == 2
    assert stats.draws == 1 and stats.surrenders == 1
    assert stats.actions == 102 and stats.average_actions == 51
    assert stats.direct_damage == 17
    assert stats.poison_damage == 7
    assert stats.healing == 24
    assert stats.items_used == 1
    browser.apply_filter(HistoryFilter(outcome="surrender"))
    assert browser.statistics().actions == 2


def test_replay_reference_sequence_matches_real_resource_snapshots(battle):
    expected = [battle.snapshot()]
    for action in (
        "fireball",
        "defend",
        "attack",
        "heavy_strike",
        "heal",
        "attack",
    ):
        act(battle, action)
        expected.append(battle.snapshot())
    final = battle.snapshot()
    replay = BattleReplay(final)
    assert replay.current.event is None
    assert replay.length == len(final.events) + 1
    assert replay.current.resources[0].hp == 140
    assert replay.current.resources[1].energy == 70
    for state in expected:
        frame = replay.seek(len(state.events))
        for actual, fighter in zip(frame.resources, state.fighters):
            assert (actual.hp, actual.energy) == (fighter.hp, fighter.energy)
    assert battle.snapshot() == final
    for _ in range(replay.length + 1):
        replay.step(-1)
    assert replay.position == 0
    replay.seek(replay.length - 1)
    assert replay.step(1).position == replay.length - 1


def test_replay_poison_healing_and_energy_item_exact_deltas():
    ranger = Character("p1", "А", "ranger")
    mage = Character("p2", "Б", "mage")
    mage.spend_energy(30)
    engine = BattleEngine(ranger, mage)
    act(engine, "poison_arrow")
    act(engine, "use_item", "energy_potion")
    act(engine, "attack")
    act(engine, "use_item", "health_potion")
    replay = BattleReplay(engine.snapshot())
    assert replay.current.resources[1].energy == 40
    assert replay.current.resources[1].hp == 95
    frame = replay.seek(replay.length - 1)
    assert frame.resources[1].energy == mage.energy == 65
    assert frame.resources[1].hp == mage.hp
    poison = next(e for e in engine.snapshot().events if e.kind == "poison")
    before = replay.seek(poison.number - 1)
    after = replay.step(1)
    assert before.resources[1].hp - after.resources[1].hp == 7
    assert replay.turn(2).event.turn == 2


def test_replay_preserves_non_full_initial_hp_and_capped_healing():
    mage = Character("p1", "A", "mage")
    mage.take_damage(3)
    engine = BattleEngine(mage, Character("p2", "B", "warrior"))
    act(engine, "heal")
    replay = BattleReplay(engine.snapshot())
    assert replay.current.resources[0].hp == 92
    assert replay.current.resources[0].energy == 70
    assert replay.seek(replay.length - 1).resources[0].hp == 95
    assert replay.current.resources[0].energy == 50


@pytest.mark.parametrize("position", [-1, 999, True, 1.5])
def test_replay_invalid_seek_does_not_move(battle, position):
    replay = BattleReplay(battle.snapshot())
    before = replay.current
    with pytest.raises(ValueError):
        replay.seek(position)
    assert replay.current == before


def test_replay_bad_direction_and_missing_turn(battle):
    replay = BattleReplay(battle.snapshot())
    with pytest.raises(ValueError):
        replay.step(0)
    with pytest.raises(ValueError):
        replay.turn(0)
    with pytest.raises(ValueError):
        BattleReplay(replace(battle.snapshot(), turn=2)).turn(2)


def test_console_history_paging_stats_and_replay(tmp_path):
    controller = GameController(tmp_path)
    controller.repository.add_result(summary().snapshot)
    responses = iter(
        [
            "",
            "s",
            "n",
            "p",
            "99",
            "oops",
            "1",
            "",
            "p",
            "end",
            "oops",
            "q",
            "нет",
        ]
    )
    messages = []
    console = Console(controller, lambda _: next(responses), messages.append)
    console.history()
    assert any("Матчей: 1" in line for line in messages)
    assert "Страница 1/1" in messages
    assert "Нет матча с таким номером на странице." in messages
    assert "Неизвестная команда истории." in messages
    assert "Неизвестная команда просмотра." in messages
    assert any("Событие 0/2" in line for line in messages)
    assert len(controller.repository.history()) == 1

import copy
import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from arena.application.bot import AggressiveBot
from arena.application.controller import GameController, MatchSetup
from arena.domain.battle import BattleEngine
from arena.domain.character import Character
from arena.domain.model import Phase
from arena.infrastructure.records import (
    MatchRepository,
    Settings,
    load_settings,
    save_settings,
)
from arena.infrastructure.storage import (
    StorageError,
    atomic_json,
    document_to_snapshot,
    load_match,
    read_json,
    save_match,
    snapshot_to_document,
)
from conftest import act, surrender


def test_poison_save_does_not_tick_again(tmp_path):
    engine = BattleEngine(
        Character("p1", "R", "ranger"), Character("p2", "M", "mage")
    )
    act(engine, "poison_arrow")
    original = engine.snapshot()
    assert original.active.hp == 71
    path = tmp_path / "save.json"
    save_match(path, original)
    restored = BattleEngine.from_snapshot(load_match(path))
    assert restored.snapshot() == original
    assert restored.snapshot().active.hp == 71
    for command, item in (
        ("use_item", "antidote"),
        ("attack", None),
        ("heal", None),
        ("poison_arrow", None),
    ):
        assert act(engine, command, item) == act(restored, command, item)
        assert restored.snapshot() == engine.snapshot()


def test_reference_six_turn_roundtrip(battle, tmp_path):
    for action in (
        "fireball",
        "defend",
        "attack",
        "heavy_strike",
        "heal",
        "attack",
    ):
        act(battle, action)
    save_match(tmp_path / "slot.json", battle.snapshot())
    restored = BattleEngine.from_snapshot(load_match(tmp_path / "slot.json"))
    assert restored.snapshot() == battle.snapshot()
    assert restored.snapshot().turn == 7


def test_continuous_and_saved_match_have_identical_outcome(battle, tmp_path):
    for _ in range(3):
        s = battle.snapshot()
        battle.submit(
            AggressiveBot().choose_action(
                s, battle.action_options(s.active_id)
            )
        )
    save_match(tmp_path / "slot.json", battle.snapshot())
    resumed = BattleEngine.from_snapshot(load_match(tmp_path / "slot.json"))
    while battle.snapshot().phase != Phase.FINISHED:
        s = battle.snapshot()
        request = AggressiveBot().choose_action(
            s, battle.action_options(s.active_id)
        )
        assert battle.submit(request) == resumed.submit(request)
    assert battle.snapshot() == resumed.snapshot()


@pytest.mark.parametrize(
    "path,value",
    [
        (("schema_version",), 2),
        (("rules_version",), True),
        (("saved_at",), "not-a-date"),
        (("battle", "phase"), "RESOLVING"),
        (("battle", "mode"), "online"),
        (("battle", "strategy"), "random"),
        (("battle", "active_id"), "alien"),
        (("battle", "active_id"), "p1"),
        (("battle", "turn"), 0),
        (("battle", "turn"), True),
        (("battle", "successful_actions"), 100),
        (("battle", "next_event"), 42),
        (("battle", "winner_id"), "p1"),
        (("battle", "finish_reason"), "limit"),
        (("battle", "fighters", 0, "id"), "p2"),
        (("battle", "fighters", 0, "name"), ""),
        (("battle", "fighters", 0, "name"), " A "),
        (("battle", "fighters", 0, "archetype"), "alien"),
        (("battle", "fighters", 0, "equipment"), "alien"),
        (("battle", "fighters", 0, "hp"), -1),
        (("battle", "fighters", 0, "hp"), 0),
        (("battle", "fighters", 0, "hp"), 141),
        (("battle", "fighters", 0, "hp"), True),
        (("battle", "fighters", 0, "energy"), 41),
        (("battle", "fighters", 0, "energy"), 1.5),
        (("battle", "fighters", 0, "stats", "attack"), 99),
        (("battle", "fighters", 0, "inventory", 0, 1), -1),
        (("battle", "fighters", 0, "inventory", 0, 1), True),
        (("battle", "fighters", 0, "inventory", 0, 0), "alien"),
        (("battle", "fighters", 0, "last_action_id"), "fireball"),
        (("battle", "fighters", 0, "totals", "healing"), -1),
        (("battle", "events", 0, "number"), 4),
        (("battle", "events", 0, "turn"), 9),
        (("battle", "events", 0, "actor_id"), "alien"),
        (("battle", "events", 0, "target_id"), "alien"),
        (("battle", "events", 0, "kind"), "alien"),
        (("battle", "events", 0, "actual"), 99),
    ],
)
def test_corrupt_save_rejected(battle, path, value):
    # JSON round trip intentionally converts tuples to lists like real files.
    document = json.loads(json.dumps(snapshot_to_document(battle.snapshot())))
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(StorageError):
        document_to_snapshot(document)


@pytest.mark.parametrize(
    "text",
    ["{", "[]", "null", '{"a":1,"a":2}', '{"schema_version":NaN}', '"text"'],
)
def test_bad_json(tmp_path, text):
    path = tmp_path / "save.json"
    path.write_text(text)
    with pytest.raises(StorageError):
        load_match(path)


def test_missing_oversized_and_invalid_unicode(tmp_path):
    with pytest.raises(StorageError):
        load_match(tmp_path / "missing.json")
    path = tmp_path / "save.json"
    path.write_bytes(b"\xff")
    with pytest.raises(StorageError):
        read_json(path)
    path.write_text(" " * 2_000_001)
    with pytest.raises(StorageError):
        read_json(path)


def test_failed_write_preserves_previous_slot(battle, tmp_path):
    path = tmp_path / "save.json"
    save_match(path, battle.snapshot())
    original = path.read_bytes()
    act(battle, "fireball")
    with patch("pathlib.Path.replace", side_effect=OSError("disk error")):
        with pytest.raises(StorageError):
            save_match(path, battle.snapshot())
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_serialization_failure_cleans_up(tmp_path):
    path = tmp_path / "save.json"
    path.write_text("old")
    with pytest.raises(StorageError):
        atomic_json(path, {"not_json": object()})
    assert path.read_text() == "old"
    assert len(list(tmp_path.iterdir())) == 1


def test_load_failure_preserves_controller_state(tmp_path):
    controller = GameController(tmp_path)
    controller.new_match(MatchSetup())
    controller.pause()
    before = controller.snapshot()
    controller.repository.slot(1).write_text("{")
    with pytest.raises(StorageError):
        controller.load(1)
    assert controller.snapshot() == before
    assert controller.paused


def test_history_deduplication_and_finished_load(tmp_path, battle):
    surrender(battle)
    state = battle.snapshot()
    repository = MatchRepository(tmp_path)
    repository.add_result(state)
    repository.add_result(state)
    assert len(repository.history()) == 1
    save_match(repository.slot(1), state)
    controller = GameController(tmp_path)
    controller.load(1)
    controller.load(1)
    assert len(repository.history()) == 1
    assert repository.history()[0].snapshot == state


def test_history_retains_only_last_50(tmp_path):
    repository = MatchRepository(tmp_path)
    for index in range(53):
        engine = BattleEngine(
            Character("p1", "A", "mage"),
            Character("p2", "B", "warrior"),
            match_id=f"m{index}",
        )
        surrender(engine)
        repository.add_result(engine.snapshot())
    history = repository.history()
    assert len(history) == 50
    assert history[0].match_id == "m3"
    assert history[-1].match_id == "m52"
    repository.clear_history()
    assert len(repository.history()) == 0


def test_history_write_error_keeps_result_usable(tmp_path):
    controller = GameController(tmp_path)
    s = controller.new_match(MatchSetup(mode="pvp"))
    from arena.domain.model import ActionRequest

    with patch.object(
        controller.repository,
        "add_result",
        side_effect=StorageError("disk error"),
    ):
        result = controller.submit(
            ActionRequest(
                s.match_id, s.turn, s.active_id, "surrender", s.active_id
            )
        )
    assert result.accepted
    assert controller.snapshot().phase == Phase.FINISHED
    assert "история не записана" in controller.warning


def test_corrupt_history_not_silently_overwritten(tmp_path, battle):
    repository = MatchRepository(tmp_path)
    repository.history_path.write_text("broken")
    surrender(battle)
    with pytest.raises(StorageError):
        repository.add_result(battle.snapshot())
    assert repository.history_path.read_text() == "broken"


def test_settings_defaults_and_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    assert load_settings(path) == Settings()
    save_settings(path, Settings(0, 18))
    assert load_settings(path) == Settings(0, 18)
    atomic_json(path, {"font_size": 14})
    assert load_settings(path) == Settings(300, 14)


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"alien": 1},
        {"bot_delay_ms": -1},
        {"font_size": 21},
        {"font_size": True},
        {"bot_delay_ms": "300"},
    ],
)
def test_invalid_settings_reported(tmp_path, data):
    path = tmp_path / "settings.json"
    atomic_json(path, data)
    with pytest.raises(StorageError):
        load_settings(path)
    controller = GameController(tmp_path)
    assert controller.settings == Settings()
    assert controller.warning


@pytest.mark.parametrize("slot", [0, 4, -1, True, 1.5])
def test_only_three_slots(tmp_path, slot):
    with pytest.raises(ValueError):
        MatchRepository(tmp_path).slot(slot)


@pytest.mark.parametrize("finish", ["surrender", "limit", "defeat", "poison"])
def test_all_finished_states_roundtrip(tmp_path, finish):
    first = Character("p1", "A", "ranger")
    second = Character("p2", "B", "mage")
    engine = BattleEngine(first, second)
    if finish == "surrender":
        surrender(engine)
    elif finish == "limit":
        for _ in range(100):
            act(engine, "defend")
    elif finish == "poison":
        second.take_damage(71)
        act(engine, "poison_arrow")
    else:
        second.take_damage(94)
        act(engine, "attack")
    s = engine.snapshot()
    assert s.finish_reason == finish
    save_match(tmp_path / "save.json", s)
    assert (
        BattleEngine.from_snapshot(
            load_match(tmp_path / "save.json")
        ).snapshot()
        == s
    )

"""Contract, restoration and error-path checks that complement reference games."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from arena.application.controller import GameController
from arena.domain.actions import ActionContext, HealAction, UseItemAction
from arena.domain.battle import BattleEngine
from arena.domain.character import Character
from arena.domain.effects import effect_from_snapshot
from arena.domain.model import ActionRequest, EffectSnapshot, Phase
from arena.infrastructure.records import (
    MatchRepository,
    MatchSummary,
    Settings,
)
from arena.infrastructure.storage import (
    StorageError,
    atomic_json,
    document_to_snapshot,
    read_json,
    snapshot_to_document,
)
from conftest import act, surrender


def document(battle):
    return json.loads(json.dumps(snapshot_to_document(battle.snapshot())))


def test_actions_reject_dead_actor_and_unknown_item():
    actor = Character("p1", "A", "mage")
    actor.take_damage(95)
    context = ActionContext(actor, actor, 1, "heal", lambda _: None)
    assert HealAction().availability(context) == "Участник побеждён"
    assert UseItemAction().availability(context) == "Участник побеждён"
    actor = Character("p1", "A", "mage")
    context.actor = actor
    context.target = actor
    context.item_id = "alien"
    assert UseItemAction().availability(context) == "Неизвестный предмет"
    assert UseItemAction().preview(context) == (0, 0, 0)
    assert UseItemAction().option(context).name == "Предмет"
    context.item_id = "antidote"
    actor.inventory.consume("antidote")
    assert UseItemAction().availability(context) == "Предмет закончился"


@pytest.mark.parametrize(
    "mode,strategy", [("online", "aggressive"), ("pvp", "random")]
)
def test_engine_invalid_modes(mode, strategy):
    with pytest.raises(ValueError):
        BattleEngine(
            Character("p1", "A", "mage"),
            Character("p2", "B", "mage"),
            mode,
            strategy,
        )


def test_engine_rejects_duplicate_or_dead_fighters():
    first = Character("p1", "A", "mage")
    with pytest.raises(ValueError):
        BattleEngine(first, first)
    first.take_damage(95)
    with pytest.raises(ValueError):
        BattleEngine(first, Character("p2", "B", "warrior"))
    with pytest.raises(ValueError):
        Character("", "A", "mage")


def test_bad_surrender_target_rejected(battle):
    before = battle.snapshot()
    request = ActionRequest(
        before.match_id,
        before.turn,
        before.active_id,
        "surrender",
        before.opponent.id,
    )
    assert battle.submit(request).code == "wrong_target"
    assert battle.snapshot() == before


def test_character_snapshot_wrong_stats_rejected():
    fighter = Character("p1", "A", "mage")
    s = fighter.snapshot()
    with pytest.raises(ValueError):
        Character.from_snapshot(replace(s, stats=replace(s.stats, attack=99)))
    with pytest.raises(ValueError):
        effect_from_snapshot(EffectSnapshot("alien", "p1", 1))


@pytest.mark.parametrize(
    "effect",
    [
        {"effect_id": "alien", "source_id": "p2", "remaining": 1},
        {"effect_id": "poison", "source_id": "alien", "remaining": 1},
        {"effect_id": "poison", "source_id": "p1", "remaining": 1},
        {"effect_id": "poison", "source_id": "p2", "remaining": 0},
        {"effect_id": "poison", "source_id": "p2", "remaining": 3},
        {"effect_id": "guard", "source_id": "p2", "remaining": 1},
        {"effect_id": "guard", "source_id": "p1", "remaining": 2},
    ],
)
def test_effect_corruption(battle, effect):
    data = document(battle)
    data["battle"]["fighters"][0]["effects"] = [effect]
    with pytest.raises(StorageError):
        document_to_snapshot(data)


def test_duplicate_effects_rejected(battle):
    data = document(battle)
    effect = {"effect_id": "poison", "source_id": "p2", "remaining": 1}
    data["battle"]["fighters"][0]["effects"] = [effect, effect]
    with pytest.raises(StorageError):
        document_to_snapshot(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("fighters", []),
        ("fighters", {}),
        ("events", {}),
        ("events", []),
        ("match_id", None),
        ("turn", "1"),
    ],
)
def test_wrong_structures_rejected(battle, field, value):
    data = document(battle)
    data["battle"][field] = value
    with pytest.raises(StorageError):
        document_to_snapshot(data)


def test_malformed_inventory_pair_rejected(battle):
    data = document(battle)
    data["battle"]["fighters"][0]["inventory"] = [["antidote"]]
    with pytest.raises(StorageError):
        document_to_snapshot(data)


def test_unknown_finish_reason_rejected(battle):
    surrender(battle)
    data = document(battle)
    data["battle"]["finish_reason"] = ""
    data["battle"]["events"][-1]["action_id"] = ""
    with pytest.raises(StorageError, match="Неизвестная причина"):
        document_to_snapshot(data)


@pytest.mark.parametrize("reason", ["surrender", "limit", "defeat", "poison"])
def test_forged_result_rejected(battle, reason):
    surrender(battle)
    data = document(battle)
    data["battle"]["finish_reason"] = reason
    data["battle"]["winner_id"] = data["battle"]["active_id"]
    data["battle"]["events"][-1]["action_id"] = reason
    data["battle"]["events"][-1]["actor_id"] = data["battle"]["active_id"]
    with pytest.raises(StorageError):
        document_to_snapshot(data)


def test_history_rejects_unfinished_version_and_duplicates(tmp_path, battle):
    with pytest.raises(ValueError):
        MatchSummary.from_snapshot(battle.snapshot())
    repository = MatchRepository(tmp_path)
    atomic_json(repository.history_path, {"schema_version": 2, "matches": []})
    with pytest.raises(StorageError):
        repository.history()
    unfinished = {
        "completed_at": "2026-09-16T00:00:00+00:00",
        "document": document(battle),
    }
    atomic_json(
        repository.history_path, {"schema_version": 1, "matches": [unfinished]}
    )
    with pytest.raises(StorageError):
        repository.history()
    surrender(battle)
    finished = {
        "completed_at": "2026-09-16T00:00:00+00:00",
        "document": document(battle),
    }
    atomic_json(
        repository.history_path,
        {"schema_version": 1, "matches": [finished, finished]},
    )
    with pytest.raises(StorageError):
        repository.history()


def test_large_history_limit_is_separate_from_slot_limit(tmp_path, battle):
    # 50 long matches may exceed the single-slot limit; they must remain readable.
    for _ in range(100):
        act(battle, "defend")
    base = battle.snapshot()
    entries = []
    for index in range(50):
        state = replace(base, match_id=f"long-{index}")
        entries.append(
            {
                "completed_at": "2026-09-16T00:00:00+00:00",
                "document": snapshot_to_document(state),
            }
        )
    repository = MatchRepository(tmp_path)
    atomic_json(
        repository.history_path, {"schema_version": 1, "matches": entries}
    )
    assert repository.history_path.stat().st_size > 2_000_000
    assert len(repository.history()) == 50


def test_settings_update_success(tmp_path):
    controller = GameController(tmp_path)
    settings = Settings(0, 14)
    controller.update_settings(settings)
    assert controller.settings == settings
    assert GameController(tmp_path).settings == settings


def test_cleanup_failure_does_not_hide_original_error(tmp_path):
    path = tmp_path / "save.json"
    with patch("pathlib.Path.replace", side_effect=OSError("original error")):
        with patch(
            "pathlib.Path.unlink", side_effect=OSError("cleanup error")
        ):
            with pytest.raises(StorageError, match="original error"):
                atomic_json(path, {})

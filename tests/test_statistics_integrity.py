"""A save must not silently introduce false totals or hidden bot state."""

from dataclasses import replace
import json

import pytest

from arena.domain.battle import BattleEngine
from arena.domain.character import Character
from arena.domain.validation import validate_recorded_statistics
from arena.infrastructure.storage import (
    StorageError,
    document_to_snapshot,
    snapshot_to_document,
)
from conftest import act


@pytest.mark.parametrize(
    "field",
    [
        "direct_damage",
        "poison_damage",
        "healing",
        "items_used",
    ],
)
def test_forged_totals_are_rejected(battle, field):
    act(battle, "fireball")
    document = json.loads(json.dumps(snapshot_to_document(battle.snapshot())))
    document["battle"]["fighters"][1]["totals"][field] += 1
    with pytest.raises(StorageError, match="Статистика"):
        document_to_snapshot(document)


def test_forged_last_action_is_rejected(battle):
    document = json.loads(json.dumps(snapshot_to_document(battle.snapshot())))
    document["battle"]["fighters"][1]["last_action_id"] = "defend"
    with pytest.raises(StorageError, match="Последнее действие"):
        document_to_snapshot(document)


def test_integrity_uses_actual_overkill_damage():
    ranger = Character("p1", "A", "ranger")
    mage = Character("p2", "B", "mage")
    mage.take_damage(94)
    engine = BattleEngine(ranger, mage)
    act(engine, "attack")
    state = engine.snapshot()
    validate_recorded_statistics(state)
    damage = next(e for e in state.events if e.kind == "damage")
    assert damage.actual == 1
    assert damage.calculated == 13
    assert state.fighters[0].totals.direct_damage == 1


def test_integrity_counts_poison_heal_and_items_separately():
    engine = BattleEngine(
        Character("p1", "A", "ranger"), Character("p2", "B", "mage")
    )
    act(engine, "poison_arrow")
    act(engine, "use_item", "health_potion")
    state = engine.snapshot()
    validate_recorded_statistics(state)
    assert state.fighters[0].totals.direct_damage == 17
    assert state.fighters[0].totals.poison_damage == 7
    assert state.fighters[1].totals.healing == 24
    assert state.fighters[1].totals.items_used == 1
    assert (
        document_to_snapshot(
            json.loads(json.dumps(snapshot_to_document(state)))
        )
        == state
    )


@pytest.mark.parametrize("kind", ["damage", "item_used", "action"])
def test_statistics_validator_rejects_unknown_actor(battle, kind):
    state = battle.snapshot()
    forged = replace(state.events[0], kind=kind, actor_id="alien")
    with pytest.raises(ValueError):
        validate_recorded_statistics(replace(state, events=(forged,)))


def test_statistics_validation_does_not_mutate_snapshot(battle):
    act(battle, "fireball")
    act(battle, "defend")
    before = battle.snapshot()
    for _ in range(3):
        validate_recorded_statistics(before)
    assert battle.snapshot() == before

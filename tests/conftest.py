from __future__ import annotations

import pytest

from arena.domain.battle import BattleEngine
from arena.domain.character import Character
from arena.domain.model import ActionRequest, ActionResult


@pytest.fixture
def battle() -> BattleEngine:
    return BattleEngine(Character("p1", "Воин", "warrior"),
                        Character("p2", "Маг", "mage"), match_id="test-match")


def act(engine: BattleEngine, action_id: str, item_id: str | None = None) -> ActionResult:
    snapshot = engine.snapshot()
    option = next(o for o in engine.action_options(snapshot.active_id)
                  if o.action_id == action_id and o.item_id == item_id)
    return engine.submit(option.request(snapshot))


def surrender(engine: BattleEngine) -> ActionResult:
    s = engine.snapshot()
    return engine.submit(ActionRequest(s.match_id, s.turn, s.active_id,
                                      "surrender", s.active_id))

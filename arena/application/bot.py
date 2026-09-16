"""Deterministic strategies inspect only immutable snapshots and previews."""
from abc import ABC, abstractmethod
from typing import override

from arena.domain.catalog import CHARACTERS, POISON_DAMAGE
from arena.domain.model import ActionOption, ActionRequest, BattleSnapshot


class PredictionBot(ABC):
    @abstractmethod
    def choose_action(self, snapshot: BattleSnapshot,
                      options: tuple[ActionOption, ...]) -> ActionRequest:
        """Return a legal request; the engine still validates it again."""

    @staticmethod
    def legal(options: tuple[ActionOption, ...]) -> list[ActionOption]:
        result = sorted((o for o in options if o.available),
                        key=lambda o: (o.action_id, o.item_id or ""))
        if not result:
            raise ValueError("Нет допустимых действий")
        return result


class AggressiveBot(PredictionBot):
    @override
    def choose_action(self, snapshot: BattleSnapshot,
                      options: tuple[ActionOption, ...]) -> ActionRequest:
        legal = self.legal(options)
        # Stable initial sorting breaks ties, including equally lethal attacks.
        chosen = max(legal, key=lambda option: option.damage)
        return chosen.request(snapshot)


class CautiousBot(AggressiveBot):
    @override
    def choose_action(self, snapshot: BattleSnapshot,
                      options: tuple[ActionOption, ...]) -> ActionRequest:
        legal = self.legal(options)
        lethal = next((o for o in legal if o.damage >= snapshot.opponent.hp), None)
        if lethal:
            return lethal.request(snapshot)
        actor = snapshot.active
        antidote = next((o for o in legal if o.item_id == "antidote"), None)
        if actor.effect("poison") and actor.hp <= POISON_DAMAGE and antidote:
            return antidote.request(snapshot)
        if actor.hp * 100 <= actor.stats.max_hp * 35:
            healing = [o for o in legal if o.healing > 0]
            if healing:
                chosen = max(healing, key=lambda o: (o.healing, o.action_id == "heal"))
                return chosen.request(snapshot)
            if actor.last_action_id != "defend":
                return next(o for o in legal if o.action_id == "defend").request(snapshot)
        else:
            special_id = CHARACTERS[actor.archetype].special
            special = next((o for o in options if o.action_id == special_id), None)
            recover = next((o for o in legal if o.action_id == "recover"), None)
            if (special and not special.available and recover and
                    actor.energy < special.cost <= actor.energy + recover.energy):
                return recover.request(snapshot)
        return super().choose_action(snapshot, options)


BOTS: dict[str, type[PredictionBot]] = {
    "aggressive": AggressiveBot,
    "cautious": CautiousBot,
}

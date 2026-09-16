"""Versioned JSON, strict decoding and atomic replacement of local files."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arena.domain.model import (
    BattleEvent, BattleSnapshot, CharacterSnapshot, CombatStats,
    EffectSnapshot, Phase, Stats,
)
from arena.domain.validation import validate_snapshot

SCHEMA_VERSION = 1
RULES_VERSION = 1
MAX_FILE_BYTES = 2_000_000


class StorageError(ValueError):
    """Expected I/O or format error suitable for presentation to the user."""


def atomic_json(path: Path, value: object) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except (OSError, ValueError, TypeError) as error:
        raise StorageError(f"Не удалось записать {path.name}: {error}") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Preserve the original error if cleanup also fails.


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Повторяющийся ключ: {key}")
        result[key] = value
    return result


def read_json(path: Path, maximum_bytes: int = MAX_FILE_BYTES) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            text = stream.read(maximum_bytes + 1)
        if len(text.encode("utf-8")) > maximum_bytes:
            raise ValueError(f"Файл превышает {maximum_bytes} байт")
        return json.loads(text, object_pairs_hook=unique_object)
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        raise StorageError(f"Не удалось прочитать {path.name}: {error}") from error


def obj(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Неверный набор полей JSON")
    return value


def string(value: Any, maximum: int = 100) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("Ожидается строка допустимой длины")
    return value


def number(value: Any) -> int:
    if type(value) is not int:
        raise ValueError("Ожидается целое число (не bool)")
    return value


def array(value: Any, maximum: int = 2000) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Ожидается массив допустимой длины")
    return value


def decode_fighter(value: Any) -> CharacterSnapshot:
    data = obj(value, {
        "id", "name", "archetype", "equipment", "stats", "hp", "energy",
        "inventory", "effects", "last_action_id", "totals",
    })
    stats = obj(data["stats"], {"max_hp", "max_energy", "attack", "magic", "armor", "speed"})
    totals = obj(data["totals"], {"direct_damage", "poison_damage", "healing", "items_used"})
    inventory: list[tuple[str, int]] = []
    for pair in array(data["inventory"], 3):
        pair = array(pair, 2)
        if len(pair) != 2:
            raise ValueError("Неверная запись предмета")
        inventory.append((string(pair[0]), number(pair[1])))
    effects: list[EffectSnapshot] = []
    for effect in array(data["effects"], 2):
        effect = obj(effect, {"effect_id", "source_id", "remaining"})
        effects.append(EffectSnapshot(string(effect["effect_id"]),
                                      string(effect["source_id"]),
                                      number(effect["remaining"])))
    return CharacterSnapshot(
        string(data["id"]), string(data["name"], 24),
        string(data["archetype"]), string(data["equipment"]),
        Stats(**{key: number(value) for key, value in stats.items()}),
        number(data["hp"]), number(data["energy"]), tuple(inventory),
        tuple(effects), string(data["last_action_id"]),
        CombatStats(**{key: number(value) for key, value in totals.items()}),
    )


def snapshot_to_document(snapshot: BattleSnapshot) -> dict[str, Any]:
    validate_snapshot(snapshot)
    return {
        "schema_version": SCHEMA_VERSION,
        "rules_version": RULES_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "battle": asdict(snapshot),
    }


def document_to_snapshot(document: Any) -> BattleSnapshot:
    try:
        doc = obj(document, {"schema_version", "rules_version", "saved_at", "battle"})
        if (number(doc["schema_version"]) != SCHEMA_VERSION or
                number(doc["rules_version"]) != RULES_VERSION):
            raise ValueError("Неподдерживаемая версия сохранения")
        datetime.fromisoformat(string(doc["saved_at"]))
        data = obj(doc["battle"], {
            "match_id", "mode", "strategy", "phase", "active_id", "turn",
            "successful_actions", "fighters", "events", "next_event",
            "winner_id", "finish_reason",
        })
        fighters = [decode_fighter(f) for f in array(data["fighters"], 2)]
        if len(fighters) != 2:
            raise ValueError("Нужны два участника")
        events: list[BattleEvent] = []
        for event in array(data["events"]):
            event = obj(event, {
                "number", "turn", "kind", "actor_id", "target_id", "action_id",
                "calculated", "actual", "remaining",
            })
            events.append(BattleEvent(
                number(event["number"]), number(event["turn"]),
                string(event["kind"]), string(event["actor_id"]),
                string(event["target_id"]), string(event["action_id"]),
                number(event["calculated"]), number(event["actual"]),
                number(event["remaining"]),
            ))
        snapshot = BattleSnapshot(
            string(data["match_id"]), string(data["mode"]), string(data["strategy"]),
            Phase(string(data["phase"])), string(data["active_id"]),
            number(data["turn"]), number(data["successful_actions"]),
            (fighters[0], fighters[1]), tuple(events), number(data["next_event"]),
            None if data["winner_id"] is None else string(data["winner_id"]),
            string(data["finish_reason"]),
        )
        validate_snapshot(snapshot)
        return snapshot
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
        raise StorageError(f"Повреждённое сохранение: {error}") from error


def save_match(path: Path, snapshot: BattleSnapshot) -> None:
    atomic_json(path, snapshot_to_document(snapshot))


def load_match(path: Path) -> BattleSnapshot:
    return document_to_snapshot(read_json(path))

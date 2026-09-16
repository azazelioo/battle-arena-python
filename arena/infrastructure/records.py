"""Persistent settings, three slots and a deduplicated history of 50 results."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from arena.domain.model import BattleSnapshot, History, Phase, integer
from .storage import (
    StorageError, array, atomic_json, document_to_snapshot, number, obj,
    read_json, snapshot_to_document, string,
)


@dataclass(frozen=True)
class Settings:
    bot_delay_ms: int = 300
    font_size: int = 12

    def __post_init__(self) -> None:
        integer(self.bot_delay_ms, 0, 3000)
        integer(self.font_size, 10, 20)


def load_settings(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    try:
        data = read_json(path)
        if not isinstance(data, dict) or set(data) - {"bot_delay_ms", "font_size"}:
            raise ValueError("Неизвестная настройка")
        return Settings(number(data.get("bot_delay_ms", 300)),
                        number(data.get("font_size", 12)))
    except (ValueError, TypeError) as error:
        raise StorageError(f"Неверные настройки: {error}") from error


def save_settings(path: Path, settings: Settings) -> None:
    atomic_json(path, asdict(settings))


@dataclass(frozen=True)
class MatchSummary:
    match_id: str
    completed_at: str
    snapshot: BattleSnapshot

    @classmethod
    def from_snapshot(cls, snapshot: BattleSnapshot) -> MatchSummary:
        if snapshot.phase != Phase.FINISHED:
            raise ValueError("В историю попадают только законченные бои")
        return cls(snapshot.match_id, datetime.now(timezone.utc).isoformat(), snapshot)


class MatchRepository:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def slot(self, index: int) -> Path:
        integer(index, 1, 3)
        return self.directory / f"slot-{index}.json"

    @property
    def history_path(self) -> Path:
        return self.directory / "history.json"

    @property
    def settings_path(self) -> Path:
        return self.directory / "settings.json"

    def history(self) -> History[MatchSummary]:
        result: History[MatchSummary] = History(50)
        if not self.history_path.exists():
            return result
        try:
            data = obj(read_json(self.history_path, maximum_bytes=32_000_000), {"schema_version", "matches"})
            if number(data["schema_version"]) != 1:
                raise ValueError("Неизвестная версия истории")
            seen: set[str] = set()
            for entry in array(data["matches"], 50):
                entry = obj(entry, {"completed_at", "document"})
                snapshot = document_to_snapshot(entry["document"])
                completed_at = string(entry["completed_at"])
                datetime.fromisoformat(completed_at)
                if snapshot.phase != Phase.FINISHED or snapshot.match_id in seen:
                    raise ValueError("Незаконченный или повторный матч в истории")
                seen.add(snapshot.match_id)
                result.append(MatchSummary(snapshot.match_id, completed_at, snapshot))
            return result
        except (ValueError, TypeError, KeyError) as error:
            raise StorageError(f"Неверная история: {error}") from error

    def add_result(self, snapshot: BattleSnapshot) -> None:
        summary = MatchSummary.from_snapshot(snapshot)
        history = self.history()
        if any(entry.match_id == snapshot.match_id for entry in history):
            return
        history.append(summary)
        atomic_json(self.history_path, {
            "schema_version": 1,
            "matches": [{"completed_at": entry.completed_at,
                         "document": snapshot_to_document(entry.snapshot)}
                        for entry in history],
        })

    def clear_history(self) -> None:
        atomic_json(self.history_path, {"schema_version": 1, "matches": []})

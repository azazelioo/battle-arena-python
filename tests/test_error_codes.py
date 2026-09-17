"""Stable error codes let interfaces recover without matching Russian text."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from arena.application.controller import GameController
from arena.domain.model import Phase
from arena.infrastructure.errors import StorageCode, StorageError
from arena.infrastructure.records import MatchRepository, load_settings
from arena.infrastructure.storage import (
    atomic_json,
    document_to_snapshot,
    read_json,
    snapshot_to_document,
)


@pytest.mark.parametrize("code", list(StorageCode))
def test_every_error_has_message_code_and_recovery(code):
    error = StorageError("Ошибка", code, Path("slot.json"))
    assert str(error) == "Ошибка"
    assert error.message == "Ошибка"
    assert error.code == code
    assert error.path == Path("slot.json")
    assert error.recovery
    assert code.value in error.details()
    assert error.recovery in error.details()


def test_filesystem_failure_categories(tmp_path):
    with pytest.raises(StorageError) as missing:
        read_json(tmp_path / "missing")
    assert missing.value.code == StorageCode.FILE_NOT_FOUND
    with patch("pathlib.Path.open", side_effect=PermissionError("denied")):
        with pytest.raises(StorageError) as denied:
            read_json(tmp_path / "denied")
    assert denied.value.code == StorageCode.FILE_READ
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
        with pytest.raises(StorageError) as denied:
            atomic_json(tmp_path / "target", {})
    assert denied.value.code == StorageCode.FILE_WRITE


@pytest.mark.parametrize(
    "contents,code",
    [
        (b"\xff", StorageCode.INVALID_ENCODING),
        (b"{", StorageCode.INVALID_JSON),
        (b'{"a":1,"a":2}', StorageCode.INVALID_JSON),
    ],
)
def test_invalid_file_content_categories(tmp_path, contents, code):
    path = tmp_path / "slot.json"
    path.write_bytes(contents)
    with pytest.raises(StorageError) as error:
        read_json(path)
    assert error.value.code == code
    assert error.value.path == path


def test_oversized_file_preserves_specific_code(tmp_path):
    path = tmp_path / "slot.json"
    path.write_text("123456")
    with pytest.raises(StorageError) as error:
        read_json(path, maximum_bytes=5)
    assert error.value.code == StorageCode.FILE_TOO_LARGE


def test_version_and_schema_are_distinct(battle):
    document = json.loads(json.dumps(snapshot_to_document(battle.snapshot())))
    document["schema_version"] = 999
    with pytest.raises(StorageError) as version:
        document_to_snapshot(document)
    assert version.value.code == StorageCode.UNSUPPORTED_VERSION
    document["schema_version"] = 1
    document["battle"]["phase"] = "alien"
    with pytest.raises(StorageError) as schema:
        document_to_snapshot(document)
    assert schema.value.code == StorageCode.INVALID_SCHEMA


def test_invalid_outgoing_state_is_a_storage_error(battle):
    from dataclasses import replace

    state = replace(battle.snapshot(), phase=Phase.RESOLVING)
    with pytest.raises(StorageError) as error:
        snapshot_to_document(state)
    assert error.value.code == StorageCode.INVALID_SCHEMA


def test_settings_history_slot_and_missing_match_categories(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"font_size":false}')
    with pytest.raises(StorageError) as error:
        load_settings(settings)
    assert error.value.code == StorageCode.INVALID_SETTINGS
    repository = MatchRepository(tmp_path)
    repository.history_path.write_text("{}")
    with pytest.raises(StorageError) as error:
        repository.history()
    assert error.value.code == StorageCode.INVALID_HISTORY
    with pytest.raises(StorageError) as error:
        repository.slot(4)
    assert error.value.code == StorageCode.INVALID_SLOT
    with pytest.raises(StorageError) as error:
        GameController(tmp_path).save(1)
    assert error.value.code == StorageCode.NO_MATCH


@pytest.mark.parametrize("operation", ["pathlib.Path.mkdir", "os.fsync"])
def test_interrupted_write_keeps_original_and_cleans_up(tmp_path, operation):
    path = tmp_path / "slot.json"
    path.write_text('{"original": true}')
    with patch(operation, side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            atomic_json(path, {"replacement": True})
    assert json.loads(path.read_text()) == {"original": True}
    assert list(tmp_path.iterdir()) == [path]

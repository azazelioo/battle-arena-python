from enum import StrEnum
from pathlib import Path


class StorageCode(StrEnum):
    FILE_NOT_FOUND = "file_not_found"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_TOO_LARGE = "file_too_large"
    INVALID_ENCODING = "invalid_encoding"
    INVALID_JSON = "invalid_json"
    INVALID_SCHEMA = "invalid_schema"
    UNSUPPORTED_VERSION = "unsupported_version"
    INVALID_SETTINGS = "invalid_settings"
    INVALID_HISTORY = "invalid_history"
    NO_MATCH = "no_match"
    INVALID_SLOT = "invalid_slot"


class StorageError(ValueError):
    """A display message plus a stable code; never expose traceback to a UI."""

    def __init__(
        self,
        message: str,
        code: StorageCode = StorageCode.FILE_WRITE,
        path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path

    @property
    def recovery(self) -> str:
        hints = {
            StorageCode.FILE_NOT_FOUND: "Выберите существующий слот или файл.",
            StorageCode.FILE_READ: "Проверьте доступ к каталогу и повторите.",
            StorageCode.FILE_WRITE: (
                "Проверьте свободное место и права записи."
            ),
            StorageCode.FILE_TOO_LARGE: (
                "Выберите файл сохранения меньшего размера."
            ),
            StorageCode.INVALID_ENCODING: (
                "Сохранение должно быть текстом UTF-8."
            ),
            StorageCode.INVALID_JSON: "Используйте другую копию сохранения.",
            StorageCode.INVALID_SCHEMA: (
                "Используйте неповреждённое сохранение игры."
            ),
            StorageCode.UNSUPPORTED_VERSION: (
                "Откройте файл в совместимой версии игры."
            ),
            StorageCode.INVALID_SETTINGS: (
                "Задайте и сохраните настройки заново."
            ),
            StorageCode.INVALID_HISTORY: (
                "Восстановите историю из резервной копии."
            ),
            StorageCode.NO_MATCH: "Сначала начните или загрузите бой.",
            StorageCode.INVALID_SLOT: "Выберите слот 1, 2 или 3.",
        }
        return hints[self.code]

    def details(self) -> str:
        return f"{self.message}\n{self.recovery}\nКод ошибки: {self.code}"

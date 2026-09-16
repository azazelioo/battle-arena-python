"""Run with python -m arena, --cli or --test."""
from __future__ import annotations

import argparse
from pathlib import Path

from arena.application.controller import GameController


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Пошаговая боевая арена")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cli", action="store_true", help="Консольный интерфейс")
    mode.add_argument("--test", action="store_true", help="Запустить pytest")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".battle-arena",
                        help="Каталог сохранений и истории")
    args = parser.parse_args(argv)
    if args.test:
        try:
            import pytest
        except ImportError:
            parser.exit(2, 'Установите тестовые зависимости: pip install -e ".[dev]"\n')
        return int(pytest.main([str(Path(__file__).resolve().parent.parent / "tests")]))
    controller = GameController(args.data_dir)
    if args.cli:
        from arena.presentation.cli import Console
        return Console(controller).run()
    try:
        from arena.presentation.gui import run_gui
        return run_gui(controller)
    except ImportError as error:
        parser.exit(2, f"Tkinter недоступен: {error}. Используйте --cli.\n")
    except Exception as error:
        # TclError cannot be imported before handling missing tkinter.
        import tkinter
        if isinstance(error, tkinter.TclError):
            parser.exit(2, f"Не удалось открыть окно: {error}. Используйте --cli.\n")
        raise


if __name__ == "__main__":
    raise SystemExit(main())

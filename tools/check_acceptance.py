"""Fail CI when measured technical acceptance requirements regress."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

from count_lines import report


def inspect(root: Path, coverage_path: Path) -> list[str]:
    failures = []
    counts = report(root)
    code_lines = counts["totals"]["code"]
    if not 6500 <= code_lines <= 7500:
        failures.append(f"Code line count {code_lines} is outside 6500..7500")
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    totals = coverage["totals"]
    if totals["missing_lines"]:
        failures.append(
            f"Uncovered executable lines: {totals['missing_lines']}"
        )
    if totals["missing_branches"]:
        failures.append(f"Uncovered branches: {totals['missing_branches']}")
    for path in sorted((root / "arena").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), 1):
            if len(line) > 80:
                failures.append(
                    f"Line exceeds 80: {path.relative_to(root)}:{number}"
                )
        if "domain" not in path.parts:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            else:
                imports = []
            if any(name.startswith("tkinter") for name in imports):
                failures.append(f"Domain imports tkinter: {path.name}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("input", "print", "open")
            ):
                failures.append(
                    f"Domain performs I/O: {path.name}:{node.lineno}"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        failures = inspect(root, args.coverage)
    except (OSError, ValueError, KeyError) as error:
        print(f"Cannot read acceptance evidence: {error}")
        return 2
    for failure in failures:
        print(failure)
    if failures:
        return 1
    print(
        "PASS: line budget, full coverage, line length and domain boundaries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

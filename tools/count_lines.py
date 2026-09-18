from __future__ import annotations

import ast
import io
import json
import tokenize
from pathlib import Path


def count_file(path: Path) -> dict[str, int]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            if node.body and isinstance(node.body[0], ast.Expr):
                expression = node.body[0]
                if isinstance(expression.value, ast.Constant) and isinstance(
                    expression.value.value, str
                ):
                    doc_lines.update(
                        range(
                            expression.lineno,
                            (expression.end_lineno or expression.lineno) + 1,
                        )
                    )
    code_lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in (
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENDMARKER,
        ):
            token_lines = set(range(token.start[0], token.end[0] + 1))
            if not token_lines <= doc_lines:
                code_lines.update(token_lines)
    return {
        "physical": len(lines),
        "nonempty": sum(bool(line.strip()) for line in lines),
        "docstring": len(doc_lines),
        "code": len(code_lines),
    }


def report(root: Path) -> dict[str, object]:
    files = {
        str(path.relative_to(root)): count_file(path)
        for folder in ("arena", "tests", "tools")
        for path in sorted((root / folder).rglob("*.py"))
    }
    totals = {
        key: sum(value[key] for value in files.values())
        for key in ("physical", "nonempty", "docstring", "code")
    }
    return {
        "method": "token lines excluding comments and AST docstrings",
        "totals": totals,
        "files": files,
    }


if __name__ == "__main__":
    print(json.dumps(report(Path(__file__).resolve().parent.parent), indent=2))

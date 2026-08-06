"""Public API type-annotation audit."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_functions_have_argument_and_return_annotations() -> None:
    missing: list[str] = []
    for source_root in (ROOT / "src", ROOT / "config"):
        for path in sorted(source_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_") and node.name != "__init__":
                    continue

                relative = path.relative_to(ROOT)
                arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                for argument in arguments:
                    if argument.arg not in {"self", "cls"} and argument.annotation is None:
                        missing.append(f"{relative}:{node.lineno} {node.name}({argument.arg})")
                if node.args.vararg and node.args.vararg.annotation is None:
                    missing.append(f"{relative}:{node.lineno} {node.name}(*{node.args.vararg.arg})")
                if node.args.kwarg and node.args.kwarg.annotation is None:
                    missing.append(f"{relative}:{node.lineno} {node.name}(**{node.args.kwarg.arg})")
                if node.name != "__init__" and node.returns is None:
                    missing.append(f"{relative}:{node.lineno} {node.name} return")

    assert not missing, "Missing type annotations:\n" + "\n".join(missing)

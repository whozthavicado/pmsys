"""Spec (a): las dependencias van en un solo sentido y un test de import lo comprueba.

core <- infra <- ingest/evidence <- analysis <- synthesis <- decision <- ledger <- eval <- pipeline

La spec no ubica `normalize` ni `rules` en la cadena (ver ADR-0002), así que no se restringen.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pmsys

LAYERS: dict[str, int] = {
    "core": 0,
    "infra": 1,
    "ingest": 2,
    "evidence": 2,
    "analysis": 3,
    "synthesis": 4,
    "decision": 5,
    "ledger": 6,
    "eval": 7,
    "pipeline": 8,
}
ROOT = "pmsys"


def _imported_subpackages(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
            if node.module == ROOT:
                names += [f"{ROOT}.{a.name}" for a in node.names]
        for name in names:
            parts = name.split(".")
            if parts[0] == ROOT and len(parts) > 1:
                found.add(parts[1])
    return found


def violations(pkg_dir: Path) -> list[str]:
    """Devuelve 'archivo -> subpaquete' por cada import de una capa superior."""
    out: list[str] = []
    for sub, layer in LAYERS.items():
        folder = pkg_dir / sub
        if not folder.is_dir():
            continue
        for py in sorted(folder.rglob("*.py")):
            for target in _imported_subpackages(py):
                if LAYERS.get(target, -1) > layer:
                    out.append(f"{py.relative_to(pkg_dir)} -> {target}")
    return out


def test_no_upward_imports_in_package() -> None:
    assert violations(Path(pmsys.__file__).parent) == []


def test_checker_detects_upward_import(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "bad.py").write_text("from pmsys.decision import sizing\n")
    (tmp_path / "decision").mkdir()
    (tmp_path / "decision" / "ok.py").write_text("import pmsys.core.models\n")
    assert violations(tmp_path) == ["core/bad.py -> decision"]

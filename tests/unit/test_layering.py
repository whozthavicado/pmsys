"""Spec (a): las dependencias van en un solo sentido y un test de import lo comprueba.

core < infra < ingest < normalize < rules/evidence < analysis < synthesis < decision < ledger
< eval < pipeline < cli

Los niveles son enteros (ADR-0002): un módulo solo importa de niveles estrictamente menores, así
que dos módulos del mismo nivel no pueden importarse entre sí.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pmsys

LAYERS: dict[str, int] = {
    "core": 1,
    "infra": 2,
    "ingest": 3,
    "normalize": 4,
    "rules": 5,
    "evidence": 5,
    "analysis": 6,
    "synthesis": 7,
    "decision": 8,
    "ledger": 9,
    "eval": 10,
    "pipeline": 11,
    "cli": 12,
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


def _module_name(pkg_dir: Path, py: Path) -> str:
    rel = py.relative_to(pkg_dir)
    return rel.stem if len(rel.parts) == 1 else rel.parts[0]


def violations(pkg_dir: Path) -> list[str]:
    """Devuelve 'archivo -> subpaquete' por cada import de un nivel igual o superior."""
    out: list[str] = []
    for py in sorted(pkg_dir.rglob("*.py")):
        own = _module_name(pkg_dir, py)
        if own not in LAYERS:
            continue
        for target in _imported_subpackages(py):
            if target != own and LAYERS.get(target, 0) >= LAYERS[own]:
                out.append(f"{py.relative_to(pkg_dir)} -> {target}")
    return out


def test_no_upward_imports_in_package() -> None:
    assert violations(Path(pmsys.__file__).parent) == []


def test_checker_detects_upward_import(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "bad.py").write_text("from pmsys.decision import sizing\n")
    (tmp_path / "decision").mkdir()
    (tmp_path / "decision" / "ok.py").write_text("import pmsys.core.models\n")
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "peer.py").write_text("from pmsys.evidence import fetch\n")
    (tmp_path / "cli.py").write_text("import pmsys.pipeline\n")
    assert violations(tmp_path) == ["core/bad.py -> decision", "rules/peer.py -> evidence"]

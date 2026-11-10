"""Migrador (spec 1.4.0, AC-1.4/1): protocolo de FKs, huellas, orden y bootstrap."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pmsys.infra.db import MigrationError, SqliteDb, discover

from . import _dbkit as kit


def _write(d: Path, name: str, sql: str) -> None:
    (d / name).write_text(sql, encoding="utf-8")


def test_real_migrations_are_contiguous_0001_to_0005() -> None:
    assert [v for v, _ in discover(kit.MIGRATIONS)] == [1, 2, 3, 4, 5]


def test_migrate_applies_all_and_foreign_key_check_is_empty() -> None:
    db = SqliteDb(":memory:")
    assert db.migrate() == 5
    assert db.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.conn.execute("PRAGMA foreign_keys").fetchone() == (1,)  # restaurado tras migrar


def test_migrate_is_idempotent_and_records_sha() -> None:
    db = SqliteDb(":memory:")
    assert db.migrate() == 5
    assert db.migrate() == 5
    rows = db.conn.execute("SELECT version, sha256 FROM schema_migrations ORDER BY 1").fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5]
    assert all(len(r[1]) == 64 for r in rows)


def test_edited_applied_migration_is_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "0001_a.sql",
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL, sha256 TEXT NOT NULL);",
    )
    path = tmp_path / "x.db"
    SqliteDb(path, migrations_dir=tmp_path).migrate()
    _write(
        tmp_path,
        "0001_a.sql",
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL, sha256 TEXT NOT NULL); -- editada",
    )
    with pytest.raises(MigrationError, match="cambió"):
        SqliteDb(path, migrations_dir=tmp_path).migrate()


def test_gap_in_migration_numbers_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a.sql", "SELECT 1;")
    _write(tmp_path, "0003_c.sql", "SELECT 1;")
    with pytest.raises(MigrationError, match="contiguas"):
        discover(tmp_path)


_BASE = (
    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL,"
    " sha256 TEXT NOT NULL);\n"
    "CREATE TABLE parent (id INTEGER PRIMARY KEY);\n"
    "CREATE TABLE child (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES parent(id));\n"
)


def test_failing_script_rolls_back_atomically(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a.sql", _BASE)
    _write(tmp_path, "0002_bad.sql", "CREATE TABLE ok_t (x);\nINSERT INTO nope VALUES (1);\n")
    db = SqliteDb(tmp_path / "x.db", migrations_dir=tmp_path)
    with pytest.raises(sqlite3.OperationalError):
        db.migrate()
    assert "ok_t" not in kit.tables(db.conn)  # la 0002 se revirtió entera
    assert db.migrate(up_to=1) == 1
    assert db.conn.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_foreign_key_violation_after_script_rolls_back(tmp_path: Path) -> None:
    """foreign_keys=OFF deja pasar la violación; foreign_key_check la atrapa antes del COMMIT."""
    _write(tmp_path, "0001_a.sql", _BASE)
    _write(tmp_path, "0002_orphan.sql", "INSERT INTO child (id, pid) VALUES (1, 999);\n")
    db = SqliteDb(tmp_path / "x.db", migrations_dir=tmp_path)
    with pytest.raises(MigrationError, match="foreign_key_check"):
        db.migrate()
    assert db.conn.execute("SELECT count(*) FROM child").fetchone() == (0,)
    assert db.conn.execute("SELECT max(version) FROM schema_migrations").fetchone() == (1,)
    assert db.conn.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_foreign_keys_are_off_while_a_migration_runs(tmp_path: Path) -> None:
    """Prueba del protocolo: una reconstrucción con DROP TABLE no borra en cascada ni falla."""
    _write(
        tmp_path,
        "0001_a.sql",
        _BASE + "INSERT INTO parent VALUES (1);\nINSERT INTO child VALUES (1, 1);\n",
    )
    _write(
        tmp_path,
        "0002_rebuild.sql",
        "-- child-fks: child\n"
        "CREATE TABLE parent_new (id INTEGER PRIMARY KEY, extra TEXT);\n"
        "INSERT INTO parent_new (id) SELECT id FROM parent;\n"
        "DROP TABLE parent;\nALTER TABLE parent_new RENAME TO parent;\n",
    )
    db = SqliteDb(tmp_path / "x.db", migrations_dir=tmp_path)
    assert db.migrate() == 2
    assert db.conn.execute("SELECT count(*) FROM child").fetchone() == (1,)


def test_bootstrap_sets_wal_and_synchronous_on_a_file(tmp_path: Path) -> None:
    db = SqliteDb(tmp_path / "x.db")
    assert db.conn.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    assert db.conn.execute("PRAGMA synchronous").fetchone() == (1,)  # NORMAL


def test_pragmas_are_not_in_any_migration() -> None:
    for _, path in discover(kit.MIGRATIONS):
        text = path.read_text(encoding="utf-8").upper()
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("--"))
        assert "PRAGMA" not in code, path.name


def _fail_inside_tx(db: SqliteDb) -> None:
    with db.tx() as c:
        kit.market(c, "m2")
        raise RuntimeError("boom")


def test_tx_commits_and_rolls_back() -> None:
    db = SqliteDb(":memory:")
    db.migrate()
    with db.tx() as c:
        kit.market(c, "m1")
    with pytest.raises(RuntimeError, match="boom"):
        _fail_inside_tx(db)
    assert db.conn.execute("SELECT market_id FROM markets").fetchall() == [("m1",)]

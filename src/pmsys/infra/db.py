"""Conexión SQLite, bootstrap y migrador (spec (b) `Db`, (c) y protocolo de migración 1.4.0).

Reparto de PRAGMAs (ADR-0004), ninguno pertenece a una migración:

- ``foreign_keys`` es por conexión y no persiste: lo fija ``connect``.
- ``journal_mode=WAL`` persiste en el fichero y ``synchronous=NORMAL`` es por conexión: los fija
  ``bootstrap`` antes de migrar.

Protocolo de cada migración (spec 1.4.0): ``PRAGMA foreign_keys = OFF`` fuera de transacción,
``BEGIN``, el script y ``PRAGMA foreign_key_check`` (si devuelve filas, ``ROLLBACK`` y error),
``COMMIT`` y ``PRAGMA foreign_keys = ON``.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    """Fallo de migración. TODO: pasar a subclase de PmsysError cuando exista core.errors."""


class Db(Protocol):
    def migrate(self) -> int: ...  # devuelve versión aplicada
    def tx(self) -> AbstractContextManager[sqlite3.Connection]: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


def _ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _in_tx(conn: sqlite3.Connection) -> bool:
    return conn.in_transaction


def connect(path: str | Path) -> sqlite3.Connection:
    """Conexión en modo autocommit, con claves foráneas activas y espera ante bloqueos."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def bootstrap(conn: sqlite3.Connection) -> None:
    """Propiedades de la base que no son esquema: WAL (persiste) y synchronous=NORMAL."""
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")


def discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    """Migraciones ordenadas; exige una serie contigua 1..N sin duplicados."""
    found: list[tuple[int, Path]] = []
    for p in sorted(migrations_dir.iterdir()):
        m = _MIGRATION_RE.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    versions = [v for v, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"migraciones no contiguas: {versions}")
    return found


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _applied(conn: sqlite3.Connection) -> dict[int, str]:
    has = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not has:
        return {}
    rows = conn.execute("SELECT version, sha256 FROM schema_migrations ORDER BY version").fetchall()
    return {int(v): str(h) for v, h in rows}


class SqliteDb:
    def __init__(
        self,
        path: str | Path,
        *,
        migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._migrations_dir = migrations_dir
        self._now = now
        self.conn = connect(path)
        bootstrap(self.conn)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def tx(self) -> AbstractContextManager[sqlite3.Connection]:
        return self._tx()

    def migrate(self, up_to: int | None = None) -> int:
        migrations = discover(self._migrations_dir)
        applied = _applied(self.conn)
        for version, sha in applied.items():
            expected = dict(migrations).get(version)
            if expected is None:
                raise MigrationError(f"la base tiene la versión {version}, que no existe en disco")
            if sha256_file(expected) != sha:
                raise MigrationError(f"la migración {version} cambió después de aplicarse")
        for version, path in migrations:
            if version in applied or (up_to is not None and version > up_to):
                continue
            self._apply(version, path)
        return max(_applied(self.conn), default=0)

    def _apply(self, version: int, path: Path) -> None:
        script = path.read_text(encoding="utf-8")
        sha = sha256_file(path)
        conn = self.conn
        if _in_tx(conn):
            raise MigrationError("migrar exige estar fuera de una transacción")
        conn.execute("PRAGMA foreign_keys = OFF")  # 1. fuera de transacción
        try:
            if conn.execute("PRAGMA foreign_keys").fetchone() != (0,):
                raise MigrationError("no se pudo desactivar foreign_keys")
            try:
                conn.executescript("BEGIN;\n" + script)  # 2. BEGIN + script
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at, sha256) VALUES (?, ?, ?)",
                    (version, _ts(self._now()), sha),
                )
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise MigrationError(
                        f"migración {version}: foreign_key_check devolvió {broken}"
                    )
                conn.execute("COMMIT")  # 3. COMMIT
            except BaseException:
                if _in_tx(conn):
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

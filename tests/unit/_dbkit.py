"""Utilidades de test para las migraciones: bases en memoria hasta una versión y filas mínimas."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from pmsys.infra.db import SqliteDb

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "migrations"
SPEC = ROOT / "docs" / "spec.md"
T0 = "2026-12-01T12:00:00Z"
TS_MS = "2026-12-01T12:00:00.000Z"


def db_at(version: int) -> SqliteDb:
    db = SqliteDb(":memory:")
    assert db.migrate(up_to=version) == version
    return db


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {str(r[0]) for r in rows}


def spec_sql_blocks() -> list[str]:
    return re.findall(r"^```sql\n(.*?)^```$", SPEC.read_text(encoding="utf-8"), re.S | re.M)


def market(conn: sqlite3.Connection, mid: str = "m1", category: str = "a") -> None:
    conn.execute(
        "INSERT INTO markets (market_id, condition_id, question, rules_text, rules_sha, category,"
        " yes_token_id, no_token_id, neg_risk, active, closed, first_seen_at, updated_at, raw_json)"
        " VALUES (?, ?, 'q', 'r', 'sha', ?, 'y', 'n', 0, 1, 0, ?, ?, '{}')",
        (mid, "c-" + mid, category, T0, T0),
    )


def analysis(
    conn: sqlite3.Connection,
    aid: str = "a1",
    mid: str = "m1",
    *,
    t_evidence: str | None = T0,
    mid_t_evidence: float | None = 0.5,
    t0: str = T0,
    v11: bool = True,
) -> None:
    cols = (
        "analysis_id, idem_key, market_id, rules_version, revision, cycle_id, t0, mid_t0,"
        " verdict, analysis_json, created_at"
    )
    vals: list[object] = [aid, "k-" + aid, mid, "rv", 0, "cy", t0, 0.5, "NO_TRADE", "{}", T0]
    if v11:
        cols += ", t_evidence, mid_t_evidence"
        vals += [t_evidence, mid_t_evidence]
    conn.execute(
        f"INSERT INTO analyses ({cols}) VALUES ({','.join('?' * len(vals))})",
        vals,
    )


def forecast(
    conn: sqlite3.Connection,
    mid: str = "m1",
    aid: str = "a1",
    *,
    category: str = "a",
    t0: str = T0,
    t_evidence: str | None = T0,
    mid_t_evidence: float | None = 0.5,
    bias_version: str | None = "identity-v0",
) -> None:
    conn.execute(
        "INSERT INTO forecasts (market_id, analysis_id, t0, p_final, mid_t0, category, horizon_d,"
        " t_evidence, mid_t_evidence, bias_version) VALUES (?, ?, ?, 0.6, 0.5, ?, 10, ?, ?, ?)",
        (mid, aid, t0, category, t_evidence, mid_t_evidence, bias_version),
    )


def decision(conn: sqlite3.Connection, did: str = "d1", aid: str = "a1") -> None:
    conn.execute(
        "INSERT INTO decisions (decision_id, analysis_id, filters_json, outcome, created_at)"
        " VALUES (?, ?, '{}', 'SIZED', ?)",
        (did, aid, T0),
    )


def position(
    conn: sqlite3.Connection,
    pid: str = "p1",
    *,
    did: str = "d1",
    mid: str = "m1",
    mode: str = "paper",
    opened_at: str = T0,
    clv_status: str = "pending",
) -> None:
    conn.execute(
        "INSERT INTO positions (position_id, decision_id, mode, market_id, side, shares,"
        " entry_price, fee_paid, opened_at, status, clv_status)"
        " VALUES (?, ?, ?, ?, 'YES', 5, 0.5, 0, ?, 'open', ?)",
        (pid, did, mode, mid, opened_at, clv_status),
    )


def calib(
    conn: sqlite3.Connection,
    version: str,
    applies_from: str,
    applies_to: str | None,
    cutoff: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO calibration_params (version, fitted_at, n_train, shrink_w, platt_a, platt_b,"
        " bucket_table_json, oos_delta_brier, active, fit_from_utc, cutoff_utc, applies_from_utc,"
        " applies_to_utc, n_cells_ok, n_cells_pooled, n_cells_identity)"
        " VALUES (?, ?, 0, 0.3, 0, 1, '{}', 0, 1, ?, ?, ?, ?, 0, 0, 0)",
        (version, T0, "2025-01-01T00:00:00Z", cutoff or applies_from, applies_from, applies_to),
    )

"""Tests de esquema por migración (spec (c) y criterios AC-B5, AC-1.2/*, AC-C*, AC-1.4/*)."""

from __future__ import annotations

import re
import sqlite3

import pytest

from pmsys.infra.db import discover

from . import _dbkit as kit

ABORT = sqlite3.IntegrityError


def _full() -> sqlite3.Connection:
    return kit.db_at(5).conn


def _seed(conn: sqlite3.Connection, v11: bool = True) -> None:
    kit.market(conn)
    kit.analysis(conn, v11=v11)


# --- el SQL de disco es el de la spec -------------------------------------------------------


def test_migrations_match_spec_blocks() -> None:
    blocks = kit.spec_sql_blocks()
    assert len(blocks) == 5
    for (_, path), block in zip(discover(kit.MIGRATIONS), blocks, strict=True):
        text = path.read_text(encoding="utf-8")
        if path.name.startswith("0001"):
            text = text.split("\n\n", 1)[1]  # cabecera ADR-0004
            block = block.split("\n\n", 1)[1]  # PRAGMA de la spec
        assert text == block, path.name


# --- 0001 -------------------------------------------------------------------------------


def test_0001_has_17_tables_and_enforces_fks() -> None:
    conn = kit.db_at(1).conn
    assert len(kit.tables(conn)) == 17
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        kit.analysis(conn, v11=False)  # market inexistente


def test_0001_forecasts_are_immutable() -> None:
    conn = kit.db_at(1).conn
    kit.market(conn)
    kit.analysis(conn, v11=False)
    conn.execute("INSERT INTO forecasts VALUES ('m1','a1',?,0.6,0.5,'a',10)", (kit.T0,))
    with pytest.raises(ABORT, match="immutable"):
        conn.execute("UPDATE forecasts SET p_final = 0.7")
    with pytest.raises(ABORT, match="immutable"):
        conn.execute("DELETE FROM forecasts")


def test_0001_check_constraints() -> None:
    conn = kit.db_at(1).conn
    with pytest.raises(ABORT):
        kit.market(conn, category="z")
    with pytest.raises(ABORT):
        conn.execute("INSERT INTO price_points VALUES ('t', 1, 1.5)")


# --- 0002 (D1-D6) -----------------------------------------------------------------------


def test_0002_has_24_tables() -> None:
    assert len(kit.tables(kit.db_at(2).conn)) == 24


def test_0002_rejects_analysis_without_mid_t_evidence() -> None:
    conn = kit.db_at(2).conn
    kit.market(conn)
    with pytest.raises(ABORT, match="required"):
        kit.analysis(conn, mid_t_evidence=None)


def test_0002_rejects_forecast_in_category_other_and_late_evidence() -> None:
    conn = kit.db_at(2).conn
    kit.market(conn, "m1", "other")
    kit.market(conn, "m2", "a")
    kit.analysis(conn, "a1", "m1")
    kit.analysis(conn, "a2", "m2")
    with pytest.raises(ABORT, match="invariant"):
        kit.forecast(conn, "m1", "a1", category="other", bias_version="v")
    with pytest.raises(ABORT, match="invariant"):
        kit.forecast(conn, "m2", "a2", t_evidence="2026-12-02T00:00:00Z", bias_version="v")
    kit.forecast(conn, "m2", "a2", bias_version="v")  # un forecast válido entra


def test_0002_rejects_bias_table_applied_before_its_cutoff() -> None:
    conn = kit.db_at(2).conn
    with pytest.raises(ABORT, match="cutoff"):
        kit.calib(
            conn,
            "v1",
            "2026-11-01T00:00:00Z",
            "2026-12-01T00:00:00Z",
            cutoff="2026-12-01T00:00:00Z",
        )


def test_0002_market_ref_class_is_frozen() -> None:
    conn = kit.db_at(2).conn
    kit.market(conn)
    conn.execute("INSERT INTO ref_classes VALUES ('c1','{}',0,?,20,5,'ms',?)", (kit.T0, kit.T0))
    conn.execute("INSERT INTO market_ref_class VALUES ('m1','sha','rv','c1')")
    with pytest.raises(ABORT, match="frozen"):
        conn.execute("UPDATE market_ref_class SET rules_sha = 'x'")


# --- 0003 (B5, 1.2/M4, M6, M7) ----------------------------------------------------------


def test_0003_analyses_are_immutable_and_check_t_evidence() -> None:
    conn = kit.db_at(3).conn
    _seed(conn)
    with pytest.raises(ABORT, match="immutable"):
        conn.execute("UPDATE analyses SET p_final = 0.9")
    with pytest.raises(ABORT, match="immutable"):
        conn.execute("DELETE FROM analyses")
    with pytest.raises(ABORT, match="t_evidence"):
        kit.analysis(conn, "a2", t_evidence="2026-12-02T00:00:00Z")


def test_0003_forecast_needs_an_existing_valid_bias_version() -> None:
    conn = kit.db_at(3).conn
    _seed(conn)
    with pytest.raises(ABORT, match="invariant"):
        kit.forecast(conn, bias_version="no-existe")
    kit.forecast(conn, bias_version="identity-v0")


def test_0003_identity_rejected_when_a_fitted_version_is_current() -> None:
    conn = kit.db_at(3).conn
    _seed(conn)
    kit.calib(conn, "v1", "2026-12-01T00:00:00Z", "9999-12-31T23:59:59Z")
    with pytest.raises(ABORT, match="invariant"):
        kit.forecast(conn, bias_version="identity-v0")
    kit.forecast(conn, bias_version="v1")


def test_0003_ref_class_tables_cannot_be_deleted() -> None:
    conn = kit.db_at(3).conn
    kit.market(conn)
    conn.execute("INSERT INTO ref_classes VALUES ('c1','{}',0,?,20,5,'ms',?)", (kit.T0, kit.T0))
    conn.execute("INSERT INTO ref_class_members VALUES ('c1','m1')")
    conn.execute("INSERT INTO market_ref_class VALUES ('m1','sha','rv','c1')")
    for table in ("ref_classes", "ref_class_members", "market_ref_class"):
        with pytest.raises(ABORT, match="frozen"):
            conn.execute(f"DELETE FROM {table}")
    with pytest.raises(ABORT, match="frozen"):
        conn.execute("UPDATE ref_classes SET n = 21")


def test_0003_timestamps_with_milliseconds_only_in_book_and_equity() -> None:
    conn = kit.db_at(3).conn
    with pytest.raises(ABORT, match="sss"):
        conn.execute("INSERT INTO book_snapshots VALUES ('t', ?, 0.4, 0.5, '{}')", (kit.T0,))
    conn.execute("INSERT INTO book_snapshots VALUES ('t', ?, 0.4, 0.5, '{}')", (kit.TS_MS,))
    with pytest.raises(ABORT, match="sss"):
        conn.execute("INSERT INTO equity VALUES ('paper', ?, 50, 50, 50, 0)", (kit.T0,))
    conn.execute("INSERT INTO equity VALUES ('paper', ?, 50, 50, 50, 0)", (kit.TS_MS,))


# --- 0004 (C1, C2, C3, C4, C6, C9) ------------------------------------------------------


def _with_decision(conn: sqlite3.Connection) -> None:
    _seed(conn)
    kit.decision(conn)


def test_0004_accepts_live_6b_c_and_rejects_unknown_mode() -> None:
    conn = kit.db_at(4).conn
    _with_decision(conn)
    kit.position(conn, "p1", mode="live_6b_c")
    with pytest.raises(ABORT):
        kit.position(conn, "p2", mode="live_9z")


def test_0004_p4_view_counts_a_market_once_and_prefers_live() -> None:
    conn = kit.db_at(4).conn
    _with_decision(conn)
    kit.position(conn, "pp", mode="paper", clv_status="measured")
    kit.position(conn, "p6a", mode="live_6a", clv_status="measured")
    kit.position(
        conn, "plive", mode="live_6b_c", opened_at="2026-12-02T00:00:00Z", clv_status="measured"
    )
    assert conn.execute("SELECT position_id FROM v_p4_picks").fetchall() == [("plive",)]


def test_0004_clv_must_be_6h_after_entry() -> None:
    conn = kit.db_at(4).conn
    _with_decision(conn)
    kit.position(conn)
    with pytest.raises(ABORT, match="C2"):
        conn.execute("UPDATE positions SET t_clv='2026-12-01T13:00:00Z', clv_status='measured'")
    conn.execute("UPDATE positions SET t_clv='2026-12-01T18:00:00Z', clv_status='measured'")


def test_0004_rejects_overlapping_bias_versions_and_edits() -> None:
    conn = kit.db_at(4).conn
    kit.calib(conn, "v1", "2026-12-01T00:00:00Z", "2027-01-01T00:00:00Z")
    with pytest.raises(ABORT, match="overlapping"):
        kit.calib(conn, "v2", "2026-12-15T00:00:00Z", "2027-02-01T00:00:00Z")
    with pytest.raises(ABORT, match="immutable"):
        conn.execute("UPDATE calibration_params SET shrink_w = 0.5")
    with pytest.raises(ABORT, match="immutable"):
        conn.execute("DELETE FROM calibration_params WHERE version = 'identity-v0'")


def test_0004_fallback_to_identity_is_logged() -> None:
    conn = kit.db_at(4).conn
    _seed(conn)
    kit.calib(conn, "v1", "2026-11-01T00:00:00Z", "2026-11-30T00:00:00Z")
    kit.forecast(conn, bias_version="identity-v0")  # t0 posterior a v1: cae a identidad
    assert conn.execute("SELECT last_fitted_version FROM bias_fallback_log").fetchall() == [("v1",)]


def test_0004_verified_label_requires_excerpt_found() -> None:
    conn = kit.db_at(4).conn
    _seed(conn)
    conn.execute(
        "INSERT INTO evidence VALUES ('e1','http://x','us','src','A',NULL,?, 'x','cs',0)", (kit.T0,)
    )
    with pytest.raises(ABORT, match="C6"):
        conn.execute("INSERT INTO analysis_evidence VALUES ('a1','e1','support','VERIFICADO')")
    conn.execute("INSERT INTO analysis_evidence VALUES ('a1','e1','support','INFERIDO')")


# --- 0005 (contigüidad, t_clv terminal) -------------------------------------------------


def test_0005_has_one_open_version_and_identity_is_the_first_link() -> None:
    conn = _full()
    assert conn.execute("SELECT version, applies_to_utc FROM calibration_params").fetchall() == [
        ("identity-v0", None)
    ]
    assert "bias_fallback_log" not in kit.tables(conn)


def test_0005_append_closes_previous_open_version() -> None:
    conn = _full()
    kit.calib(conn, "v1", "2026-12-01T00:00:00Z", None)
    rows = conn.execute(
        "SELECT version, applies_to_utc FROM calibration_params ORDER BY applies_from_utc"
    ).fetchall()
    assert rows == [("identity-v0", "2026-12-01T00:00:00Z"), ("v1", None)]


def test_0005_closed_new_version_is_rejected() -> None:
    with pytest.raises(ABORT, match="must be open"):
        kit.calib(_full(), "v1", "2026-12-01T00:00:00Z", "2027-01-01T00:00:00Z")


def test_0005_version_starting_before_the_open_one_is_rejected() -> None:
    conn = _full()
    kit.calib(conn, "v1", "2026-12-01T00:00:00Z", None)
    with pytest.raises(ABORT, match="after the open version start"):
        kit.calib(conn, "v0", "2026-11-01T00:00:00Z", None)


def test_0005_only_closing_the_open_version_is_allowed() -> None:
    conn = _full()
    with pytest.raises(ABORT, match="only closing"):
        conn.execute("UPDATE calibration_params SET shrink_w = 0.5")
    conn.execute("UPDATE calibration_params SET applies_to_utc = '2026-12-01T00:00:00Z'")
    with pytest.raises(ABORT, match="only closing"):  # reapertura
        conn.execute("UPDATE calibration_params SET applies_to_utc = NULL")


def test_0005_retroactive_version_cannot_reassign_existing_forecasts() -> None:
    conn = _full()
    _seed(conn)
    kit.forecast(conn, t0="2026-12-10T00:00:00Z", bias_version="identity-v0")
    with pytest.raises(ABORT, match="reassign"):
        kit.calib(conn, "v1", "2026-12-05T00:00:00Z", None)
    kit.calib(conn, "v1", "2026-12-11T00:00:00Z", None)  # posterior a todo forecast: válida


def test_0005_forecast_accepts_the_open_version() -> None:
    conn = _full()
    _seed(conn)
    kit.forecast(conn, bias_version="identity-v0")


def test_0005_terminal_clv_basis_skips_the_6h_floor() -> None:
    conn = _full()
    _with_decision(conn)
    kit.position(conn)
    with pytest.raises(ABORT, match="t_clv rule"):  # standard a 3 h: viola el suelo
        conn.execute(
            "UPDATE positions SET t_clv='2026-12-01T15:00:00Z', clv_basis='standard',"
            " clv_status='measured'"
        )
    conn.execute(
        "UPDATE positions SET t_clv='2026-12-01T15:00:00Z', clv_basis='terminal_1h',"
        " clv_status='measured'"
    )
    with pytest.raises(ABORT, match="t_clv rule"):  # nunca antes o igual que la entrada
        conn.execute("UPDATE positions SET t_clv='2026-12-01T12:00:00Z', clv_status='measured'")


def test_0005_positions_keep_their_own_fks_after_rebuild() -> None:
    conn = _full()
    kit.market(conn)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        kit.position(conn, did="no-existe")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


# --- AC-1.4/1: reconstrucciones con FKs hijas -------------------------------------------

_DROP = re.compile(r"^\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)", re.I | re.M)
_HEADER = re.compile(r"^--\s*child-fks:\s*(.+)$", re.I | re.M)


def rebuilt_with_child_fks(sql: str, conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Tablas que el script reconstruye (DROP TABLE) y que otra tabla referencia."""
    out: dict[str, set[str]] = {}
    for table in _DROP.findall(sql):
        children = {
            str(r[0])
            for r in conn.execute(
                "SELECT m.name FROM sqlite_master m, pragma_foreign_key_list(m.name) f"
                " WHERE m.type = 'table' AND m.name <> ? AND f.\"table\" = ?",
                (table, table),
            )
        }
        if children:
            out[table] = children
    return out


def undeclared(sql: str, conn: sqlite3.Connection) -> dict[str, set[str]]:
    header = _HEADER.search(sql)
    declared = {t.strip() for t in header.group(1).split(",")} if header else set()
    return {t: c - declared for t, c in rebuilt_with_child_fks(sql, conn).items() if c - declared}


def test_no_migration_rebuilds_a_table_with_undeclared_child_fks() -> None:
    db = kit.SqliteDb(":memory:")
    for version, path in discover(kit.MIGRATIONS):
        sql = path.read_text(encoding="utf-8")
        assert undeclared(sql, db.conn) == {}, path.name
        db.migrate(up_to=version)


def test_checker_flags_a_rebuild_of_a_table_with_child_fks() -> None:
    conn = kit.db_at(1).conn
    bad = (
        "CREATE TABLE markets_new (x);\nDROP TABLE markets;\n"
        "ALTER TABLE markets_new RENAME TO markets;"
    )
    assert "analyses" in undeclared(bad, conn)["markets"]
    declared = "-- child-fks: analyses, positions, clob_params, rules_specs\n" + bad
    assert "analyses" not in undeclared(declared, conn).get("markets", set())

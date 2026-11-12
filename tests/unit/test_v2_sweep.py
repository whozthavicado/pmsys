"""scripts/v2_sweep.py: barrido de umaResolutionStatus con HTTP falso (sin red)."""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pmsys.core.jsontypes import JsonValue

_PATH = Path(__file__).parents[2] / "scripts" / "v2_sweep.py"
_spec = importlib.util.spec_from_file_location("v2_sweep", _PATH)
assert _spec is not None
assert _spec.loader is not None
v2 = importlib.util.module_from_spec(_spec)
sys.modules["v2_sweep"] = v2
_spec.loader.exec_module(v2)

NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)


def mk(mid: str, status: JsonValue = "__absent__") -> dict[str, JsonValue]:
    m: dict[str, JsonValue] = {"id": mid, "conditionId": f"0x{mid}"}
    if status != "__absent__":
        m["umaResolutionStatus"] = status
    return m


class FakeHttp:
    """Responde según ``closed`` y ``after_cursor``; registra las llamadas."""

    def __init__(self, pages: Mapping[tuple[str, str | None], JsonValue]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonValue:
        p = dict(params or {})
        self.calls.append((url, p))
        if url.endswith("/markets"):
            return {"markets": [mk("ex-open", p["uma_resolution_status"])]}
        return self.pages[(p["closed"], p.get("after_cursor"))]

    def post_json(self, url: str, body: JsonValue) -> JsonValue:
        raise AssertionError("el barrido es de solo lectura")


def pages() -> dict[tuple[str, str | None], JsonValue]:
    return {
        ("false", None): {"markets": [mk("1", None), mk("2", "proposed")], "next_cursor": "c1"},
        ("false", "c1"): {"markets": [mk("3", "disputed"), mk("4")], "next_cursor": None},
        ("true", None): {"markets": [mk("5", "resolved"), mk("6", "proposed")], "next_cursor": ""},
    }


def test_sweep_counts_values_nulls_and_missing_field_across_both_passes() -> None:
    res = v2.sweep(FakeHttp(pages()), NOW)
    assert res.markets_seen == 6
    assert {k: s.count for k, s in res.values.items()} == {
        "proposed": 2, "disputed": 1, "resolved": 1,
    }  # fmt: skip
    assert (res.null_count, res.missing_field_count) == (1, 1)
    assert res.values["proposed"].open_count == 1
    assert res.values["proposed"].closed_count == 1
    assert res.values["proposed"].example_open_id == "2"
    assert res.values["proposed"].example_closed_id == "6"
    assert res.pages == {"open": 2, "closed": 1}
    assert res.truncated == []


def test_sweep_requests_follow_the_spec_and_are_read_only() -> None:
    http = FakeHttp(pages())
    v2.sweep(http, NOW)
    open_first, open_next, closed = (p for _, p in http.calls)
    assert open_first == {"closed": "false", "limit": "100"}
    assert open_next == {"closed": "false", "limit": "100", "after_cursor": "c1"}
    assert closed == {
        "closed": "true",
        "end_date_min": "2025-11-10T12:00:00Z",
        "end_date_max": "2026-11-10T12:00:00Z",
        "limit": "100",
    }
    assert all(u == "https://gamma-api.polymarket.com/markets/keyset" for u, _ in http.calls)
    forbidden = {"offset", "order"}
    assert all(not (forbidden & set(p)) for _, p in http.calls)


def test_non_string_values_are_recorded_and_flagged() -> None:
    http = FakeHttp(
        {
            ("false", None): {"markets": [mk("1", 3), mk("2", "null")]},
            ("true", None): {"markets": []},
        }
    )
    res = v2.sweep(http, NOW)
    assert set(res.values) == {"3", "null"}  # la cadena "null" no se confunde con None
    assert res.non_string_types == {"int"}
    assert res.null_count == 0


def test_cursor_loop_aborts() -> None:
    http = FakeHttp(
        {
            ("false", None): {"markets": [mk("1", "a")], "next_cursor": "c"},
            ("false", "c"): {"markets": [mk("2", "a")], "next_cursor": "c"},
        }
    )
    with pytest.raises(v2.SweepAborted, match="bucle"):
        v2.sweep(http, NOW)


def test_max_pages_marks_the_sweep_as_incomplete() -> None:
    http = FakeHttp(
        {
            ("false", None): {"markets": [mk("1", "a")], "next_cursor": "c1"},
            ("true", None): {"markets": [mk("2", "b")]},
        }
    )
    res = v2.sweep(http, NOW, max_pages=1)
    assert res.truncated == ["open"]
    assert res.pages["open"] == 1


def test_extract_markets_shapes() -> None:
    assert [m["id"] for m in v2.extract_markets([mk("1")])] == ["1"]
    assert [m["id"] for m in v2.extract_markets({"data": [mk("1")], "next_cursor": "x"})] == ["1"]
    assert v2.extract_markets({"markets": []}) == []
    with pytest.raises(v2.SweepAborted, match="SIN VERIFICAR"):
        v2.extract_markets({"a": [mk("1")], "b": [mk("2")]})
    with pytest.raises(v2.SweepAborted, match="SIN VERIFICAR"):
        v2.extract_markets({"markets": [{"id": "sin conditionId"}]})
    with pytest.raises(v2.SweepAborted, match="SIN VERIFICAR"):
        v2.extract_markets({"detalle": "x"} | {"n": 3})


def test_find_examples_uses_the_documented_filter_only_for_values_without_open_example() -> None:
    http = FakeHttp(pages())
    res = v2.sweep(http, NOW)
    http.calls.clear()
    v2.find_examples(http, res)
    assert [p["uma_resolution_status"] for _, p in http.calls] == ["resolved"]
    assert http.calls[0][1] == {
        "uma_resolution_status": "resolved",
        "closed": "false",
        "limit": "1",
    }
    assert res.values["resolved"].example_open_id == "ex-open"


def test_merge_fixture_matches_spec_shape_and_keeps_first_observation() -> None:
    res = v2.sweep(FakeHttp(pages()), NOW)
    first = v2.merge_fixture(None, res, "2026-11-10T12:00:00Z")
    assert first["proposed"] == {
        "count": 2,
        "market_id_ejemplo": "2",
        "observado_en": "2026-11-10T12:00:00Z",
    }
    second = v2.merge_fixture(first, res, "2026-11-11T12:00:00Z")
    assert second["proposed"]["observado_en"] == "2026-11-10T12:00:00Z"
    assert set(second["proposed"]) == {"count", "market_id_ejemplo", "observado_en"}


def test_proposed_map_is_valid_toml_and_unknown_values_stay_unreviewed() -> None:
    http = FakeHttp(
        {
            ("false", None): {"markets": [mk("1", "proposed"), mk("2", 'raro"valor')]},
            ("true", None): {"markets": []},
        }
    )
    res = v2.sweep(http, NOW)
    parsed = tomllib.loads(v2.propose_map(res))["map"]
    assert parsed == {"proposed": "proposed", 'raro"valor': "REVISAR"}
    assert "REVISAR" not in v2.STATES  # no es un estado válido: F8 sigue fail-closed


def test_main_writes_fixture_report_and_proposal_but_never_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    fixture = tmp_path / "fx" / "uma_status_values.json"
    code = v2.main(
        ["--fixture", str(fixture), "--reports-dir", str(tmp_path / "reports"), "--find-examples"],
        http=FakeHttp(pages()),
    )
    assert code == 0
    assert set(json.loads(fixture.read_text(encoding="utf-8"))) == {
        "proposed",
        "disputed",
        "resolved",
    }
    names = sorted(p.name for p in (tmp_path / "reports").iterdir())
    assert names[0] == "uma_status_map.proposed.toml"
    assert names[1].startswith("v2_sweep_")
    report = json.loads((tmp_path / "reports" / names[1]).read_text(encoding="utf-8"))
    assert report["barrido_incompleto"] == []
    assert report["valores_sin_mapear_a_estado"] == []
    assert not (tmp_path / "config").exists()


def test_main_exit_codes_for_incomplete_and_aborted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    base = ["--fixture", str(tmp_path / "f.json"), "--reports-dir", str(tmp_path / "r")]
    short = FakeHttp(
        {
            ("false", None): {"markets": [mk("1", "a")], "next_cursor": "c1"},
            ("true", None): {"markets": []},
        }
    )
    assert v2.main([*base, "--max-pages", "1"], http=short) == 3
    ambiguous = FakeHttp(
        {("false", None): {"a": [mk("1")], "b": [mk("2")]}, ("true", None): {"markets": []}}
    )
    assert v2.main(base, http=ambiguous) == 2


def test_on_page_hook_sees_every_page_with_running_counts() -> None:
    seen: list[tuple[str, int, int]] = []
    v2.sweep(
        FakeHttp(pages()),
        NOW,
        on_page=lambda name, n, res: seen.append((name, n, res.markets_seen)),
    )
    assert seen == [("open", 1, 2), ("open", 2, 4), ("closed", 1, 6)]


def test_main_writes_progress_and_partial_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(v2, "PROGRESS_EVERY", 1)
    monkeypatch.setattr(v2, "CHECKPOINT_EVERY", 2)
    code = v2.main(
        ["--fixture", str(tmp_path / "f.json"), "--reports-dir", str(tmp_path / "r")],
        http=FakeHttp(pages()),
    )
    assert code == 0
    assert "[open] página 1" in capsys.readouterr().err
    partial = json.loads((tmp_path / "r" / "v2_partial.json").read_text(encoding="utf-8"))
    assert partial["mercados_vistos"] == 4  # checkpoint tras la página 2 de «open»

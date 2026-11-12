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

from pmsys.core.errors import UpstreamError, UpstreamTimeout
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
    assert "uma_status_map.proposed.toml" in names
    assert "v2_state.json" not in names  # corrida terminada con éxito: el estado se borra
    report_name = next(n for n in names if n.startswith("v2_sweep_"))
    report = json.loads((tmp_path / "reports" / report_name).read_text(encoding="utf-8"))
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
    assert partial["mercados_vistos"] == 6  # el último guardado es el del fin de la pasada «closed»


def test_write_atomic_replaces_the_file_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "v2_partial.json"
    target.write_text("viejo", "utf-8")
    v2.write_atomic(target, '{"ok": true}')
    assert target.read_text("utf-8") == '{"ok": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["v2_partial.json"]


def test_write_atomic_keeps_the_previous_file_if_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "v2_partial.json"
    target.write_text("intacto", "utf-8")

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disco lleno")

    monkeypatch.setattr(v2.os, "replace", boom)
    with pytest.raises(OSError, match="disco lleno"):
        v2.write_atomic(target, "nuevo")
    assert target.read_text("utf-8") == "intacto"


# ── Reanudación, cruce y paciencia ───────────────────────────────────────


def _no_sleep(_s: float) -> None:
    return None


class DyingHttp(FakeHttp):
    """Como FakeHttp, pero lanza un error tras ``die_after`` peticiones, como un corte largo."""

    def __init__(self, pages_: Mapping[tuple[str, str | None], JsonValue], die_after: int) -> None:
        super().__init__(pages_)
        self.die_after = die_after

    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonValue:
        if len(self.calls) >= self.die_after:
            raise UpstreamError(host="gamma-api.polymarket.com", status=0)
        return super().get_json(url, params)


def test_resume_after_a_crash_gives_the_same_result_as_an_uninterrupted_run() -> None:
    whole = v2.sweep(FakeHttp(pages()), NOW)

    saved: list[tuple[v2.SweepResult, v2.Cursor]] = []
    snaps: list[str] = []

    def keep(res: v2.SweepResult, cur: v2.Cursor) -> None:
        snaps.append(v2.state_to_json(res, cur, "2026-11-10T12:00:00Z", 365))

    with pytest.raises(UpstreamError):
        v2.sweep(DyingHttp(pages(), die_after=2), NOW, on_checkpoint=keep, state=None, patience_s=0)
    assert snaps, "debió guardar estado antes de caerse"

    res0, cur0, observed, days = v2.state_from_json(snaps[-1])
    assert (observed, days) == ("2026-11-10T12:00:00Z", 365)
    saved.append((res0, cur0))
    resumed = v2.sweep(FakeHttp(pages()), NOW, state=saved[0], on_checkpoint=keep)

    def digest(r: v2.SweepResult) -> tuple[object, ...]:
        return (
            r.markets_seen,
            {k: (s.count, s.open_count, s.closed_count) for k, s in r.values.items()},
            {k: (c.values, c.null, c.absent) for k, c in r.cross.items()},
            r.null_count,
            r.missing_field_count,
            r.pages,
        )

    assert digest(resumed) == digest(whole)


def test_resume_does_not_recount_pages_already_in_the_saved_state() -> None:
    snaps: list[str] = []
    v2.sweep(
        FakeHttp(pages()),
        NOW,
        on_checkpoint=lambda r, c: snaps.append(
            v2.state_to_json(r, c, "2026-11-10T12:00:00Z", 365)
        ),
    )
    # Con CHECKPOINT_EVERY=10 solo guarda al terminar una pasada; reanudar desde ahí no repite nada.
    http = FakeHttp(pages())
    res, cur, _o, _d = v2.state_from_json(snaps[-1])
    again = v2.sweep(http, NOW, state=(res, cur))
    assert http.calls == []
    assert again.markets_seen == 6


def test_resume_continues_from_the_saved_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v2, "CHECKPOINT_EVERY", 1)
    snaps: list[str] = []
    with pytest.raises(UpstreamError):
        v2.sweep(
            DyingHttp(pages(), die_after=1),
            NOW,
            on_checkpoint=lambda r, c: snaps.append(
                v2.state_to_json(r, c, "2026-11-10T12:00:00Z", 365)
            ),
        )
    res, cur, _o, _d = v2.state_from_json(snaps[-1])
    assert (cur.phase, cur.after, cur.pages_in_pass) == ("open", "c1", 1)
    http = FakeHttp(pages())
    v2.sweep(http, NOW, state=(res, cur))
    first = http.calls[0][1]
    assert first["after_cursor"] == "c1"  # retoma en la página 2, no en la 1
    assert first["closed"] == "false"


def test_crosstab_separates_null_and_absent_by_open_and_closed() -> None:
    http = FakeHttp(
        {
            ("false", None): {"markets": [mk("1", None), mk("2"), mk("3", "proposed")]},
            ("true", None): {"markets": [mk("4"), mk("5"), mk("6", "resolved"), mk("7", None)]},
        }
    )
    res = v2.sweep(http, NOW)
    cross = v2.crosstab_fixture(res, "2026-11-10T12:00:00Z")
    assert cross["completo"] is True
    assert cross["abiertos"] == {"valores": {"proposed": 1}, "null": 1, "campo_ausente": 1}
    # Un cerrado sin campo es un resuelto sin estado: no se mezcla con un abierto sin propuesta.
    assert cross["cerrados"] == {"valores": {"resolved": 1}, "null": 1, "campo_ausente": 2}


def test_crosstab_is_marked_incomplete_when_the_page_cap_is_hit() -> None:
    http = FakeHttp(
        {
            ("false", None): {"markets": [mk("1", "a")], "next_cursor": "c1"},
            ("true", None): {"markets": []},
        }
    )
    res = v2.sweep(http, NOW, max_pages=1)
    assert v2.crosstab_fixture(res, "t")["completo"] is False


def test_page_cap_is_per_pass_and_defaults_high_enough_for_the_first_run() -> None:
    assert v2.DEFAULT_MAX_PAGES >= 10_000  # la pasada de cerrados pasó de 2.350 páginas
    http = FakeHttp(
        {
            ("false", None): {"markets": [mk("1", "a")], "next_cursor": "c1"},
            ("false", "c1"): {"markets": [mk("2", "a")]},
            ("true", None): {"markets": [mk("3", "b")], "next_cursor": "c2"},
            ("true", "c2"): {"markets": [mk("4", "b")]},
        }
    )
    res = v2.sweep(http, NOW, max_pages=2)  # 2 por pasada: 4 en total sin marcar incompleto
    assert res.truncated == []
    assert res.markets_seen == 4


def test_patience_retries_the_same_page_after_the_client_gives_up() -> None:
    class Flaky(FakeHttp):
        fails = 2

        def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonValue:
            if self.fails > 0:
                self.fails -= 1
                raise UpstreamError(host="gamma-api.polymarket.com", status=0)
            return super().get_json(url, params)

    http = Flaky(pages())
    sleeps: list[float] = []
    res = v2.sweep(http, NOW, patience_s=600, sleep=sleeps.append)
    assert res.markets_seen == 6
    assert sleeps == [v2.PATIENCE_STEP_S, v2.PATIENCE_STEP_S]
    # Agotada la paciencia, se rinde y propaga el error.
    always = Flaky(pages())
    always.fails = 99
    with pytest.raises(UpstreamError):
        v2.sweep(always, NOW, patience_s=120, sleep=_no_sleep)


def test_state_file_rejects_garbage_and_other_versions() -> None:
    with pytest.raises(v2.SweepAborted, match="ilegible"):
        v2.state_from_json('{"hola": 1}')
    with pytest.raises(v2.SweepAborted, match="ilegible"):
        v2.state_from_json("no es json")
    good = v2.state_to_json(v2.SweepResult(), v2.Cursor(), "t", 365)
    bad = good.replace('"version":1', '"version":99')
    with pytest.raises(v2.SweepAborted, match="otra versión"):
        v2.state_from_json(bad)


def test_main_refuses_to_overwrite_an_unfinished_state_and_resumes_with_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(v2, "CHECKPOINT_EVERY", 1)
    base = [
        "--fixture", str(tmp_path / "f.json"),
        "--crosstab", str(tmp_path / "x.json"),
        "--reports-dir", str(tmp_path / "r"),
        "--patience-min", "0",
    ]  # fmt: skip
    code = v2.main(base, http=DyingHttp(pages(), die_after=2))
    assert code == 4  # interrumpido, con estado guardado
    assert (tmp_path / "r" / "v2_state.json").exists()
    assert v2.main(base, http=FakeHttp(pages())) == 2  # sin --resume no pisa el estado
    assert v2.main([*base, "--resume"], http=FakeHttp(pages())) == 0
    crosstab = json.loads((tmp_path / "x.json").read_text("utf-8"))
    assert crosstab["completo"] is True
    assert crosstab["abiertos"]["null"] == 1
    assert crosstab["abiertos"]["campo_ausente"] == 1


def test_a_4xx_is_permanent_and_does_not_burn_the_patience() -> None:
    class Bad(FakeHttp):
        def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonValue:
            self.calls.append((url, dict(params or {})))
            raise UpstreamError(host="gamma-api.polymarket.com", status=400)

    sleeps: list[float] = []
    http = Bad(pages())
    with pytest.raises(UpstreamError):
        v2.sweep(http, NOW, patience_s=1800, sleep=sleeps.append)
    assert sleeps == []
    assert len(http.calls) == 1


@pytest.mark.parametrize(
    ("status", "transient"), [(0, True), (500, True), (503, True), (400, False), (404, False)]
)
def test_transient_classification(status: int, transient: bool) -> None:
    assert v2._is_transient(UpstreamError(host="h", status=status)) is transient
    assert v2._is_transient(UpstreamTimeout(host="h")) is True


def test_fixtures_are_written_even_if_find_examples_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    class ExamplesDown(FakeHttp):
        def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonValue:
            if url.endswith("/markets"):
                raise UpstreamError(host="gamma-api.polymarket.com", status=500)
            return super().get_json(url, params)

    code = v2.main(
        [
            "--find-examples",
            "--fixture", str(tmp_path / "f.json"),
            "--crosstab", str(tmp_path / "x.json"),
            "--reports-dir", str(tmp_path / "r"),
        ],
        http=ExamplesDown(pages()),
    )  # fmt: skip
    assert code == 0
    assert (tmp_path / "f.json").exists()
    assert (tmp_path / "x.json").exists()


def test_state_with_a_bad_date_is_a_clean_abort_not_a_traceback() -> None:
    good = v2.state_to_json(v2.SweepResult(), v2.Cursor(), "2026-11-10T12:00:00Z", 365)
    bad = good.replace("2026-11-10T12:00:00Z", "ayer por la tarde")
    with pytest.raises(v2.SweepAborted, match="fecha ilegible"):
        v2.state_from_json(bad)


def test_a_finished_run_leaves_no_state_so_the_next_one_starts_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    base = ["--fixture", str(tmp_path / "f.json"), "--crosstab", str(tmp_path / "x.json"),
            "--reports-dir", str(tmp_path / "r")]  # fmt: skip
    assert v2.main(base, http=FakeHttp(pages())) == 0
    assert not (tmp_path / "r" / "v2_state.json").exists()
    assert v2.main(base, http=FakeHttp(pages())) == 0  # una segunda corrida no la bloquea nada

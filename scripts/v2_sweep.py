"""V2 (B6): barrido del dominio de ``umaResolutionStatus`` en Gamma. Solo lectura (GET).

Uso, desde un entorno con acceso a gamma-api.polymarket.com (p. ej. el VPS):

    uv run python scripts/v2_sweep.py --find-examples

Hace el barrido de la spec (V2, «Método»): ``/markets/keyset`` con ``closed=false`` y con
``closed=true`` (resueltos en los últimos 365 días), cuenta cada valor distinto y, con
``--find-examples``, busca ejemplos de cada valor con el filtro ``uma_resolution_status`` de
``/markets``. Escribe:

- ``tests/fixtures/uma_status_values.json``  ``{valor: {count, market_id_ejemplo, observado_en}}``
- ``reports/v2_sweep_<fecha>.json``           informe completo (no versionado)
- ``reports/uma_status_map.proposed.toml``    PROPUESTA de mapeo, a revisar a mano

No escribe ``config/uma_status_map.toml``: el mapeo a los 4 estados lo decide una persona.

SIN VERIFICAR: la forma exacta del cuerpo de ``/markets/keyset`` y de ``/markets`` (en qué clave
viene la lista de mercados). El script la detecta (una única lista de objetos con
``conditionId``) y, si es ambigua, aborta y guarda la respuesta cruda en el informe.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pmsys.core.errors import SchemaDrift
from pmsys.core.jsontypes import JsonValue
from pmsys.infra.http import HttpClient, RetryingHttpClient, UrllibTransport

GAMMA = "https://gamma-api.polymarket.com"
STATUS_FIELD = "umaResolutionStatus"
PROGRESS_EVERY = 10
CHECKPOINT_EVERY = 50
PAGE_LIMIT = 100  # máximo de /markets/keyset (VERIFICADO)
STATES = ("open_no_proposal", "proposed", "disputed", "resolved")
# Coincidencia exacta de nombre, solo como sugerencia: el mapeo real lo confirma una persona.
SUGGESTIONS = {"proposed": "proposed", "disputed": "disputed", "resolved": "resolved"}


class SweepAborted(Exception):
    """El barrido no puede continuar sin inventar algo (forma de respuesta ambigua, bucle)."""


@dataclass
class ValueStat:
    count: int = 0
    open_count: int = 0
    closed_count: int = 0
    example_id: str | None = None
    example_open_id: str | None = None
    example_closed_id: str | None = None


@dataclass
class SweepResult:
    values: dict[str, ValueStat] = field(default_factory=dict)
    null_count: int = 0
    missing_field_count: int = 0
    non_string_types: set[str] = field(default_factory=set)
    markets_seen: int = 0
    pages: dict[str, int] = field(default_factory=dict)
    truncated: list[str] = field(default_factory=list)


def extract_markets(body: JsonValue) -> list[dict[str, JsonValue]]:
    """Devuelve la lista de mercados sin asumir la clave: lista de objetos con ``conditionId``."""
    candidates: list[list[JsonValue]] = []
    if isinstance(body, list):
        candidates.append(body)
    elif isinstance(body, dict):
        candidates += [v for v in body.values() if isinstance(v, list)]
    markets = [
        c for c in candidates if c and all(isinstance(m, dict) and "conditionId" in m for m in c)
    ]
    if len(markets) == 1:
        return [m for m in markets[0] if isinstance(m, dict)]
    if candidates and all(not c for c in candidates):
        return []  # página vacía: hay lista, y está vacía
    raise SweepAborted("forma de respuesta SIN VERIFICAR: no hay una única lista de mercados")


def next_cursor(body: JsonValue) -> str | None:
    if isinstance(body, dict):
        cur = body.get("next_cursor")
        if isinstance(cur, str) and cur:
            return cur
    return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(res: SweepResult, market: Mapping[str, JsonValue], *, closed: bool) -> None:
    res.markets_seen += 1
    if STATUS_FIELD not in market:
        res.missing_field_count += 1
        return
    raw = market[STATUS_FIELD]
    if raw is None:
        res.null_count += 1
        return
    if not isinstance(raw, str):
        res.non_string_types.add(type(raw).__name__)
    key = raw if isinstance(raw, str) else json.dumps(raw)
    stat = res.values.setdefault(key, ValueStat())
    mid = str(market.get("id", ""))
    stat.count += 1
    stat.example_id = stat.example_id or mid
    if closed:
        stat.closed_count += 1
        stat.example_closed_id = stat.example_closed_id or mid
    else:
        stat.open_count += 1
        stat.example_open_id = stat.example_open_id or mid


PageHook = Callable[[str, int, SweepResult], None]


def sweep(
    http: HttpClient,
    now: datetime,
    *,
    max_pages: int = 5000,
    closed_days: int = 365,
    on_page: PageHook | None = None,
) -> SweepResult:
    """Barrido completo: abiertos (sin fecha) y cerrados de los últimos ``closed_days`` días."""
    res = SweepResult()
    passes = {
        "open": {"closed": "false"},
        "closed": {
            "closed": "true",
            "end_date_min": _iso(now - timedelta(days=closed_days)),
            "end_date_max": _iso(now),
        },
    }
    for name, base in passes.items():
        cursor: str | None = None
        seen: set[str] = set()
        pages = 0
        while True:
            params = {**base, "limit": str(PAGE_LIMIT)}
            if cursor:
                params["after_cursor"] = cursor
            body = http.get_json(f"{GAMMA}/markets/keyset", params)
            pages += 1
            res.pages[name] = pages
            for market in extract_markets(body):
                _record(res, market, closed=name == "closed")
            if on_page is not None:
                on_page(name, pages, res)
            cursor = next_cursor(body)
            if cursor is None:
                break
            if cursor in seen:
                raise SweepAborted(f"{name}: el cursor se repite; paginación en bucle")
            seen.add(cursor)
            if pages >= max_pages:
                res.truncated.append(name)  # barrido incompleto: no sirve para cerrar V2
                break
    return res


def find_examples(http: HttpClient, res: SweepResult) -> None:
    """Completa ejemplos abiertos por valor con el filtro ``uma_resolution_status`` de /markets."""
    for value, stat in res.values.items():
        if stat.example_open_id is not None:
            continue
        body = http.get_json(
            f"{GAMMA}/markets",
            {"uma_resolution_status": value, "closed": "false", "limit": "1"},
        )
        for market in extract_markets(body)[:1]:
            stat.example_open_id = str(market.get("id", "")) or None


def merge_fixture(
    previous: Mapping[str, JsonValue] | None, res: SweepResult, observed_at: str
) -> dict[str, dict[str, JsonValue]]:
    """Fixture de la spec. Un valor ya visto conserva su primer ``observado_en`` y su ejemplo."""
    out: dict[str, dict[str, JsonValue]] = {}
    for value, stat in sorted(res.values.items()):
        old = previous.get(value) if previous else None
        first = old if isinstance(old, dict) else {}
        out[value] = {
            "count": stat.count,
            "market_id_ejemplo": first.get("market_id_ejemplo") or stat.example_id,
            "observado_en": first.get("observado_en") or observed_at,
        }
    return out


def propose_map(res: SweepResult) -> str:
    lines = [
        "# PROPUESTA generada por scripts/v2_sweep.py. Revisar a mano antes de copiar a",
        "# config/uma_status_map.toml. Estados válidos: " + ", ".join(STATES),
        '# Un valor sin sugerencia queda como "REVISAR" y falla F8 (fail-closed).',
        "[map]",
    ]
    for value in sorted(res.values):
        suggestion = SUGGESTIONS.get(value.lower(), "REVISAR")
        lines.append(f"{json.dumps(value)} = {json.dumps(suggestion)}")
    return "\n".join(lines) + "\n"


def _jl(items: Iterable[str]) -> list[JsonValue]:
    return list(items)


def build_report(res: SweepResult, observed_at: str) -> dict[str, JsonValue]:
    values: dict[str, JsonValue] = {
        v: {
            "count": s.count,
            "abiertos": s.open_count,
            "cerrados": s.closed_count,
            "ejemplo": s.example_id,
            "ejemplo_abierto": s.example_open_id,
            "ejemplo_cerrado": s.example_closed_id,
        }
        for v, s in sorted(res.values.items())
    }
    return {
        "observado_en": observed_at,
        "mercados_vistos": res.markets_seen,
        "valores": values,
        "sin_valor_null": res.null_count,
        "campo_ausente": res.missing_field_count,
        "tipos_no_string": _jl(sorted(res.non_string_types)),
        "paginas": dict(res.pages),
        "barrido_incompleto": _jl(res.truncated),
        "valores_sin_mapear_a_estado": _jl(
            sorted(v for v in res.values if v.lower() not in SUGGESTIONS)
        ),
    }


def _load(path: Path) -> Mapping[str, JsonValue] | None:
    if not path.exists():
        return None
    data: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None, http: HttpClient | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--find-examples", action="store_true")
    ap.add_argument("--max-pages", type=int, default=5000)
    ap.add_argument("--fixture", type=Path, default=Path("tests/fixtures/uma_status_values.json"))
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = ap.parse_args(argv)

    now = datetime.now(UTC)
    observed_at = _iso(now)
    client = http or RetryingHttpClient(UrllibTransport())
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    partial = args.reports_dir / "v2_partial.json"

    def progress(name: str, pages: int, res: SweepResult) -> None:
        if pages % PROGRESS_EVERY == 0:
            sys.stderr.write(
                f"[{name}] página {pages}: {res.markets_seen} mercados, "
                f"valores {sorted(res.values)}\n"
            )
        if pages % CHECKPOINT_EVERY == 0:  # estado parcial, solo informativo (no es el fixture)
            partial.write_text(
                json.dumps(build_report(res, observed_at), indent=2, ensure_ascii=False) + "\n",
                "utf-8",
            )

    try:
        res = sweep(client, now, max_pages=args.max_pages, on_page=progress)
        if args.find_examples:
            find_examples(client, res)
    except (SweepAborted, SchemaDrift) as exc:
        sys.stderr.write(f"V2 abortado: {exc}\n")
        return 2

    args.fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture = merge_fixture(_load(args.fixture), res, observed_at)
    args.fixture.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", "utf-8")
    report = build_report(res, observed_at)
    (args.reports_dir / f"v2_sweep_{now:%Y%m%d}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    (args.reports_dir / "uma_status_map.proposed.toml").write_text(propose_map(res), "utf-8")

    sys.stdout.write(
        f"{res.markets_seen} mercados; valores: {sorted(res.values)}; "
        f"null: {res.null_count}; incompleto: {res.truncated or 'no'}\n"
    )
    return 3 if res.truncated else 0


if __name__ == "__main__":
    raise SystemExit(main())

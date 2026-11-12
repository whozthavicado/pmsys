"""V2 (B6): barrido del dominio de ``umaResolutionStatus`` en Gamma. Solo lectura (GET).

Uso, desde un entorno con acceso a gamma-api.polymarket.com (p. ej. el VPS):

    uv run python scripts/v2_sweep.py --find-examples
    uv run python scripts/v2_sweep.py --find-examples --resume   # tras una caída

Hace el barrido de la spec (V2, «Método»): ``/markets/keyset`` con ``closed=false`` y con
``closed=true`` (resueltos en los últimos 365 días), cuenta cada valor distinto y, con
``--find-examples``, busca ejemplos de cada valor con el filtro ``uma_resolution_status`` de
``/markets``. Escribe:

- ``tests/fixtures/uma_status_values.json``  ``{valor: {count, market_id_ejemplo, observado_en}}``
- ``tests/fixtures/uma_status_crosstab.json``  cruce (abierto/cerrado) por (valor, null, ausente)
- ``reports/v2_state.json``                   estado reanudable (cursor y contadores)
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
import os
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from pmsys.core.errors import RateLimited, SchemaDrift, UpstreamError, UpstreamTimeout
from pmsys.core.jsontypes import JsonValue
from pmsys.infra.http import HttpClient, RetryingHttpClient, UrllibTransport

GAMMA = "https://gamma-api.polymarket.com"
STATUS_FIELD = "umaResolutionStatus"
PROGRESS_EVERY = 10
# El estado reanudable se guarda cada tantas páginas; al reanudar se rehacen a lo sumo estas.
CHECKPOINT_EVERY = 10
# Tope de páginas POR PASADA (no total). La pasada de cerrados superó las 2.350 páginas en la
# primera corrida; 20.000 deja holgura y un barrido que lo alcance se marca incompleto.
DEFAULT_MAX_PAGES = 20_000
# Tras agotar los reintentos del cliente, el barrido espera y vuelve a intentar la MISMA página
# durante este tiempo antes de rendirse (con el estado ya guardado).
DEFAULT_PATIENCE_MIN = 30
PATIENCE_STEP_S = 60.0
STATE_VERSION = 1
OBSERVED_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
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
class Cross:
    """Cruce (abierto/cerrado) por (valor, null, campo ausente): el fixture lo lleva completo."""

    values: dict[str, int] = field(default_factory=dict)
    null: int = 0
    absent: int = 0


@dataclass
class SweepResult:
    values: dict[str, ValueStat] = field(default_factory=dict)
    cross: dict[str, Cross] = field(default_factory=lambda: {"open": Cross(), "closed": Cross()})
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


def parse_observed(text: str) -> datetime:
    """Inversa de ``_iso``; lanza ``ValueError`` si el texto no tiene ese formato."""
    return datetime.strptime(text, OBSERVED_FORMAT).replace(tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(OBSERVED_FORMAT)


def _record(res: SweepResult, market: Mapping[str, JsonValue], *, closed: bool) -> None:
    res.markets_seen += 1
    cross = res.cross["closed" if closed else "open"]
    if STATUS_FIELD not in market:
        res.missing_field_count += 1
        cross.absent += 1
        return
    raw = market[STATUS_FIELD]
    if raw is None:
        res.null_count += 1
        cross.null += 1
        return
    if not isinstance(raw, str):
        res.non_string_types.add(type(raw).__name__)
    key = raw if isinstance(raw, str) else json.dumps(raw)
    stat = res.values.setdefault(key, ValueStat())
    cross.values[key] = cross.values.get(key, 0) + 1
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


@dataclass
class Cursor:
    """Dónde va el barrido: la pasada en curso y el ``after_cursor`` de la PRÓXIMA página."""

    phase: str = "open"
    after: str | None = None
    pages_in_pass: int = 0
    seen: set[str] = field(default_factory=set)
    done: list[str] = field(default_factory=list)


def _passes(now: datetime, closed_days: int) -> dict[str, dict[str, str]]:
    return {
        "open": {"closed": "false"},
        "closed": {
            "closed": "true",
            "end_date_min": _iso(now - timedelta(days=closed_days)),
            "end_date_max": _iso(now),
        },
    }


def _is_transient(exc: Exception) -> bool:
    """Un 4xx (salvo 429) es permanente: esperar no lo arregla, así que se propaga al instante."""
    if isinstance(exc, UpstreamError):
        return exc.status == 0 or exc.status >= 500
    return True  # RateLimited y UpstreamTimeout


def _get_page_patiently(
    http: HttpClient,
    params: Mapping[str, str],
    *,
    patience_s: float,
    sleep: Callable[[float], None],
) -> JsonValue:
    """Pide la página; si el cliente agota sus reintentos, espera y la vuelve a pedir un rato."""
    waited = 0.0
    while True:
        try:
            return http.get_json(f"{GAMMA}/markets/keyset", params)
        except (UpstreamError, UpstreamTimeout, RateLimited) as exc:
            if not _is_transient(exc) or waited >= patience_s:
                raise
            sys.stderr.write(
                f"Gamma no responde; espero {PATIENCE_STEP_S:.0f} s y reintento esta página…\n"
            )
            sleep(PATIENCE_STEP_S)
            waited += PATIENCE_STEP_S


def sweep(
    http: HttpClient,
    now: datetime,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    closed_days: int = 365,
    on_page: PageHook | None = None,
    state: tuple[SweepResult, Cursor] | None = None,
    on_checkpoint: Callable[[SweepResult, Cursor], None] | None = None,
    patience_s: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> SweepResult:
    """Barrido completo: abiertos (sin fecha) y cerrados de los últimos ``closed_days`` días.

    Con ``state`` (resultado y cursor guardados) retoma donde se quedó: salta las pasadas ya
    terminadas y sigue desde el ``after_cursor`` guardado, sin recontar lo ya contado.
    """
    res, cur = state if state is not None else (SweepResult(), Cursor())
    for name, base in _passes(now, closed_days).items():
        if name in cur.done:
            continue
        if cur.phase != name:
            cur.phase, cur.after, cur.pages_in_pass, cur.seen = name, None, 0, set()
        while True:
            params = {**base, "limit": str(PAGE_LIMIT)}
            if cur.after:
                params["after_cursor"] = cur.after
            body = _get_page_patiently(http, params, patience_s=patience_s, sleep=sleep)
            cur.pages_in_pass += 1
            res.pages[name] = cur.pages_in_pass
            for market in extract_markets(body):
                _record(res, market, closed=name == "closed")
            if on_page is not None:
                on_page(name, cur.pages_in_pass, res)
            nxt = next_cursor(body)
            if nxt is None:
                cur.done.append(name)
                if on_checkpoint is not None:
                    on_checkpoint(res, cur)
                break
            if nxt in cur.seen:
                raise SweepAborted(f"{name}: el cursor se repite; paginación en bucle")
            cur.seen.add(nxt)
            cur.after = (
                nxt  # estado consistente: contadores hasta esta página + cursor de la siguiente
            )
            if on_checkpoint is not None and cur.pages_in_pass % CHECKPOINT_EVERY == 0:
                on_checkpoint(res, cur)
            if cur.pages_in_pass >= max_pages:
                res.truncated.append(name)  # barrido incompleto: no sirve para cerrar V2
                cur.done.append(name)
                break
    return res


# ── Estado reanudable ────────────────────────────────────────────────────


class _ValueModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int
    open: int
    closed: int
    ex: str | None
    ex_open: str | None
    ex_closed: str | None


class _CrossModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, int]
    null: int
    absent: int


class _StateModel(BaseModel):
    """Formato en disco del estado reanudable; ``extra="forbid"`` detecta un fichero ajeno."""

    model_config = ConfigDict(extra="forbid")
    version: int
    observado_en: str
    closed_days: int
    phase: str
    after: str | None
    pages_in_pass: int
    seen: list[str]
    done: list[str]
    values: dict[str, _ValueModel]
    cross: dict[str, _CrossModel]
    null: int
    absent: int
    non_string: list[str]
    seen_markets: int
    pages: dict[str, int]
    truncated: list[str]


def state_to_json(res: SweepResult, cur: Cursor, observed_at: str, closed_days: int) -> str:
    model = _StateModel(
        version=STATE_VERSION,
        observado_en=observed_at,
        closed_days=closed_days,
        phase=cur.phase,
        after=cur.after,
        pages_in_pass=cur.pages_in_pass,
        seen=sorted(cur.seen),
        done=list(cur.done),
        values={
            v: _ValueModel(
                count=s.count,
                open=s.open_count,
                closed=s.closed_count,
                ex=s.example_id,
                ex_open=s.example_open_id,
                ex_closed=s.example_closed_id,
            )
            for v, s in res.values.items()
        },
        cross={
            k: _CrossModel(values=dict(c.values), null=c.null, absent=c.absent)
            for k, c in res.cross.items()
        },
        null=res.null_count,
        absent=res.missing_field_count,
        non_string=sorted(res.non_string_types),
        seen_markets=res.markets_seen,
        pages=dict(res.pages),
        truncated=list(res.truncated),
    )
    return model.model_dump_json() + "\n"


def state_from_json(text: str) -> tuple[SweepResult, Cursor, str, int]:
    try:
        m = _StateModel.model_validate_json(text)
    except ValidationError as exc:
        raise SweepAborted(
            f"estado guardado ilegible ({exc.error_count()} errores); bórralo y empieza de cero"
        ) from exc
    if m.version != STATE_VERSION:
        raise SweepAborted(
            "el estado guardado es de otra versión del script; bórralo y empieza de cero"
        )
    try:
        parse_observed(m.observado_en)
    except ValueError as exc:
        raise SweepAborted(f"estado guardado con fecha ilegible ({m.observado_en!r})") from exc
    cur = Cursor(
        phase=m.phase,
        after=m.after,
        pages_in_pass=m.pages_in_pass,
        seen=set(m.seen),
        done=list(m.done),
    )
    res = SweepResult()
    for v, s in m.values.items():
        res.values[v] = ValueStat(
            count=s.count,
            open_count=s.open,
            closed_count=s.closed,
            example_id=s.ex,
            example_open_id=s.ex_open,
            example_closed_id=s.ex_closed,
        )
    for k, c in m.cross.items():
        res.cross[k] = Cross(values=dict(c.values), null=c.null, absent=c.absent)
    res.null_count = m.null
    res.missing_field_count = m.absent
    res.non_string_types = set(m.non_string)
    res.markets_seen = m.seen_markets
    res.pages = dict(m.pages)
    res.truncated = list(m.truncated)
    return res, cur, m.observado_en, m.closed_days


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


def crosstab_fixture(res: SweepResult, observed_at: str) -> dict[str, JsonValue]:
    """Cruce completo (abierto/cerrado) por (valor, null, campo ausente).

    La ausencia del campo es un estado propio: un cerrado sin campo es un resuelto sin estado, no
    un abierto sin propuesta, y F8 tiene que poder distinguirlos. ``completo`` es false si el
    barrido alcanzó el tope de páginas (entonces no sirve para cerrar V2).
    """

    def side(c: Cross) -> dict[str, JsonValue]:
        return {
            "valores": dict(sorted(c.values.items())),
            "null": c.null,
            "campo_ausente": c.absent,
        }

    return {
        "observado_en": observed_at,
        "completo": not res.truncated,
        "paginas": dict(res.pages),
        "mercados_vistos": res.markets_seen,
        "abiertos": side(res.cross["open"]),
        "cerrados": side(res.cross["closed"]),
    }


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


def write_atomic(path: Path, text: str) -> None:
    """Escribe a un temporal y lo mueve con ``os.replace``: nunca queda un fichero a medias."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, path)


def _load(path: Path) -> Mapping[str, JsonValue] | None:
    if not path.exists():
        return None
    data: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None, http: HttpClient | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--find-examples", action="store_true")
    ap.add_argument(
        "--max-pages", type=int, default=DEFAULT_MAX_PAGES, help="tope de páginas POR PASADA"
    )
    ap.add_argument("--resume", action="store_true", help="retoma desde reports/v2_state.json")
    ap.add_argument("--patience-min", type=float, default=DEFAULT_PATIENCE_MIN)
    ap.add_argument("--fixture", type=Path, default=Path("tests/fixtures/uma_status_values.json"))
    ap.add_argument(
        "--crosstab", type=Path, default=Path("tests/fixtures/uma_status_crosstab.json")
    )
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = ap.parse_args(argv)

    args.reports_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.reports_dir / "v2_state.json"
    partial = args.reports_dir / "v2_partial.json"
    client = http or RetryingHttpClient(UrllibTransport())

    state: tuple[SweepResult, Cursor] | None = None
    closed_days = 365
    if state_path.exists():
        if not args.resume:
            sys.stderr.write(
                f"Hay un estado guardado en {state_path}. "
                "Usa --resume o bórralo para empezar de cero.\n"
            )
            return 2
        try:
            loaded = state_from_json(state_path.read_text("utf-8"))
        except SweepAborted as exc:
            sys.stderr.write(f"No se puede reanudar: {exc}\n")
            return 2
        res0, cur0, observed_at, closed_days = loaded
        state = (res0, cur0)
        # La ventana de fechas de la pasada de cerrados debe ser la de la corrida original.
        now = parse_observed(observed_at)
        sys.stderr.write(
            f"Reanudando: pasada «{cur0.phase}», página {cur0.pages_in_pass}, "
            f"{res0.markets_seen} mercados.\n"
        )
    else:
        if args.resume:
            sys.stderr.write("No hay estado guardado; empiezo de cero.\n")
        now = datetime.now(UTC)
        observed_at = _iso(now)

    def progress(name: str, pages: int, res: SweepResult) -> None:
        if pages % PROGRESS_EVERY == 0:
            sys.stderr.write(
                f"[{name}] página {pages}: {res.markets_seen} mercados, "
                f"valores {sorted(res.values)}\n"
            )

    def checkpoint(res: SweepResult, cur: Cursor) -> None:
        write_atomic(state_path, state_to_json(res, cur, observed_at, closed_days))
        write_atomic(
            partial, json.dumps(build_report(res, observed_at), indent=2, ensure_ascii=False) + "\n"
        )

    try:
        res = sweep(
            client,
            now,
            max_pages=args.max_pages,
            closed_days=closed_days,
            on_page=progress,
            state=state,
            on_checkpoint=checkpoint,
            patience_s=args.patience_min * 60,
        )
    except (SweepAborted, SchemaDrift) as exc:
        sys.stderr.write(f"V2 abortado: {exc}\n")
        return 2
    except (UpstreamError, UpstreamTimeout, RateLimited) as exc:
        sys.stderr.write(
            f"V2 interrumpido: {exc}. El estado quedó guardado: relanza con --resume.\n"
        )
        return 4

    # Los fixtures y el cruce no dependen de los ejemplos: se escriben ANTES de ``find_examples``,
    # para que un fallo de red ahí no tire horas de barrido.
    args.fixture.parent.mkdir(parents=True, exist_ok=True)
    args.crosstab.parent.mkdir(parents=True, exist_ok=True)
    fixture = merge_fixture(_load(args.fixture), res, observed_at)
    write_atomic(args.fixture, json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
    write_atomic(
        args.crosstab,
        json.dumps(crosstab_fixture(res, observed_at), indent=2, ensure_ascii=False) + "\n",
    )
    if args.find_examples:
        try:
            find_examples(client, res)
        except (SweepAborted, SchemaDrift, UpstreamError, UpstreamTimeout, RateLimited) as exc:
            sys.stderr.write(
                f"No se pudieron buscar ejemplos abiertos ({exc}); el informe va sin ellos.\n"
            )
    report = build_report(res, observed_at)
    write_atomic(
        args.reports_dir / f"v2_sweep_{now:%Y%m%d}.json",
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
    )
    write_atomic(args.reports_dir / "uma_status_map.proposed.toml", propose_map(res))
    if not res.truncated:
        state_path.unlink(missing_ok=True)  # corrida terminada: no bloquea la siguiente

    sys.stdout.write(
        f"{res.markets_seen} mercados; valores: {sorted(res.values)}; "
        f"null: {res.null_count}; incompleto: {res.truncated or 'no'}\n"
    )
    return 3 if res.truncated else 0


if __name__ == "__main__":
    raise SystemExit(main())

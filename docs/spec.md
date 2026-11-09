# Spec Fase 1 — Sistema de picks en mercados de predicción

Nov 4, 2026 · Bernumeno

**Versión 1.4.1.** Cierra las 4 comprobaciones y los ajustes de la revisión de la 1.3.0, y adopta el plan de muestra y tope (75 forecasts/mes, cap\_mensual = 30 USD). La 1.3.0 cerró C1–C11. La 1.2.0 cerró B1–B6 y 1.2/M1–M9 de la 1.1.0. La 1.1.0 cerró D1–D6 y M1–M6 de la 1.0.0. El prefijo "1.2/" evita confundir estas correcciones con las métricas M1–M10. El detalle está en el changelog al final.

## 0. Decisiones de Fase 0 y supuestos

Decisiones de diseño resueltas y aprobadas por ti: T1 = C, T2 = C, T3 = B (detalle en la sección 1). No queda ninguna decisión de diseño abierta. Las dependencias abiertas son los bloqueantes V1 y V2 de Fase 2.

| Parámetro | Papel | Vivo |
| --- | --- | --- |
| Bankroll | 50 USDC nocional | 50 USDC objetivo; arranque según T2 = C: 6a con 5 USDC y después 6b |
| Stop de sistema | Sin stop: el papel nunca se detiene (1.2/M4); el drawdown solo se registra para P5 (B2) | 15% desde pico, stop definitivo, revisión manual |
| Categorías | a geopolítica, b política EE. UU., c política no EE. UU., d macro; desde el mes 4, solo las 2 activas (1.4.0) | Top 1–2 tras papel (T3) |
| Horizonte | 2–90 días a resolución | 2–45 días |
| Ejecución | Ledger simulado | Picks con ejecución manual, sin CLOB autenticado |
| Stack | Python 3.12, pydantic v2, SQLite WAL, VPS Linux, ciclo 12 h | Igual |
| LLM | Haiku triaje, Sonnet análisis, Opus solo tras pre-filtro | Igual |
| Ventana | 6 meses + 1 extensión de 3 | — |
| Presupuesto | LLM ≤ 30 (cap\_mensual, 1.4.0), datos 0, hosting ≤ 10 USD/mes | Igual |

**Jurisdicción: \[RELLENAR\] → supuesto México.** VERIFICADO: MX no aparece como Blocked ni Close-only en la tabla de restricciones de Polymarket (consulta 2026-11-04, [geoblock](https://docs.polymarket.com/api-reference/geoblock.md)). Venue asumido: Polymarket internacional. Polymarket US queda fuera de alcance.

Regla dura: antes de emitir un pick en vivo, el sistema consulta `GET https://polymarket.com/api/geoblock`. Si `blocked=true` o `country` no coincide con la jurisdicción configurada, la salida es "no operar". El sistema no soporta operar desde una IP de otro país.

Mapeo de categorías a taxonomía de Polymarket (INFERIDO, verificar tag IDs en Fase 2): a → Geopolitics; b, c → Politics; d → Economics y Finance. El mapeo importa porque las comisiones difieren por categoría (sección 1, T4).

**Dependencia abierta (B4).** La gestión de capital supone que el tamaño mínimo de orden se mide en acciones. Esto se verifica como primer bloqueante de Fase 2 (V1). Si resulta en USDC, se aplica la contingencia de T2 y la decisión de B\_live vuelve a ti.

## 1. Defectos en las definiciones de partida y trade-offs

Dos definiciones del brief, tal como están, hacen el sistema inevaluable o inoperable. T1, T2 y T3 están aprobadas (C, C y B); T4–T6 son decisiones técnicas con recomendación.

### T1. Benchmark de "éxito del sistema" (aprobada: C)

INFERIDO: el precio de cierre incorpora toda la información posterior al momento del pronóstico. En mercados cuyo desenlace se conoce antes del cierre, su Brier tiende a 0. Comparar un pronóstico emitido días antes contra ese precio no mide ventaja; mide quién tuvo más información.

| Opción | Mide ventaja | Alcanzable | Recomendación |
| --- | --- | --- | --- |
| A. Brier vs precio de cierre (brief literal) | No | Casi nunca | Rechazar como criterio primario |
| B. Brier vs mid del mercado en t0 (instante en que se congela p\_final) | Sí: mismo conjunto de información | Sí | **Primario** |
| C. B primario + A como métrica informativa | Sí | Sí | **Adoptar C** |

### T2. Arranque en vivo con 5 USDC frente al tamaño mínimo de orden (aprobada: C)

VERIFICADO: el endpoint CLOB `/clob-markets/{condition_id}` expone `mos` ("Minimum order size", ejemplo 5) y el ejemplo de la API usa 5. SIN VERIFICAR: que la unidad sea acciones. Esta tabla asume acciones. Coste mínimo de entrada = 5 × precio del lado comprado.

Condición para que Kelly 1/4 alcance el mínimo, con B = bankroll, q = precio del lado y π = probabilidad del lado:

```latex
0.25 \cdot B \cdot \frac{\pi - q}{1 - q} \ge 5q \iff \pi - q \ge \frac{20\,q\,(1-q)}{B}
```

| q (precio del lado) | Edge mínimo con B = 5 | Edge mínimo con B = 50 |
| --- | --- | --- |
| 0.10 / 0.90 | 0.36 | 0.036 |
| 0.20 / 0.80 | 0.64 | 0.064 |
| 0.30 / 0.70 | 0.84 | 0.084 |
| 0.50 | 1.00 | 0.100 |

Con 5 USDC, Kelly 1/4 nunca alcanza el mínimo. Forzar la orden mínima equivale a apostar hasta 20× Kelly 1/4.

| Opción | Consecuencia | Recomendación |
| --- | --- | --- |
| A. 5 USDC + Kelly 1/4 estricto | 0 operaciones; no valida nada | Rechazar |
| B. 5 USDC forzando tamaño mínimo | Sizing roto; hasta 50% del bankroll en una posición | Rechazar |
| C. **6a**: 5 USDC, como máximo 2 órdenes de tamaño mínimo. Solo valida ejecución, slippage y comisión real; sin evaluar P&L. **6b**: 50 USDC con Kelly 1/4. Si stake\_kelly < mínimo, la salida es "no operar por tamaño" y el pick sigue registrándose en papel | Conserva el sizing; valida el flujo con riesgo de 5 USDC | **Adoptar C** |

**Contingencia de unidad (B4).** Todo lo anterior supone `min_order_unit = "shares"`. La unidad se verifica en V1, el primer bloqueante de Fase 2. El sizing usa `min_cost(c) = mos × c` si la unidad es acciones, o `min_cost(c) = mos` si es USDC. Si V1 resuelve USDC, se aplica este procedimiento antes de continuar la Fase 2:

1. Fijar `min_order_unit = "usdc"` en `settings.toml`; cambia `rules_version`.
2. Rehacer la tabla de este apartado con la condición `π − c ≥ 4·mos·(1 − c) / B`. Con mos = 5 y B = 50: c = 0.10 → 0.36; 0.30 → 0.28; 0.50 → 0.20; 0.70 → 0.12; 0.80 → 0.08; 0.90 → 0.04.
3. Recalcular los Ejemplos 1 y 2 de (h) y el pre-filtro a Opus (Presupuesto LLM), que ya usan `min_cost(c)`.
4. Detener la Fase 2 y pedirte una decisión de capital.

| Opción (solo si la unidad es USDC) | Edge mínimo a c = 0.50 | Consecuencia |
| --- | --- | --- |
| B\_live = 200 USDC con Kelly 1/4 | 0.05 | Multiplica por 4 el capital comprometido |
| B\_live = 100 USDC con Kelly 1/2 | 0.05 | Duplica el capital y la varianza por apuesta |
| Mantener B = 50 | 0.20 | Picks casi solo sobre favoritos; P4 inalcanzable en la práctica |

El B nocional del papel se iguala al B\_live elegido, para que los picks de papel representen lo que se operaría. Si no hay decisión, por defecto el papel sigue con B = 50, M1 y M1b continúan (no dependen del sizing) y la promoción queda congelada.

### T3. "Al menos una categoría, sobre ≥ 200 mercados" (aprobada: B)

Es ambiguo: 200 por categoría o 200 en total. 200 por categoría son 800 mercados resueltos en 9 meses, fuera de alcance con este presupuesto.

INFERIDO (simulación propia, 1,500 réplicas): con un modelo que capta el 30–50% del error oculto del mercado, ΔBrier ≈ −0.006 a −0.009. Con test unilateral al 5%, la potencia es 0.67–0.75 con n = 200 y 0.31–0.34 con n = 50. Si el modelo añade ruido propio, la potencia con n = 200 baja a \~0.27–0.41.

| Opción | Potencia | Recomendación |
| --- | --- | --- |
| A. 200 por categoría | Alta, pero inalcanzable | Rechazar |
| B. Test sobre 200 en total; la categoría se elige por estimación contraída + CLV, etiquetada INFERIDO | Suficiente agregada; débil por categoría | **Adoptar B** |

**Concentración de la muestra desde el mes 4 (1.4.0).** Es una regla precomprometida:

1. El día 1 del mes 4 a 00:00 UTC se ordenan las 4 categorías por M1 contraído (el mismo Bayes empírico de T3), con los forecasts resueltos hasta ese corte. Gana el menor; en empate, la de más resueltos.
2. Las 2 primeras pasan a ser las categorías activas. E1 de la selección (D3) solo admite esas 2, y la cuota mínima sube de 10 a 25 por categoría.
3. Las otras 2 se siguen ingiriendo, pero dejan de recibir forecasts. La selección de categorías para vivo (T3) y su revisión (1.2/M8) se hacen solo entre las 2 activas.

INFERIDO: al corte del mes 3 cada categoría tiene \~25–35 resueltos, así que el ranking es ruidoso. Se acepta por diseño a cambio de duplicar la densidad por categoría cuando el gate de T3 ya tiene datos.

**Revisión de categorías (1.2/M8).** La selección de categorías para vivo es provisional. A los 3 meses de iniciar 6b (pleno o 6b-C) se recalcula M1 por categoría con todos los forecasts resueltos hasta ese corte y se repite la selección con la misma regla de (f). Motivo, INFERIDO: con n = 40 por categoría la potencia es ≈ 0.25, así que la primera elección tiene alta probabilidad de ser ruido. Una categoría que sale de la selección cierra sus posiciones solo por vencimiento, sin ventas anticipadas.

### T4. Edge neto de costes

VERIFICADO ([fees](https://docs.polymarket.com/trading/fees.md)): solo pagan los takers, con `fee = C × feeRate × p × (1 − p)`. feeRate: Geopolitics 0, Politics 0.04, Economics 0.05, Finance 0.04.

SIN VERIFICAR: `/clob-markets` expone también un exponente de curva (`fd.e`) que la fórmula publicada no incluye. Decisión: calcular ambas variantes y usar la mayor (conservadora) hasta medir la comisión real en 6a.

El edge que entra en los filtros es siempre neto: VWAP del lado para el tamaño + comisión por acción. Ejemplo en Politics a 0.50: comisión = 0.04 × 0.25 = 0.01 por acción, es decir, 2% del nocional.

### T5. Hosting

CX22 está descontinuado. Según fuentes secundarias, CX23 cuesta 5.49 EUR/mes tras el ajuste del 2026-06-15 y aparece como no disponible para pedido (SIN VERIFICAR en hetzner.com).

| Opción | Coste | Recomendación |
| --- | --- | --- |
| CX23 si se puede pedir | \~5.49 EUR | Preferente |
| CAX11 (ARM) | \~5.99 EUR | Alternativa; todas las dependencias son Python puro o con wheels ARM |
| Otro VPS 2 vCPU / 4 GB | ≤ 10 USD | Aceptable; la spec no depende del proveedor |

### T6. Recuperación de texto de evidencia

GDELT devuelve metadatos y URL, no texto completo.

| Opción | Coste | Fiabilidad | Recomendación |
| --- | --- | --- | --- |
| GDELT + RSS oficiales + descarga directa de la URL | 0 | Media: muros de pago y HTML cambiante | **Primario** |
| Herramienta de búsqueda web de la API de Anthropic | Por búsqueda (precio SIN VERIFICAR); consume presupuesto LLM | Alta | Desactivada por defecto; flag `evidence.web_search=false` |

### T7. Categoría 'other' (D6)

| Opción | Consecuencia | Recomendación |
| --- | --- | --- |
| A. Excluir 'other' en la selección (E1) y conservarlo en `markets` para no perder datos de ingesta, con aserción en `analyze()` y trigger en `forecasts` | Ingesta completa; análisis solo a–d; una violación se detecta en dos capas | **Adoptar** (implementado en (b), "Invariante de categoría", y en la migración 0002) |
| B. Añadir 'other' al enum del schema y analizarlo | Amplía el alcance decidido en Fase 0; tasas base y tabla de sesgo sin categoría definida | Rechazar |

## (a) Árbol de directorios

Es un paquete con 11 submódulos y dependencias en un solo sentido: `core` ← `infra` ← `ingest`/`evidence` ← `analysis` ← `synthesis` ← `decision` ← `ledger` ← `eval` ← `pipeline`. Ningún módulo importa de una capa superior; un test de import lo comprueba.

```text
pmsys/
├── pyproject.toml            # py3.12, mypy --strict, ruff, pytest, hypothesis
├── .env.example              # ANTHROPIC_API_KEY, FRED_API_KEY, COURTLISTENER_TOKEN
├── config/
│   ├── settings.toml         # umbrales, caps, horizontes; su hash = rules_version
│   ├── categories.toml       # categoría a|b|c|d -> tag IDs de Gamma (verificados)
│   ├── sources.toml          # allowlist de feeds RSS oficiales y tier de fiabilidad
│   ├── clusters.toml         # reglas de clúster correlacionado (manuales)
│   ├── event_types.toml      # regex de tipo de evento por prioridad (D2)
│   ├── ref_external.toml     # registro de clases externas; vacío por defecto (D2)
│   ├── resolution_sources.toml  # allowlist monitorizable para F10 (M1)
│   └── uma_status_map.toml   # valor de umaResolutionStatus → estado para F8 (B6)
├── migrations/               # 0001_init.sql, 0002_*.sql ... aplicadas en orden
├── prompts/                  # triage.md, rules.md, outside_view.md, red_team.md, synth.md
│                             # cada prompt versionado por sha256 del contenido
├── src/pmsys/
│   ├── core/
│   │   ├── models.py         # todos los modelos pydantic de contrato (frozen=True)
│   │   ├── errors.py         # jerarquía de errores
│   │   ├── clock.py          # Clock inyectable; todo en UTC tz-aware
│   │   └── ids.py            # claves de idempotencia (sha256)
│   ├── infra/
│   │   ├── http.py           # cliente con backoff+jitter y token bucket por host
│   │   ├── db.py             # conexión SQLite (WAL), migrador, transacciones
│   │   └── llm.py            # cliente Anthropic, enrutado por coste, presupuesto duro
│   ├── ingest/
│   │   ├── gamma.py          # mercados y eventos
│   │   ├── clob.py           # libro, historial de precios, parámetros CLOB
│   │   └── geoblock.py       # estado de jurisdicción
│   ├── normalize/market.py   # RawMarket -> Market
│   ├── rules/parser.py       # criterios de resolución + score de ambigüedad
│   ├── evidence/
│   │   ├── gdelt.py  rss.py  fred.py  courtlistener.py
│   │   ├── fetch.py          # descarga de URL -> texto; contenido tratado como dato
│   │   └── retriever.py      # orquesta búsqueda pro y contra, citas obligatorias
│   ├── analysis/
│   │   ├── base_rates.py     # clases de referencia y tasas base
│   │   ├── market_implied.py # p implícita y sesgo histórico por bucket
│   │   ├── outside_view.py   # agente vista externa
│   │   └── red_team.py       # agente red team
│   ├── synthesis/
│   │   ├── combine.py        # p_model con ajustes en espacio logit
│   │   └── shrink.py         # shrinkage hacia el mercado
│   ├── decision/
│   │   ├── costs.py          # VWAP, comisión, edge neto
│   │   ├── filters.py        # filtros duros F1-F9
│   │   ├── sizing.py         # Kelly fraccional + mínimo de orden
│   │   └── risk.py           # caps por clúster, exposición, stop
│   ├── ledger/
│   │   ├── paper.py          # posiciones simuladas y liquidación
│   │   └── manual.py         # registro de fills manuales en vivo
│   ├── eval/
│   │   ├── scoring.py        # Brier, log loss, ΔBrier pareado, bootstrap
│   │   ├── calibration.py    # buckets, ECE, pendiente/intercepto
│   │   ├── attribution.py    # por categoría, fuente, ajuste
│   │   ├── recalibrate.py    # ajuste de w y Platt con validación temporal
│   │   └── promotion.py      # evalúa P1-P7, emite veredicto
│   ├── pipeline/
│   │   ├── cycle.py          # orquestador de 9 pasos, reanudable
│   │   └── state.py          # checkpoints por paso y mercado
│   └── cli.py                # pmsys run|resume|report|settle|promote-check
├── tests/
│   ├── fixtures/             # respuestas reales grabadas de Gamma/CLOB/GDELT
│   ├── unit/                 # uno por módulo; red bloqueada
│   └── property/             # hypothesis: sizing, costes, scoring
└── reports/                  # salidas generadas (no versionadas)
```

## (b) Contratos de interfaz

Cada módulo expone funciones puras o clases con dependencias inyectadas (`HttpClient`, `Db`, `LlmClient`, `Clock`). Por eso todos se testean con fakes y sin red. Todos los modelos son `pydantic.BaseModel` con `frozen=True` y `extra="forbid"`. Los timestamps son `datetime` UTC tz-aware: un naive lanza `ValidationError`.

### Errores comunes (`core/errors.py`)

```python
class PmsysError(Exception): ...
class RateLimited(PmsysError):        retry_after_s: float | None
class UpstreamError(PmsysError):      host: str; status: int
class UpstreamTimeout(PmsysError):    host: str
class SchemaDrift(PmsysError):        source: str; field: str      # falta un campo esperado o cambió de tipo
class NormalizationError(PmsysError): market_id: str; field: str
class BudgetExceeded(PmsysError):     scope: Literal["day", "month"]; spent_usd: float
class LlmSchemaViolation(PmsysError): task: str; attempts: int     # tras 2 reintentos
class InsufficientEvidence(PmsysError): reason: str                 # termina en "no operar"
class InsufficientReferenceClass(PmsysError): n: int                # n < 20
class IdempotencyConflict(PmsysError): key: str
class SystemStopped(PmsysError):      since: datetime; reason: str   # solo en la ruta de ejecución real (M4)
class CategoryInvariantError(PmsysError): market_id: str            # D6
class SelectionIncomplete(PmsysError): tag_id: int                   # D3
```

Regla: `RateLimited`, `UpstreamError` 5xx y `UpstreamTimeout` se reintentan en `infra.http`. El resto se propaga y el orquestador lo registra como estado del mercado en ese ciclo, nunca como pick.

**Stop y papel (M4).** `SystemStopped` solo lo lanzan `ledger.manual` y la ruta de decisión en modo vivo. El ciclo de papel nunca lo lanza ni lo captura: con el stop activo continúan forecasts, picks de papel, liquidación y scoring. El drawdown del ledger de papel se registra en `system_state.paper_stop`, que solo lee P5.

### infra

```python
class HostPolicy(BaseModel):
    host: str; max_req: int; window_s: float     # token bucket
    max_retries: int = 5; base_delay_s: float = 1.0; max_delay_s: float = 60.0
# backoff: delay = uniform(0, min(max_delay, base * 2**attempt)); respeta Retry-After si existe

class HttpClient(Protocol):
    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonValue: ...
    def post_json(self, url: str, body: JsonValue) -> JsonValue: ...
    # errores: RateLimited (agotados reintentos), UpstreamError, UpstreamTimeout

class Db(Protocol):
    def migrate(self) -> int: ...                     # devuelve versión aplicada
    def tx(self) -> ContextManager[sqlite3.Connection]: ...

class LlmTask(StrEnum): TRIAGE="triage"; RULES="rules"; OUTSIDE="outside"; RED_TEAM="red_team"; SYNTH="synth"
class LlmResult(BaseModel, Generic[T]):
    value: T; model: str; prompt_sha: str; input_tokens: int; output_tokens: int; cost_usd: float
class LlmClient(Protocol):
    def run(self, task: LlmTask, prompt_id: str, inputs: Mapping[str, Any],
            out_schema: type[T], batch: bool = False) -> LlmResult[T]: ...
    # enrutado fijo: TRIAGE, RULES -> Haiku; OUTSIDE -> Sonnet; RED_TEAM, SYNTH -> Opus solo si pasa pre-filtro, si no Sonnet
    # errores: BudgetExceeded (antes de llamar, con coste estimado), LlmSchemaViolation, UpstreamError
```

### ingest y normalize

```python
def fetch_markets(http: HttpClient, *, active: bool, closed: bool, limit: int, offset: int) -> list[RawMarket]
def fetch_market(http: HttpClient, market_id: str) -> RawMarket
def get_book(http: HttpClient, token_id: str) -> OrderBook                    # bids/asks [(price, size)], ts
def get_price_history(http: HttpClient, token_id: str, start: datetime, end: datetime,
                      fidelity_min: int) -> list[PricePoint]                 # {t, p}
def get_clob_params(http: HttpClient, condition_id: str) -> ClobParams       # mos, mts, fee_rate, fee_exp, taker_only
def check_geoblock(http: HttpClient) -> GeoStatus                            # blocked, country, region
def normalize(raw: RawMarket, now: datetime) -> Market
# Market: market_id, condition_id, event_id, question, rules_text, category (a|b|c|d|other),
#   end_date_utc, yes_token, no_token, neg_risk, active, closed, uma_status, outcome (YES|NO|VOID|None)
# errores: SchemaDrift si falta un campo requerido; NormalizationError si un valor no parsea
```

RawMarket guarda el JSON crudo completo. Los campos usados (`conditionId`, `endDate`, `closed`, `umaResolutionStatus`, `orderMinSize`, `orderPriceMinTickSize`, `resolutionSource`) aparecen en el esquema de la referencia de Gamma. Sus dominios de valores están SIN VERIFICAR hasta grabar fixtures reales en Fase 2.

### rules

```python
class ResolutionSpec(BaseModel):
    deadline_utc: datetime | None          # None => ambigüedad +2
    deadline_tz_explicit: bool
    resolution_sources: list[str]          # nombradas en el texto
    yes_conditions: list[str]; no_conditions: list[str]; void_conditions: list[str]
    ambiguity_score: int                   # 0-10
    ambiguity_reasons: list[AmbiguityReason]
    rules_sha: str                         # sha256 del texto normalizado
def parse_rules(market: Market, llm: LlmClient) -> ResolutionSpec
```

Score de ambigüedad: primero una rúbrica determinista, después Haiku; el score final es el máximo de los dos (conservador). Se guardan ambos.

| Motivo | Puntos |
| --- | --- |
| Fecha límite sin hora o sin zona horaria explícita | +1 |
| Términos subjetivos ("significant", "credible reporting", "major") | +2 |
| Fuente de resolución no nombrada, o varias sin precedencia | +2 |
| Sin regla para aplazamiento, cancelación o empate | +1 |
| Depende de "consenso de reportes" | +1 |
| Condición compuesta (AND/OR anidados) | +1 |
| Evento ya en curso con resultado parcial ambiguo | +1 |

Máximo 10. Los casos límite que se testean en Fase 2: deadline a 23:59 ET frente a UTC, DST, fecha "by" frente a "on", condición de anulación (50-50), y mercados neg\_risk de un mismo evento.

### analysis

```python
class BaseRate(BaseModel):
    ref_class: str; class_sha: str; level: int; k: int; n: int; rate: float; ci95: tuple[float, float]   # Wilson
    source: Literal["polymarket_resolved", "external"]; citation_ids: list[str]
def base_rate(frozen: FrozenRefClass, db: Db) -> BaseRate          # error: InsufficientReferenceClass si n < 20

class MarketImplied(BaseModel):
    t0: datetime; best_bid: float; best_ask: float; mid: float; spread: float
    depth_usd_2ticks: float; vol_24h_usd: float; drift_7d: float
    p_implied: float                 # mid
    p_implied_debiased: float        # mid corregido por la calibración histórica del bucket
    discount_notes: list[str]        # qué está descontando el precio (R8)
def market_implied(book: OrderBook, history: list[PricePoint], calib: BucketCalibration) -> MarketImplied

def outside_view(market: Market, spec: ResolutionSpec, br: BaseRate, llm: LlmClient) -> OutsideView
def red_team(market: Market, draft: DraftEstimate, ev: list[EvidenceItem], llm: LlmClient) -> RedTeam
# RedTeam: case_market_right, case_market_wrong, falsifiers: list[{observable, by_date, direction, delta_logit}]
```

INFERIDO: la fuente de ventaja más defendible no es el LLM. Es medir el sesgo del propio precio de Polymarket por bucket, categoría y horizonte (por ejemplo, favorito–longshot) con los mercados resueltos acumulados en la base. `p_implied_debiased` arranca igual a `mid` hasta tener n ≥ 30 por bucket.

### Clase de referencia (D2)

Una clase de referencia es un conjunto congelado de mercados de Polymarket ya resueltos que comparten con el mercado objetivo hasta 4 dimensiones. Se construye una vez por (market\_id, rules\_sha, rules\_version) y todas las revisiones del mercado la reutilizan.

```python
class EventType(StrEnum):
    ELECTION_WINNER    = "election_winner"     # X gana la elección o nominación Y
    ELECTION_THRESHOLD = "election_threshold"  # % de voto, escaños o participación frente a N
    LEGISLATION        = "legislation"         # ley o proyecto aprobado, firmado o vetado
    OFFICE_CHANGE      = "office_change"       # nombramiento, renuncia, destitución
    COURT              = "court"               # fallo, imputación, sentencia
    MILITARY           = "military"            # ataque, invasión, alto el fuego, despliegue
    DIPLOMACY          = "diplomacy"           # acuerdo, tratado, reunión, sanción
    MACRO_RELEASE      = "macro_release"       # dato publicado frente a umbral (CPI, empleo, PIB)
    CENTRAL_BANK       = "central_bank"        # decisión de tipos
    OTHER_DEADLINE     = "other_deadline"      # "¿ocurre X antes de D?" sin tipo anterior

class EventFamily(StrEnum):
    ELECTORAL = "electoral"; POLICY = "policy"; CONFLICT = "conflict"; MACRO = "macro"; OTHER = "other"

FAMILY: Final[Mapping[EventType, EventFamily]] = {
    ELECTION_WINNER: ELECTORAL, ELECTION_THRESHOLD: ELECTORAL,
    LEGISLATION: POLICY, OFFICE_CHANGE: POLICY, COURT: POLICY,
    MILITARY: CONFLICT, DIPLOMACY: CONFLICT,
    MACRO_RELEASE: MACRO, CENTRAL_BANK: MACRO, OTHER_DEADLINE: OTHER,
}

class HorizonBucket(StrEnum):
    H1 = "2-14"; H2 = "15-45"; H3 = "46-90"            # días a end_date en t
HORIZON_LO_DAYS: Final = {H1: 2, H2: 15, H3: 46}

class EventLabel(BaseModel):                          # frozen, extra="forbid"
    event_type: EventType; event_family: EventFamily; yes_is_change: bool
    method: Literal["rule", "llm"]; rule_id: str | None; classifier_version: str

class RefClassQuery(BaseModel):                       # frozen, extra="forbid"
    level: Literal[0, 1, 2, 3, 4]
    category: Literal["a", "b", "c", "d"] | None       # None = dimensión relajada
    event_type: EventType | None
    event_family: EventFamily | None
    yes_is_change: bool                               # nunca se relaja
    horizon_bucket: HorizonBucket | None
    as_of: datetime                                   # UTC; solo resueltos con resolved_at < as_of
    exclude_event_id: str | None                      # excluye mercados hermanos del mismo evento
    classifier_version: str

class FrozenRefClass(BaseModel):                      # frozen, extra="forbid"
    query: RefClassQuery; class_sha: str; members_sha: str; n: int; k: int

def classify_event(market: Market, spec: ResolutionSpec, llm: LlmClient) -> EventLabel
def build_ref_class(market: Market, label: EventLabel, as_of: datetime, db: Db) -> FrozenRefClass
# recorre L0..L4 y devuelve el primer nivel con n ≥ 20
# error: InsufficientReferenceClass si L4 tiene n < 20
def get_or_build_ref_class(market: Market, rules_version: str, db: Db, ...) -> FrozenRefClass
# lee market_ref_class; solo construye si no hay fila
```

**Clasificación.** `config/event_types.toml` contiene reglas regex ordenadas por prioridad, aplicadas sobre `question` + `rules_text`; gana la primera coincidencia (`method="rule"`). Sin coincidencia, Haiku elige del enum con temperatura 0 y salida forzada a schema (`method="llm"`).

`yes_is_change` sale de la misma llamada, o de la regla si la define:

- `true`: YES exige que algo ocurra o cambie respecto al estado en t (ley aprobada, ataque, renuncia, cambio de tipos).
- `false`: YES es el statu quo (sigue en el cargo, tipos sin cambio).

El resultado se guarda en `market_event_type` con clave (market\_id, rules\_sha, classifier\_version). Los mercados históricos de la población se clasifican con el mismo `classifier_version` en el backfill de Fase 2. INFERIDO: \~1 USD único para 5,000 mercados no cubiertos por reglas.

**Dimensiones.**

| Dimensión | ¿Entra? | Motivo |
| --- | --- | --- |
| category | Sí, solo en L0 | Captura diferencias de cobertura y de redacción entre venues temáticos |
| event\_type | Sí, L0–L2; en L3 pasa a event\_family | Es el determinante principal de la mecánica del suceso |
| yes\_is\_change | Sí; nunca se relaja | INFERIDO: es la dimensión con más señal sobre la tasa de YES en mercados "¿ocurre X antes de D?". Mezclar ambos sentidos da una tasa sin significado |
| horizon\_bucket | Sí, L0–L1 | La probabilidad de que algo ocurra depende del tiempo restante |
| Bucket de precio | No | Calibraría el precio, no una vista externa. Ya está en p\_implied\_debiased (D5); incluirlo contaría el mercado dos veces en el shrinkage |
| Volumen o liquidez | No | Son variables de selección, no del suceso, y reintroducen el sesgo que D3 evita |
| Entidades concretas (país, persona) | No | Casi siempre dan n < 20; sobreajuste |
| Fecha de creación | No | La no estacionariedad ya la controla `as_of` |

**Regla de pertenencia.** Un mercado r pertenece a la clase de Q si se cumplen las 6 condiciones:

1. `r.outcome ∈ {YES, NO}` (VOID excluido) y `r.resolved_at < Q.as_of`.
2. `r.category ≠ 'other'` y, si `Q.category` no es None, `r.category = Q.category`.
3. La etiqueta de r con `Q.classifier_version` coincide en `yes_is_change` y en `event_type` o `event_family` (lo que Q fije).
4. `r.event_id ≠ Q.exclude_event_id`.
5. Horizonte: con τ = r.end\_date\_utc − HORIZON\_LO\_DAYS\[Q.horizon\_bucket\] días (o 2 días si es None), r estaba vivo en τ: `r.start_utc ≤ τ < r.resolved_at`. Es decir, r estuvo abierto con al menos el mínimo de días restantes del bucket.
6. `start_utc` = `startDate` de Gamma y `resolved_at` = `closedTime` de Gamma. Su semántica en mercados cerrados es una tarea de verificación de Fase 2. Si falta `startDate`, se usa el primer punto de `/prices-history`.

Tasa base = k / n, con IC 95% de Wilson.

**Cadena de degradación.** Se usa el primer nivel con n ≥ 20.

| Nivel | Dimensiones | Se relaja | Motivo del orden (INFERIDO) |
| --- | --- | --- | --- |
| L0 | category, event\_type, yes\_is\_change, horizon | — | Clase más específica |
| L1 | event\_type, yes\_is\_change, horizon | category | event\_type ya contiene casi toda la información de la categoría (b y c comparten tipos) |
| L2 | event\_type, yes\_is\_change | horizon (τ con 2 días) | El horizonte pesa menos que el tipo de suceso |
| L3 | event\_family, yes\_is\_change | event\_type → familia | La familia conserva la mecánica gruesa |
| L4 | yes\_is\_change | familia | Último nivel con significado |

Si L4 tiene n < 20, `InsufficientReferenceClass`. El mercado no se analiza y queda en `selection_members.exclusion_reason = 'REFCLASS_EXHAUSTED'`, contado en la auditoría de representatividad (D3).

**Clases externas.**

| Opción | Validación | Recomendación |
| --- | --- | --- |
| A. Solo mercados resueltos de Polymarket | No aplica | **Adoptar** en Fase 3 |
| B. Clases externas vía registro `config/ref_external.toml`: URL, licencia, sha256 del fichero fijado, definición de YES y mapeo a (event\_type, yes\_is\_change, horizon) | (1) El fichero coincide con su sha256. (2) n ≥ 20. (3) Si la clase interna equivalente tiene n ≥ 20, la tasa externa cae dentro de su IC 95% de Wilson; si no, se rechaza. (4) `source = "external"`. (5) Cada entrada requiere tu aprobación | Implementar el registro vacío. Solo puede sustituir niveles L2–L4, nunca L0–L1 |

**Congelación y hash.**

1. `as_of` = `started_at` del ciclo que crea la revisión 0. Un `resume` del mismo ciclo produce el mismo valor.
2. `class_sha = sha256(canonical_json(query))`, con `canonical_json = json.dumps(query.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)` y datetimes en ISO-8601 `Z` con precisión de segundos.
3. `members_sha = sha256("\n".join(sorted(market_ids)))`.
4. Se persiste en `ref_classes`, `ref_class_members` y `market_ref_class` (migración 0002). `market_ref_class` es inmutable por trigger.
5. `get_or_build_ref_class` lee primero `market_ref_class`. Si existe la fila, devuelve esa clase sin recalcular.
6. Test de reproducibilidad: recalcular la pertenencia con el `as_of` guardado debe dar el mismo `members_sha`. Si no coincide (por ejemplo, un resultado revisado a posteriori), lanza `IdempotencyConflict` y se registra; la clase congelada no cambia.

### Tabla de sesgo del precio (D5)

`p_implied_debiased` se calcula con una tabla ajustada solo con datos anteriores a un corte mensual y aplicada solo a forecasts posteriores a ese corte.

1. **Corte.** c\_m = día 1 de cada mes, 00:00 UTC.
2. **Ventana de ajuste.** Mercados con outcome YES o NO, categoría a–d y resolved\_at ∈ \[c\_m − 365 d, c\_m).
3. **Una observación por mercado y horizonte.** Para cada bucket H se toma el mid en τ\_H = end\_date − d\_H, con el bucket de calibración y su centro d\_H de la tabla "Buckets de calibración (B3)": 5, 11, 30 y 68 días: el último punto de `/prices-history` con `fidelity = 60` y t ≤ τ\_H. Se excluye si el mercado no estaba vivo en τ\_H o si no hay punto en las 24 h previas.
4. **Celda.** (category, bucket de calibración H1a/H1b/H2/H3, decil del mid 0–9).
5. **n mínimo.** 30 observaciones por celda en la ventana de ajuste.
6. **Estimador.** `p_debiased = clip(mid + λ·(ȳ_celda − mid̄_celda), 0.01, 0.99)`, con λ = n / (n + 50).
7. **Celdas por debajo de n.** Primero se agrega por (H, decil) sobre todas las categorías. Si sigue < 30, se usa la identidad (`p_debiased = mid`) y la celda se marca `identity`. El mes 1, sin backfill suficiente, es todo identidad.
8. **Ventana de aplicación.** Forecasts con t0 ∈ \[c\_m, c\_{m+1}). Cada forecast guarda `bias_version`.
9. **Persistencia.** `calibration_params` guarda `fit_from_utc`, `cutoff_utc`, `applies_from_utc`, `applies_to_utc` y el recuento de celdas ok, agregadas e identidad. Un trigger rechaza `applies_from_utc < cutoff_utc`.
10. **Test de invariantes.** Ningún mercado del ajuste tiene `resolved_at ≥ cutoff_utc`, y todo forecast tiene `t0` dentro de la ventana de aplicación de su `bias_version`.

### Buckets de calibración (B3)

La tabla de sesgo parte H1 en dos sub-buckets con centro propio; las clases de referencia (D2) mantienen H1 entero. Intervalos semiabiertos en días a end\_date; centro = floor((lo + hi) / 2).

| Bucket de calibración | Intervalo | Centro d\_H | Vida mínima exigida al mercado |
| --- | --- | --- | --- |
| H1a | \[2, 8) | 5 | 5 días |
| H1b | \[8, 15) | 11 | 11 días |
| H2 | \[15, 46) | 30 | 30 días |
| H3 | \[46, 90\] | 68 | 68 días |

H2 y H3 siguen centrados con la regla del floor: 30 en \[15, 46) y 68 en \[46, 90\]. Un forecast usa el bucket que corresponde a sus días a end\_date en t0.

| Opción | Sesgo residual | Coste | Recomendación |
| --- | --- | --- | --- |
| (A) d\_H1 = 5 con H1 entero | La observación mide el precio a 5 días mientras los forecasts de H1 van de 2 a 14: descentrada en 3 días. Excluye mercados con vida < 5 días | Ninguno | Rechazar |
| (B) Partir H1 solo en la tabla de sesgo: H1a con centro 5, H1b con centro 11 | Celdas centradas. Solo quedan fuera de H1a los mercados con vida < 5 días | Más celdas, así que más agregación o identidad por n < 30 | **Adoptar** |
| (C) Partir H1 también en `HorizonBucket` de D2 | Igual que (B) | Cambia el enum de D2 y alarga la cadena de degradación | Rechazar |

Sesgo residual documentado (INFERIDO): los mercados cuya vida total es menor de 5 días no aportan observaciones a H1a. Un forecast sobre uno de ellos (2–4 días restantes, creado hace menos de 5) se corrige con la celda H1a, que se ajustó con mercados de vida ≥ 5 días. El informe mensual muestra la fracción de forecasts H1a con vida < 5 días. Si supera el 20%, la celda H1a de esos forecasts se fuerza a identidad.

### evidence

```python
class EvidenceItem(BaseModel):
    evidence_id: str; url: HttpUrl; source_id: str; tier: Literal["A", "B", "C"]
    published_at: datetime | None; retrieved_at: datetime
    excerpt: str                      # literal, ≤ 300 caracteres, recortado del texto descargado
    stance: Literal["pro_yes", "pro_no", "neutral"]
    label: Literal["VERIFICADO", "INFERIDO", "ESPECULACION", "SIN_VERIFICAR"]
def retrieve(market: Market, spec: ResolutionSpec, thesis: str, *, max_items: int) -> EvidenceBundle
# EvidenceBundle: items, contra_queries (las consultas de contra-tesis ejecutadas), contra_found: bool,
#   contra_absent_reason: str | None
# invariante: un excerpt debe aparecer literalmente en el texto descargado de su URL; si no, la etiqueta pasa a SIN_VERIFICAR
# error: InsufficientEvidence si 0 items tier A/B
```

El texto descargado se trata solo como dato. Nunca se interpola como instrucción del prompt: va dentro de un bloque delimitado y se le eliminan las etiquetas de rol.

### synthesis

```python
class Adjustment(BaseModel):
    reason: str; delta_logit: float; evidence_ids: list[str]; label: Literal["VERIFICADO", "INFERIDO", "ESPECULACION"]
def combine(ov: OutsideView, adj: list[Adjustment], rt: RedTeam) -> Estimate
# logit(p_model) = logit(base_rate) + Σ delta_logit_i
# reglas: |delta_logit| > 0.3 exige ≥ 1 evidencia VERIFICADO; ESPECULACION aporta 0; |Σ| ≤ 1.5
def shrink(p_model: float, p_mkt: float, w: float) -> float
# logit(p_final) = w·logit(p_model) + (1−w)·logit(p_mkt_debiased); w inicial 0.30, se recalibra (Fase 5)
```

### decision, ledger, eval

```python
def quote_sides(p_final: float, book: OrderBook, params: ClobParams, size_shares: float) -> tuple[EdgeQuote, EdgeQuote]
# EdgeQuote: side, vwap, fee_per_share, cost_per_share = vwap + fee, edge_gross, edge_net = p_side − cost
def apply_filters(ctx: DecisionContext) -> FilterResult          # passed, failures: list[FilterCode]
def size(p_side: float, cost: float, bankroll: float, caps: Caps, min_shares: float) -> SizeResult
# SizeResult: kelly_full, stake_usd, shares, outcome: SIZED | NO_TRADE_SIZE | NO_TRADE_CAP
def risk_check(portfolio: Portfolio, cand: SizeResult, cluster_id: str, caps: Caps) -> RiskResult   # caps = CAPS_BY_MODE[mode] (C1)

def record_forecast(db: Db, a: Analysis) -> None                 # congela p_final, mid_t0, t_evidence y mid_t_evidence; inmutable
def record_pick(db: Db, d: Decision) -> None
def settle(db: Db, market: Market) -> Settlement                 # YES, NO o VOID (devuelve el coste)

def paired_delta_brier(rows: Sequence[Scored], n_boot: int = 10_000, seed: int = 0) -> DeltaBrier
def calibration(rows: Sequence[Scored], bins: int = 10) -> CalibrationReport   # ECE, slope, intercept
def promotion_check(db: Db, now: datetime) -> PromotionVerdict   # P1-P7, cada uno con valor y umbral
```

### Caps por modo y veredictos (C1, C11)

```python
LedgerMode = Literal["paper", "live_6a", "live_6b", "live_6b_c"]

class Caps(BaseModel):                                # frozen; fracciones de B
    profile: Literal["paper", "6b", "6b_c"]
    kelly_fraction: float; per_position: float; per_cluster: float; total_open: float; max_positions: int

CAPS_6B    = Caps(profile="6b",   kelly_fraction=0.25, per_position=0.10, per_cluster=0.20, total_open=0.50, max_positions=8)
CAPS_PAPER = CAPS_6B.model_copy(update={"profile": "paper"})
CAPS_6B_C  = Caps(profile="6b_c", kelly_fraction=0.25, per_position=0.05, per_cluster=0.10, total_open=0.25, max_positions=4)
CAPS_BY_MODE: Final[Mapping[LedgerMode, Caps]] = {
    "paper": CAPS_PAPER, "live_6b": CAPS_6B, "live_6b_c": CAPS_6B_C,
}   # live_6a no usa Caps: como máximo 2 órdenes de tamaño mínimo

class Gate(StrEnum): P1 = "P1"; P2 = "P2"; P3 = "P3"; P4 = "P4"; P5 = "P5"; P6 = "P6"; P7 = "P7"
class GateResult(BaseModel):
    gate: Gate; value: float | None; threshold: str; passed: bool
    reason: Literal["power", "signal"] | None          # solo P4

class PromotionOutcome(StrEnum):                       # promotion_check, antes de vivo
    NOT_READY           = "not_ready"            # P1 sin cumplir y la ventana sigue abierta
    NO_EDGE             = "no_edge"              # P2 falla al cierre de la ventana: "sin ventaja demostrada"
    NO_PROMOTION_GATES  = "no_promotion_gates"   # falla P3, P5 o P6
    NO_PROMOTION_SIGNAL = "no_promotion_signal"  # P4 falla por señal
    PROMOTE_6B_C        = "promote_6b_c"         # P4 falla por potencia: 6a y después 6b-C (B1)
    PROMOTE_6B          = "promote_6b"           # todo pasa: 6a y después 6b

class ModelVariant(StrEnum):
    FULL = "full"; NO_LLM = "no_llm"             # NO_LLM si P7 falla: se opera p_implied_debiased sin ajustes LLM

class PromotionVerdict(BaseModel):
    outcome: PromotionOutcome; variant: ModelVariant; gates: list[GateResult]
    evaluated_at: datetime; rules_version: str

class LiveOutcome(StrEnum):                            # live_review, durante 6b-C y 6b (C10)
    CONTINUE        = "continue"
    UPGRADE_TO_6B   = "upgrade_to_6b"            # 6b-C con P4 aprobado
    DEGRADE_TO_6B_C = "degrade_to_6b_c"          # 6b con P4 fallando por potencia en la revisión trimestral
    BACK_TO_PAPER   = "back_to_paper"            # parada temprana, P2 falla, o P4 falla por señal
    STOPPED         = "stopped"                  # stop del 15%; requiere --ack-stop

class LiveReview(BaseModel):
    outcome: LiveOutcome; mode: LedgerMode; gates: list[GateResult]; evaluated_at: datetime; rules_version: str

def promotion_check(db: Db, now: datetime) -> PromotionVerdict
def live_review(db: Db, now: datetime, mode: Literal["live_6b", "live_6b_c"]) -> LiveReview
```

Precedencia de `PromotionOutcome`: se devuelve el primero que aplica en el orden NOT\_READY → NO\_EDGE → NO\_PROMOTION\_GATES → NO\_PROMOTION\_SIGNAL → PROMOTE\_6B\_C → PROMOTE\_6B. P7 no bloquea: solo fija `variant`.

Precedencia de `LiveOutcome`: STOPPED → BACK\_TO\_PAPER → DEGRADE\_TO\_6B\_C → UPGRADE\_TO\_6B → CONTINUE.

### pipeline

`run_cycle(cycle_id)` ejecuta 9 pasos en orden: ingest → normalize → rules → triage → evidence → analysis → synthesis → decision → settle/eval. Cada paso escribe un checkpoint `(cycle_id, step, market_id, status)` en la misma transacción que su salida. `resume(cycle_id)` salta los pares ya `done`. Un mercado que falla queda `failed` con el error y no bloquea a los demás.

### pipeline.select: universo, recorte y metadatos (D3)

En cada ciclo se enumera el universo completo de mercados abiertos de las 4 categorías, sin ordenar ni filtrar por volumen. El recorte a 150 es un muestreo estratificado por hash, determinista y auditable.

```python
def select(http: HttpClient, db: Db, cfg: SelectionConfig, cycle: Cycle) -> SelectionRun
# SelectionRun: universe (list[SelectedMarket]), triage_batch (≤ 150), counts, universe_sha
# error: SelectionIncomplete si alguna enumeración por tag no termina; no se usa un universo parcial
```

**1. Consulta.** Para cada categoría c ∈ {a, b, c, d} y cada `tag_id` de `categories.toml[c]`:

```text
GET https://gamma-api.polymarket.com/markets/keyset
    ?closed=false
    &tag_id={tag_id}
    &end_date_min={cycle.started_at + 2 d, ISO-8601 Z}
    &end_date_max={cycle.started_at + 90 d, ISO-8601 Z}
    &limit=100
    [&after_cursor={next_cursor}]
```

No se envían `order`, `volume_num_*` ni `liquidity_num_*`.

- VERIFICADO en la [referencia de /markets/keyset](https://docs.polymarket.com/cn/api-reference/endpoints/gamma/get-markets-keyset): `after_cursor`, `next_cursor`, `limit` máximo 100 y `offset` rechazado con 422.
- VERIFICADO en la [referencia de /markets](https://docs.polymarket.com/api-reference/markets/list-markets): `active` no es parámetro, así que se filtra en local.

**2. Paginación.** Se itera mientras la respuesta traiga `next_cursor`. Hay un límite de 200 páginas por tag: si se alcanza, `SchemaDrift`.

Si la enumeración de cualquier tag falla tras los reintentos de `infra.http`, el paso `select` del ciclo queda `failed` y no se tría nada nuevo ese ciclo. Revisiones y liquidaciones siguen. Así se evita un universo parcial sesgado hacia los tags que respondieron.

**3. Deduplicación y categoría.** Clave: `market_id` (Gamma `id`). Un mercado que aparece bajo varios tags se asigna a la primera categoría de `categories.toml.priority` (por defecto `["a", "b", "c", "d"]`) cuyo conjunto de tags interseca con los del mercado. Si no interseca con ninguna, la categoría es `'other'`.

**4. Elegibilidad.** Los filtros se aplican en local y en orden; se guarda el primer motivo de exclusión.

| Código | Condición para ser elegible |
| --- | --- |
| E1 | category ∈ {a, b, c, d}. `'other'` se excluye aquí (D6). Desde el mes 4, solo las 2 categorías activas (1.4.0) |
| E2 | active = true y closed = false |
| E3 | 2 ≤ (end\_date − cycle.started\_at) ≤ 90 días, recalculado en local |
| E4 | enableOrderBook = true y exactamente 2 tokens |
| E5 | rules\_text no vacío |
| E6 | Sin forecast previo. Los mercados con forecast van al flujo de revisiones, no al triaje |

**5. Pool de triaje.** T = elegibles que nunca se triaron con la `rules_version` vigente (`pool = 'new'`), más elegibles ya triados sin forecast cuyo mid se movió ≥ 0.05 desde el último triaje (`pool = 'retriage'`).

**6. Orden determinista.** `rank_key = sha256(f"{cycle_id}|{market_id}")` en hex. Se ordena por (`rank_key`, `market_id`); `market_id` es el desempate estable.

**7. Recorte a 150 sin sesgo.** Estratificación proporcional por categoría:

1. quota\_c = floor(150 · |T\_c| / |T|).
2. Las plazas sobrantes se asignan por mayor resto; los empates se resuelven por el orden a, b, c, d.
3. Si quota\_c > |T\_c|, el excedente se reparte con la misma regla.
4. Dentro de cada estrato se toman los primeros quota\_c por `rank_key`.
5. Se guarda la probabilidad de inclusión p\_incl\_triage = quota\_c / |T\_c|.

| Opción de recorte | Sesgo | Reproducible sin estado | Recomendación |
| --- | --- | --- | --- |
| Top 150 por volumen | Hacia mercados líquidos (el defecto D3) | Sí | Rechazar |
| FIFO por first\_seen\_at | Hacia mercados largos y listados hace tiempo | Sí | Rechazar |
| Aleatorio con semilla guardada | Ninguno | Requiere guardar semilla y versión del RNG | Aceptable |
| Hash por ciclo + estratificación proporcional | Ninguno; composición por categoría igual a la del pool | Sí | **Adoptar** |

**8. Del triaje al forecast.**

- El triaje solo devuelve `{analyzable: bool, reason_code}`. Su schema no tiene campo de probabilidad ni de edge, así que el triaje no puede seleccionar por ventaja esperada. Es analizable si las reglas son legibles, nombran al menos una fuente de resolución y el suceso es resoluble dentro del horizonte.
- Cuota del ciclo: q = ceil(cuota\_mensual\_restante / ciclos\_restantes\_del\_mes), con cuota mensual 75 (1.4.0).
- Se eligen q analizables por `rank_key`. Prioridad: si una categoría lleva < 10 forecasts en el mes (< 25 desde el mes 4, solo entre las 2 categorías activas) y tiene analizables, su primer mercado ocupa la primera plaza libre.
- Se guarda p\_incl\_forecast.

**9. Metadatos persistidos** (migración 0002):

- `selection_runs`: parámetros de la consulta, páginas, recuentos por etapa y `universe_sha` (sha256 de los `market_id` elegibles ordenados).
- `selection_members`: una fila por mercado y ciclo, con:
  - category, horizon\_days, mid\_at\_selection
  - vol\_24h\_usd y liquidity\_usd, guardados solo para auditoría; nunca ordenan ni filtran
  - eligible, exclusion\_reason, pool, rank\_key, stratum\_size, quota, p\_incl\_triage
  - triaged, triage\_analyzable, p\_incl\_forecast, forecast\_selected

**10. Auditoría de representatividad** (informe mensual). Se compara la muestra de forecasts con el universo elegible del mes en 4 variables: categoría, horizon\_days, |mid − 0.5| y log(1 + vol\_24h). La métrica es la diferencia de medias estandarizada (SMD), con la muestra ponderada por 1 / (p\_incl\_triage · p\_incl\_forecast) frente al universo elegible sin ponderar (definición precisada en C4). Alerta si |SMD| > 0.10 en cualquiera. M1 se reporta también ponderado por 1/p\_incl\_forecast (Horvitz–Thompson) junto al M1 sin ponderar.

### Invariante de categoría (D6)

`markets.category` admite `'other'` para no perder datos en la ingesta. El análisis solo admite a–d. Hay 3 controles:

1. E1 excluye `'other'` en la selección.
2. `analyze()` empieza con una aserción de runtime: si `market.category not in {"a", "b", "c", "d"}`, lanza `CategoryInvariantError(market_id)`, subclase de `PmsysError`. No se desactiva con `-O` porque es un `if` + `raise`, no un `assert`.
3. El trigger `trg_forecasts_v11_required` (migración 0002) rechaza en la base cualquier forecast con categoría fuera de a–d.

Test: un mercado `'other'` inyectado tras E1 debe fallar en (2), y un INSERT directo en `forecasts` debe fallar en (3).

## (c) DDL SQLite

El DDL es la migración `0001_init.sql`, con 17 tablas. VERIFICADO: lo ejecuté con `sqlite3` de Python 3. Parsea, aplica las FK y los triggers de inmutabilidad de `forecasts` abortan los UPDATE y DELETE. Todas las fechas son TEXT ISO-8601 UTC. Las migraciones siguientes solo añaden columnas y tablas; nunca reescriben `forecasts`.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, sha256 TEXT NOT NULL
);

CREATE TABLE markets (
  market_id       TEXT PRIMARY KEY,                -- Gamma id
  condition_id    TEXT NOT NULL UNIQUE,
  event_id        TEXT,
  slug            TEXT,
  question        TEXT NOT NULL,
  rules_text      TEXT NOT NULL,
  rules_sha       TEXT NOT NULL,
  category        TEXT NOT NULL CHECK (category IN ('a','b','c','d','other')),
  tags_json       TEXT NOT NULL DEFAULT '[]',
  yes_token_id    TEXT NOT NULL,
  no_token_id     TEXT NOT NULL,
  neg_risk        INTEGER NOT NULL CHECK (neg_risk IN (0,1)),
  end_date_utc    TEXT,
  active          INTEGER NOT NULL CHECK (active IN (0,1)),
  closed          INTEGER NOT NULL CHECK (closed IN (0,1)),
  uma_status      TEXT,
  outcome         TEXT CHECK (outcome IN ('YES','NO','VOID')),
  resolved_at     TEXT,
  first_seen_at   TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  raw_json        TEXT NOT NULL
);
CREATE INDEX ix_markets_open      ON markets (active, closed, end_date_utc);
CREATE INDEX ix_markets_category  ON markets (category, end_date_utc);
CREATE INDEX ix_markets_event     ON markets (event_id);
CREATE INDEX ix_markets_unsettled ON markets (closed, outcome) WHERE outcome IS NULL;

CREATE TABLE clob_params (
  condition_id   TEXT NOT NULL REFERENCES markets(condition_id),
  fetched_at     TEXT NOT NULL,
  min_order_size REAL NOT NULL,
  tick_size      REAL NOT NULL,
  fee_rate       REAL,
  fee_exponent   REAL,
  taker_only     INTEGER,
  raw_json       TEXT NOT NULL,
  PRIMARY KEY (condition_id, fetched_at)
);

CREATE TABLE rules_specs (
  market_id        TEXT NOT NULL REFERENCES markets(market_id),
  rules_sha        TEXT NOT NULL,
  parser_version   TEXT NOT NULL,
  spec_json        TEXT NOT NULL,
  ambiguity_det    INTEGER NOT NULL CHECK (ambiguity_det BETWEEN 0 AND 10),
  ambiguity_llm    INTEGER CHECK (ambiguity_llm BETWEEN 0 AND 10),
  ambiguity_final  INTEGER NOT NULL CHECK (ambiguity_final BETWEEN 0 AND 10),
  created_at       TEXT NOT NULL,
  PRIMARY KEY (market_id, rules_sha, parser_version)
);

CREATE TABLE book_snapshots (
  token_id TEXT NOT NULL, ts TEXT NOT NULL,
  best_bid REAL, best_ask REAL,
  depth_json TEXT NOT NULL,                        -- top 20 niveles por lado
  PRIMARY KEY (token_id, ts)
);

CREATE TABLE price_points (
  token_id TEXT NOT NULL,
  t        INTEGER NOT NULL,                       -- unix s UTC
  p        REAL NOT NULL CHECK (p BETWEEN 0 AND 1),
  PRIMARY KEY (token_id, t)
) WITHOUT ROWID;

CREATE TABLE evidence (
  evidence_id   TEXT PRIMARY KEY,                  -- sha256(url_norm|excerpt)
  url           TEXT NOT NULL,
  url_sha       TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  tier          TEXT NOT NULL CHECK (tier IN ('A','B','C')),
  published_at  TEXT,
  retrieved_at  TEXT NOT NULL,
  excerpt       TEXT NOT NULL CHECK (length(excerpt) <= 300),
  content_sha   TEXT NOT NULL,
  excerpt_found INTEGER NOT NULL CHECK (excerpt_found IN (0,1))
);
CREATE INDEX ix_evidence_url ON evidence (url_sha);

CREATE TABLE analyses (
  analysis_id   TEXT PRIMARY KEY,
  idem_key      TEXT NOT NULL UNIQUE,              -- sha256(market_id|rules_sha|rules_version|revision)
  market_id     TEXT NOT NULL REFERENCES markets(market_id),
  rules_version TEXT NOT NULL,                     -- sha256(settings.toml + prompts/)
  revision      INTEGER NOT NULL CHECK (revision >= 0),
  cycle_id      TEXT NOT NULL,
  t0            TEXT NOT NULL,
  mid_t0        REAL NOT NULL CHECK (mid_t0 BETWEEN 0 AND 1),
  p_base        REAL CHECK (p_base BETWEEN 0 AND 1),
  p_model       REAL CHECK (p_model BETWEEN 0 AND 1),
  p_final       REAL CHECK (p_final BETWEEN 0 AND 1),
  shrink_w      REAL CHECK (shrink_w BETWEEN 0 AND 1),
  verdict       TEXT NOT NULL CHECK (verdict IN ('PICK_YES','PICK_NO','NO_TRADE','INSUFFICIENT_EVIDENCE')),
  analysis_json TEXT NOT NULL,                     -- valida contra el JSON Schema (d)
  cost_usd      REAL NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL
);
CREATE INDEX ix_analyses_market ON analyses (market_id, revision);
CREATE INDEX ix_analyses_cycle  ON analyses (cycle_id);

CREATE TABLE analysis_evidence (
  analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id),
  evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
  role        TEXT NOT NULL CHECK (role IN ('support','contra','context')),
  label       TEXT NOT NULL CHECK (label IN ('VERIFICADO','INFERIDO','ESPECULACION','SIN_VERIFICAR')),
  PRIMARY KEY (analysis_id, evidence_id)
);
CREATE INDEX ix_ae_evidence ON analysis_evidence (evidence_id);

CREATE TABLE forecasts (                           -- primer p_final congelado: base del scoring
  market_id   TEXT PRIMARY KEY REFERENCES markets(market_id),
  analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id),
  t0          TEXT NOT NULL,
  p_final     REAL NOT NULL,
  mid_t0      REAL NOT NULL,
  category    TEXT NOT NULL,
  horizon_d   REAL NOT NULL
);
CREATE TRIGGER trg_forecasts_immutable BEFORE UPDATE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts are immutable'); END;
CREATE TRIGGER trg_forecasts_nodelete BEFORE DELETE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts are immutable'); END;

CREATE TABLE decisions (
  decision_id   TEXT PRIMARY KEY,
  analysis_id   TEXT NOT NULL REFERENCES analyses(analysis_id),
  side          TEXT CHECK (side IN ('YES','NO')),
  vwap REAL, fee_per_share REAL, edge_net REAL,
  filters_json  TEXT NOT NULL,                     -- {"passed": bool, "failures": [...]}
  kelly_full REAL, stake_usd REAL, shares REAL,
  outcome       TEXT NOT NULL CHECK (outcome IN ('SIZED','NO_TRADE_FILTER','NO_TRADE_SIZE','NO_TRADE_CAP','NO_TRADE_STOP')),
  cluster_id    TEXT,
  created_at    TEXT NOT NULL
);
CREATE INDEX ix_decisions_analysis ON decisions (analysis_id);

CREATE TABLE positions (
  position_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
  mode        TEXT NOT NULL CHECK (mode IN ('paper','live_6a','live_6b')),
  market_id   TEXT NOT NULL REFERENCES markets(market_id),
  side        TEXT NOT NULL CHECK (side IN ('YES','NO')),
  shares      REAL NOT NULL CHECK (shares > 0),
  entry_price REAL NOT NULL,
  fee_paid    REAL NOT NULL,
  opened_at   TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('open','settled','closed_early')),
  exit_price REAL, pnl_usd REAL, settled_at TEXT,
  clv_close   REAL,                                -- precio del lado al cierre - entry_price
  fill_ref    TEXT                                 -- vivo: referencia del fill manual
);
CREATE INDEX ix_positions_open ON positions (mode, status);
CREATE INDEX ix_positions_mkt  ON positions (market_id);

CREATE TABLE equity (
  mode TEXT NOT NULL, ts TEXT NOT NULL,
  bankroll REAL NOT NULL, mtm_equity REAL NOT NULL, peak REAL NOT NULL, drawdown REAL NOT NULL,
  PRIMARY KEY (mode, ts)
);

CREATE TABLE system_state (                        -- stop, presupuesto, flags
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE llm_calls (
  call_id TEXT PRIMARY KEY, ts TEXT NOT NULL, task TEXT NOT NULL, model TEXT NOT NULL,
  prompt_sha TEXT NOT NULL, market_id TEXT, batch INTEGER NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','schema_violation','error'))
);
CREATE INDEX ix_llm_month ON llm_calls (substr(ts,1,7));

CREATE TABLE calibration_params (
  version TEXT PRIMARY KEY, fitted_at TEXT NOT NULL, n_train INTEGER NOT NULL,
  shrink_w REAL NOT NULL, platt_a REAL NOT NULL, platt_b REAL NOT NULL,
  bucket_table_json TEXT NOT NULL, oos_delta_brier REAL NOT NULL, active INTEGER NOT NULL
);

CREATE TABLE checkpoints (
  cycle_id TEXT NOT NULL, step TEXT NOT NULL, market_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('running','done','failed')),
  error TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (cycle_id, step, market_id)
);
CREATE INDEX ix_checkpoints_status ON checkpoints (cycle_id, status);
```

Idempotencia: `idem_key` es `UNIQUE`. Un reintento del mismo análisis hace `INSERT ... ON CONFLICT(idem_key) DO NOTHING` y reutiliza la fila existente. La revisión solo sube con un disparador: movimiento del mid ≥ 0.05 desde t0, o una evidencia nueva tier A/B. Máximo 3 revisiones por mercado. El scoring primario usa siempre `forecasts`, es decir, la revisión 0.

### Migración 0002 (v1.1.0)

0002 añade 7 tablas y 15 columnas para D1–D6. VERIFICADO con `sqlite3` de Python sobre 0001 + 0002: 24 tablas. Los triggers rechazan 4 casos:

- Un análisis sin `mid_t_evidence`.
- Un forecast `'other'`.
- Un forecast con `t_evidence > t0`.
- Una tabla de sesgo aplicada antes de su corte.

Un forecast válido entra sin error. Los timestamps usan el formato fijo `YYYY-MM-DDTHH:MM:SSZ`, así que la comparación de texto equivale a la cronológica.

| Implementación | Ventaja | Inconveniente | Recomendación |
| --- | --- | --- | --- |
| Editar 0001 en sitio (aún no hay datos) | NOT NULL nativo | Se pierde el diff contra la 1.0.0 revisada | Rechazar |
| Nueva migración 0002 | 0001 queda tal como se aprobó; ejercita el migrador desde el día 1 | ADD COLUMN no admite NOT NULL sin DEFAULT; se suple con triggers BEFORE INSERT | **Adoptar** |

```sql
-- 0002: spec 1.1.0 (D1, D2, D3, D4, D5, D6)
-- D4: precio en el instante de congelar la evidencia
ALTER TABLE analyses  ADD COLUMN t_evidence     TEXT;
ALTER TABLE analyses  ADD COLUMN mid_t_evidence REAL CHECK (mid_t_evidence BETWEEN 0 AND 1);
ALTER TABLE forecasts ADD COLUMN t_evidence     TEXT;
ALTER TABLE forecasts ADD COLUMN mid_t_evidence REAL CHECK (mid_t_evidence BETWEEN 0 AND 1);
ALTER TABLE forecasts ADD COLUMN bias_version   TEXT;
ALTER TABLE forecasts ADD COLUMN class_sha      TEXT;

-- D4 + D5 + D6: invariantes en filas nuevas (ADD COLUMN no admite NOT NULL sin DEFAULT)
CREATE TRIGGER trg_analyses_evidence_required BEFORE INSERT ON analyses
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL
BEGIN SELECT RAISE(ABORT, 'analyses.t_evidence/mid_t_evidence required'); END;

CREATE TRIGGER trg_forecasts_v11_required BEFORE INSERT ON forecasts
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL OR NEW.bias_version IS NULL
  OR NEW.t_evidence > NEW.t0
  OR NEW.category NOT IN ('a','b','c','d')
BEGIN SELECT RAISE(ABORT, 'forecast invariant violated (D4/D5/D6)'); END;

-- D1: CLV a horizonte fijo, medible antes de la resolución
ALTER TABLE positions ADD COLUMN t_clv TEXT;
ALTER TABLE positions ADD COLUMN clv_h REAL;      -- mid del lado en t_clv - coste de entrada por acción
CREATE TABLE shadow_picks (                        -- D1: NO_TRADE_SIZE, solo indicador (M10)
  decision_id TEXT PRIMARY KEY REFERENCES decisions(decision_id),
  market_id   TEXT NOT NULL REFERENCES markets(market_id),
  side        TEXT NOT NULL CHECK (side IN ('YES','NO')),
  entry_cost  REAL NOT NULL,                       -- VWAP del tamaño mínimo + comisión
  t_entry     TEXT NOT NULL,
  t_clv       TEXT,
  clv_h       REAL
);

-- D2: tipo de evento y clases de referencia congeladas
CREATE TABLE market_event_type (
  market_id          TEXT NOT NULL REFERENCES markets(market_id),
  rules_sha          TEXT NOT NULL,
  classifier_version TEXT NOT NULL,
  event_type         TEXT NOT NULL,
  event_family       TEXT NOT NULL,
  yes_is_change      INTEGER NOT NULL CHECK (yes_is_change IN (0,1)),
  method             TEXT NOT NULL CHECK (method IN ('rule','llm')),
  rule_id            TEXT,
  created_at         TEXT NOT NULL,
  PRIMARY KEY (market_id, rules_sha, classifier_version)
);
CREATE INDEX ix_met_class ON market_event_type (classifier_version, event_type, yes_is_change);

CREATE TABLE ref_classes (
  class_sha   TEXT PRIMARY KEY,                    -- sha256(canonical_json(RefClassQuery))
  query_json  TEXT NOT NULL,
  level       INTEGER NOT NULL CHECK (level BETWEEN 0 AND 4),
  as_of       TEXT NOT NULL,
  n           INTEGER NOT NULL CHECK (n >= 20),
  k           INTEGER NOT NULL CHECK (k BETWEEN 0 AND n),
  members_sha TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
CREATE TABLE ref_class_members (
  class_sha TEXT NOT NULL REFERENCES ref_classes(class_sha),
  market_id TEXT NOT NULL REFERENCES markets(market_id),
  PRIMARY KEY (class_sha, market_id)
) WITHOUT ROWID;
CREATE TABLE market_ref_class (
  market_id     TEXT NOT NULL REFERENCES markets(market_id),
  rules_sha     TEXT NOT NULL,
  rules_version TEXT NOT NULL,
  class_sha     TEXT NOT NULL REFERENCES ref_classes(class_sha),
  PRIMARY KEY (market_id, rules_sha, rules_version)
);
CREATE TRIGGER trg_market_ref_class_immutable BEFORE UPDATE ON market_ref_class
BEGIN SELECT RAISE(ABORT, 'ref class is frozen'); END;

-- D3: selección auditable
CREATE TABLE selection_runs (
  cycle_id      TEXT PRIMARY KEY,
  started_at    TEXT NOT NULL,
  params_json   TEXT NOT NULL,                     -- tags, end_date_min/max, rules_version
  pages_fetched INTEGER NOT NULL,
  n_raw         INTEGER NOT NULL,
  n_dedup       INTEGER NOT NULL,
  n_eligible    INTEGER NOT NULL,
  n_triage_pool INTEGER NOT NULL,
  n_triaged     INTEGER NOT NULL,
  n_forecast    INTEGER NOT NULL,
  universe_sha  TEXT NOT NULL,                     -- sha256 de market_id elegibles ordenados
  status        TEXT NOT NULL CHECK (status IN ('complete','failed'))
);
CREATE TABLE selection_members (
  cycle_id          TEXT NOT NULL REFERENCES selection_runs(cycle_id),
  market_id         TEXT NOT NULL,
  category          TEXT NOT NULL,
  horizon_days      REAL,
  mid_at_selection  REAL,
  vol_24h_usd       REAL,                          -- solo auditoría; nunca ordena ni filtra
  liquidity_usd     REAL,                          -- idem
  eligible          INTEGER NOT NULL CHECK (eligible IN (0,1)),
  exclusion_reason  TEXT,                          -- E1..E6, REFCLASS_EXHAUSTED
  pool              TEXT CHECK (pool IN ('new','retriage')),
  rank_key          TEXT,
  stratum_size      INTEGER,
  quota             INTEGER,
  p_incl_triage     REAL,
  triaged           INTEGER NOT NULL DEFAULT 0,
  triage_analyzable INTEGER,
  p_incl_forecast   REAL,
  forecast_selected INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (cycle_id, market_id)
);
CREATE INDEX ix_selm_market    ON selection_members (market_id);
CREATE INDEX ix_selm_cycle_sel ON selection_members (cycle_id, forecast_selected);

-- D5: corte temporal de la tabla de sesgo
ALTER TABLE calibration_params ADD COLUMN fit_from_utc     TEXT;
ALTER TABLE calibration_params ADD COLUMN cutoff_utc       TEXT;  -- fin exclusivo de la ventana de ajuste
ALTER TABLE calibration_params ADD COLUMN applies_from_utc TEXT;
ALTER TABLE calibration_params ADD COLUMN applies_to_utc   TEXT;
ALTER TABLE calibration_params ADD COLUMN n_cells_ok       INTEGER;
ALTER TABLE calibration_params ADD COLUMN n_cells_pooled   INTEGER;
ALTER TABLE calibration_params ADD COLUMN n_cells_identity INTEGER;
CREATE TRIGGER trg_calib_cutoff BEFORE INSERT ON calibration_params
WHEN NEW.cutoff_utc IS NULL OR NEW.applies_from_utc < NEW.cutoff_utc
BEGIN SELECT RAISE(ABORT, 'bias table applied before its cutoff'); END;
```

### Migración 0003 (v1.2.0)

0003 cierra B5, 1.2/M4, 1.2/M5, 1.2/M6 y 1.2/M7. VERIFICADO con `sqlite3` de Python sobre 0001 + 0002 + 0003: los 12 casos de prueba dan el resultado esperado. Se rechazan:

- UPDATE y DELETE en `analyses`, e INSERT con `t_evidence > t0`.
- Un forecast con `bias_version` inexistente.
- Un forecast con `identity-v0` cuando ya hay una versión ajustada vigente en su t0.
- DELETE en `ref_classes`.
- `equity.ts` sin milisegundos.

Se aceptan los casos válidos de cada uno.

**B5. `analyses` tras la escritura.**

| Opción | Garantía | Coste | Recomendación |
| --- | --- | --- | --- |
| A. Trigger BEFORE UPDATE que revalida `t_evidence`, `mid_t_evidence` y `t_evidence ≤ t0` | Impide los nulos, pero permite reescribir p\_final, verdict y analysis\_json | Bajo | Rechazar: deja abierta la reescritura del pronóstico |
| B. `analyses` inmutable siempre (UPDATE y DELETE abortan) | Ninguna fila cambia tras escribirse | Ninguno: por diseño la fila se escribe una vez, completa, tras la decisión. Una corrección es una revisión nueva | **Adoptar** |
| C. Inmutable solo tras existir una fila en `decisions` | Igual que B tras la decisión | Hay una ventana mutable sin uso legítimo | Rechazar |

Como B bloquea los UPDATE, el trigger de INSERT de 0002 se rehace para comprobar también `t_evidence ≤ t0` en `analyses`, no solo en `forecasts`.

**1.2/M4. Versión de sesgo inicial.** 0003 siembra `identity-v0` en `calibration_params`: identidad, `platt_a = 0`, `platt_b = 1`, `shrink_w = 0.30`, vigente de 1970 a 9999.

El trigger de forecasts pasa a exigir que `bias_version` exista y esté vigente en t0. Además, si es `identity-v0`, que no haya ninguna versión ajustada vigente en ese t0. Así, desde el mes 1 todo forecast lleva `identity-v0` hasta el primer corte mensual con tabla ajustada; después, la versión ajustada es obligatoria.

**1.2/M5. Retención de `selection_members`.** INFERIDO: con \~2,000 mercados en el universo y 730 ciclos al año salen \~1.5 millones de filas al año. Compactación mensual, después de generar el informe:

1. Para ciclos con `started_at` anterior a hace 90 días, las filas con `triaged = 0` y `forecast_selected = 0` se agregan en `selection_members_agg`. Por (cycle\_id, category, eligible, exclusion\_reason, pool) se guardan n, suma y suma de cuadrados de horizon\_days, |mid − 0.5| y log(1 + vol\_24h).
2. Esas filas se borran en la misma transacción.
3. Las filas triadas o seleccionadas para forecast se conservan siempre: llevan las probabilidades de inclusión que usa Horvitz–Thompson.
4. La auditoría SMD lee medias y varianzas del universo desde los agregados, así que da el mismo resultado antes y después de compactar. Hay un test que lo verifica sobre un ciclo sintético.

**1.2/M6.** DELETE abortado en `ref_classes`, `ref_class_members` y `market_ref_class`; UPDATE abortado también en `ref_classes`.

**1.2/M7.** `book_snapshots.ts` y `equity.ts` usan el formato `YYYY-MM-DDTHH:MM:SS.sssZ`, impuesto por trigger, para que no colisione la clave primaria con dos escrituras en el mismo segundo. Las comparaciones entre estas columnas y columnas con precisión de segundos se hacen tras parsear a `datetime`, nunca como texto: el carácter `.` ordena antes que `Z`.

```sql
-- 0003: spec 1.2.0 (B5, 1.2/M4, 1.2/M5, 1.2/M6, 1.2/M7)
-- B5: analyses inmutable; t_evidence <= t0 también en analyses
CREATE TRIGGER trg_analyses_immutable BEFORE UPDATE ON analyses
BEGIN SELECT RAISE(ABORT, 'analyses are immutable; write a new revision'); END;
CREATE TRIGGER trg_analyses_nodelete BEFORE DELETE ON analyses
BEGIN SELECT RAISE(ABORT, 'analyses are immutable'); END;
DROP TRIGGER trg_analyses_evidence_required;
CREATE TRIGGER trg_analyses_evidence_required BEFORE INSERT ON analyses
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL OR NEW.t_evidence > NEW.t0
BEGIN SELECT RAISE(ABORT, 'analyses: t_evidence/mid_t_evidence required and t_evidence <= t0'); END;

-- 1.2/M4: versión identidad sembrada; el forecast exige una bias_version existente y vigente en t0
INSERT INTO calibration_params
  (version, fitted_at, n_train, shrink_w, platt_a, platt_b, bucket_table_json, oos_delta_brier, active,
   fit_from_utc, cutoff_utc, applies_from_utc, applies_to_utc, n_cells_ok, n_cells_pooled, n_cells_identity)
VALUES ('identity-v0', '2026-11-05T00:00:00Z', 0, 0.30, 0.0, 1.0, '{"mode":"identity"}', 0.0, 1,
        '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', '9999-12-31T23:59:59Z', 0, 0, 0);
DROP TRIGGER trg_forecasts_v11_required;
CREATE TRIGGER trg_forecasts_v12_required BEFORE INSERT ON forecasts
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL OR NEW.bias_version IS NULL
  OR NEW.t_evidence > NEW.t0
  OR NEW.category NOT IN ('a','b','c','d')
  OR NOT EXISTS (SELECT 1 FROM calibration_params cp
                 WHERE cp.version = NEW.bias_version
                   AND NEW.t0 >= cp.applies_from_utc AND NEW.t0 < cp.applies_to_utc)
  OR (NEW.bias_version = 'identity-v0' AND EXISTS (
        SELECT 1 FROM calibration_params cp
        WHERE cp.version <> 'identity-v0'
          AND NEW.t0 >= cp.applies_from_utc AND NEW.t0 < cp.applies_to_utc))
BEGIN SELECT RAISE(ABORT, 'forecast invariant violated (D4/D5/D6/M4)'); END;

-- 1.2/M5: agregados para compactar selection_members
CREATE TABLE selection_members_agg (
  cycle_id         TEXT NOT NULL REFERENCES selection_runs(cycle_id),
  category         TEXT NOT NULL,
  eligible         INTEGER NOT NULL CHECK (eligible IN (0,1)),
  exclusion_reason TEXT NOT NULL DEFAULT '',
  pool             TEXT NOT NULL DEFAULT '',
  n                INTEGER NOT NULL CHECK (n > 0),
  sum_horizon REAL, sumsq_horizon REAL,
  sum_absmid  REAL, sumsq_absmid  REAL,            -- |mid - 0.5|
  sum_logvol  REAL, sumsq_logvol  REAL,            -- log(1 + vol_24h_usd)
  PRIMARY KEY (cycle_id, category, eligible, exclusion_reason, pool)
);

-- 1.2/M6: clases de referencia no borrables ni editables
CREATE TRIGGER trg_ref_classes_nodelete BEFORE DELETE ON ref_classes
BEGIN SELECT RAISE(ABORT, 'ref classes are frozen'); END;
CREATE TRIGGER trg_ref_classes_noupdate BEFORE UPDATE ON ref_classes
BEGIN SELECT RAISE(ABORT, 'ref classes are frozen'); END;
CREATE TRIGGER trg_ref_class_members_nodelete BEFORE DELETE ON ref_class_members
BEGIN SELECT RAISE(ABORT, 'ref classes are frozen'); END;
CREATE TRIGGER trg_market_ref_class_nodelete BEFORE DELETE ON market_ref_class
BEGIN SELECT RAISE(ABORT, 'ref class is frozen'); END;

-- 1.2/M7: milisegundos en book_snapshots.ts y equity.ts
CREATE TRIGGER trg_book_ts_ms BEFORE INSERT ON book_snapshots
WHEN NEW.ts NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'
BEGIN SELECT RAISE(ABORT, 'book_snapshots.ts must be YYYY-MM-DDTHH:MM:SS.sssZ'); END;
CREATE TRIGGER trg_equity_ts_ms BEFORE INSERT ON equity
WHEN NEW.ts NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'
BEGIN SELECT RAISE(ABORT, 'equity.ts must be YYYY-MM-DDTHH:MM:SS.sssZ'); END;
```

### Migración 0004 (v1.3.0)

0004 cierra C1, C2, C3, C4, C6 y C9. VERIFICADO con `sqlite3` de Python sobre 0001–0004: los 13 casos de prueba dan el resultado esperado.

- **C1.** El modo `live_6b_c` se acepta y un modo desconocido se rechaza.
- **C9.** Un mismo mercado con posición de papel, de 6a y de 6b-C aparece una sola vez en `v_p4_picks`, con el registro de 6b-C.
- **C2.** `t_clv` a menos de 6 h de la entrada se rechaza.
- **C3.** Se rechazan una versión de sesgo solapada y el UPDATE o DELETE en `calibration_params`; una caída a `identity-v0` tras caducar la versión ajustada queda registrada en `bias_fallback_log`.
- **C6.** Una evidencia VERIFICADO con `excerpt_found = 0` se rechaza.

**C1. Modo `live_6b_c`.** SQLite no permite alterar un CHECK, así que `positions` se reconstruye: tabla nueva, copia, borrado y renombrado, sin datos todavía. La reconstrucción añade también `clv_status` (C2). Los caps de cada modo están en `CAPS_BY_MODE` en (b).

**C3. Versiones de sesgo.**

- `calibration_params` es inmutable y no admite ventanas de aplicación solapadas entre versiones ajustadas.
- Siempre hay al menos una versión vigente: `identity-v0` cubre 1970–9999 y ahora no se puede borrar ni editar.
- Si un forecast cae a `identity-v0` después de que caducara una versión ajustada, un trigger AFTER INSERT lo registra en `bias_fallback_log` con la última versión ajustada y su `applies_to_utc`. El informe mensual lista esas caídas.
- A diario, el pipeline alerta si ninguna versión ajustada cubre los próximos 7 días.
- Cada mes se inserta siempre una versión nueva. Si el w y el Platt reajustados no mejoran fuera de muestra (paso 2 del bucle de recalibración), la versión nueva lleva los del mes anterior con la tabla de sesgo nueva. Así, "activar" una versión nunca requiere un UPDATE.

**C4. SMD tras compactar.**

- **Definición exacta de la auditoría D3.** Muestra de forecasts ponderada por w = 1 / (p\_incl\_triage · p\_incl\_forecast), frente al universo elegible sin ponderar.
- **Precisión:** bajo esta definición el universo no necesita pesos, y las filas de la muestra nunca se compactan.
- **Cambio igualmente:** se añaden sumas ponderadas con w = 1 / p\_incl\_triage (1 si es NULL): `sum_w` y suma y suma de cuadrados ponderadas de horizon, absmid y logvol. Así la SMD es recalculable con cualquiera de las dos definiciones.
- **Test de 1.2/M5:** comprueba ambas antes y después de compactar.

**C6.** Un trigger rechaza `analysis_evidence.label = 'VERIFICADO'` si la evidencia tiene `excerpt_found = 0`. El validador pydantic de `EvidenceItem` aplica la misma regla, y F6 la exige.

```sql
-- 0004: spec 1.3.0 (C1, C2, C3, C4, C6, C9)
-- C1 + C2: modo live_6b_c y estado de CLV (SQLite no altera CHECK: se reconstruye positions; aún sin datos)
CREATE TABLE positions_v13 (
  position_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
  mode        TEXT NOT NULL CHECK (mode IN ('paper','live_6a','live_6b','live_6b_c')),
  market_id   TEXT NOT NULL REFERENCES markets(market_id),
  side        TEXT NOT NULL CHECK (side IN ('YES','NO')),
  shares      REAL NOT NULL CHECK (shares > 0),
  entry_price REAL NOT NULL,
  fee_paid    REAL NOT NULL,
  opened_at   TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('open','settled','closed_early')),
  exit_price REAL, pnl_usd REAL, settled_at TEXT,
  clv_close   REAL,
  fill_ref    TEXT,
  t_clv       TEXT,
  clv_h       REAL,
  clv_status  TEXT NOT NULL DEFAULT 'pending' CHECK (clv_status IN ('pending','measured','unmeasurable'))
);
INSERT INTO positions_v13
  (position_id, decision_id, mode, market_id, side, shares, entry_price, fee_paid, opened_at, status,
   exit_price, pnl_usd, settled_at, clv_close, fill_ref, t_clv, clv_h, clv_status)
SELECT position_id, decision_id, mode, market_id, side, shares, entry_price, fee_paid, opened_at, status,
       exit_price, pnl_usd, settled_at, clv_close, fill_ref, t_clv, clv_h,
       CASE WHEN clv_h IS NULL THEN 'pending' ELSE 'measured' END
FROM positions;
DROP TABLE positions;
ALTER TABLE positions_v13 RENAME TO positions;
CREATE INDEX ix_positions_open ON positions (mode, status);
CREATE INDEX ix_positions_mkt  ON positions (market_id);
CREATE TRIGGER trg_positions_clv_after_entry BEFORE UPDATE OF t_clv ON positions
WHEN NEW.t_clv IS NOT NULL AND NEW.clv_status = 'measured'
 AND (julianday(NEW.t_clv) - julianday(NEW.opened_at)) * 24 < 6
BEGIN SELECT RAISE(ABORT, 'C2: t_clv must be >= opened_at + 6 h'); END;
ALTER TABLE shadow_picks ADD COLUMN clv_status TEXT NOT NULL DEFAULT 'pending'
  CHECK (clv_status IN ('pending','measured','unmeasurable'));

-- C9: un mercado cuenta una vez en P4; prevalece el registro vivo; 6a excluido (1.2/M2)
CREATE VIEW v_p4_picks AS
WITH ranked AS (
  SELECT p.*,
         ROW_NUMBER() OVER (
           PARTITION BY p.market_id
           ORDER BY CASE WHEN p.mode IN ('live_6b','live_6b_c') THEN 0 ELSE 1 END, p.opened_at, p.position_id
         ) AS rn
  FROM positions p
  WHERE p.mode IN ('paper','live_6b','live_6b_c')
)
SELECT * FROM ranked WHERE rn = 1 AND clv_status = 'measured';

-- C3: versiones de sesgo inmutables, sin solapes; registro de caída a identidad
CREATE TRIGGER trg_calib_noupdate BEFORE UPDATE ON calibration_params
BEGIN SELECT RAISE(ABORT, 'calibration_params are immutable'); END;
CREATE TRIGGER trg_calib_nodelete BEFORE DELETE ON calibration_params
BEGIN SELECT RAISE(ABORT, 'calibration_params are immutable'); END;
CREATE TRIGGER trg_calib_no_overlap BEFORE INSERT ON calibration_params
WHEN NEW.version <> 'identity-v0' AND EXISTS (
  SELECT 1 FROM calibration_params cp
  WHERE cp.version <> 'identity-v0'
    AND NEW.applies_from_utc < cp.applies_to_utc
    AND cp.applies_from_utc < NEW.applies_to_utc)
BEGIN SELECT RAISE(ABORT, 'C3: overlapping bias versions'); END;
CREATE TABLE bias_fallback_log (
  market_id           TEXT NOT NULL REFERENCES markets(market_id),
  t0                  TEXT NOT NULL,
  last_fitted_version TEXT NOT NULL,
  last_applies_to_utc TEXT NOT NULL,
  PRIMARY KEY (market_id, t0)
);
CREATE TRIGGER trg_forecasts_bias_fallback AFTER INSERT ON forecasts
WHEN NEW.bias_version = 'identity-v0' AND EXISTS (
  SELECT 1 FROM calibration_params cp
  WHERE cp.version <> 'identity-v0' AND cp.applies_to_utc <= NEW.t0)
BEGIN
  INSERT INTO bias_fallback_log
  SELECT NEW.market_id, NEW.t0, cp.version, cp.applies_to_utc
  FROM calibration_params cp
  WHERE cp.version <> 'identity-v0' AND cp.applies_to_utc <= NEW.t0
  ORDER BY cp.applies_to_utc DESC LIMIT 1;
END;

-- C4: sumas ponderadas (w = 1 / p_incl_triage; 1 si es NULL)
ALTER TABLE selection_members_agg ADD COLUMN sum_w           REAL;
ALTER TABLE selection_members_agg ADD COLUMN sum_w_horizon   REAL;
ALTER TABLE selection_members_agg ADD COLUMN sumsq_w_horizon REAL;
ALTER TABLE selection_members_agg ADD COLUMN sum_w_absmid    REAL;
ALTER TABLE selection_members_agg ADD COLUMN sumsq_w_absmid  REAL;
ALTER TABLE selection_members_agg ADD COLUMN sum_w_logvol    REAL;
ALTER TABLE selection_members_agg ADD COLUMN sumsq_w_logvol  REAL;

-- C6: VERIFICADO exige excerpt_found = 1
CREATE TRIGGER trg_ae_verified_needs_excerpt BEFORE INSERT ON analysis_evidence
WHEN NEW.label = 'VERIFICADO'
 AND COALESCE((SELECT excerpt_found FROM evidence e WHERE e.evidence_id = NEW.evidence_id), 0) = 0
BEGIN SELECT RAISE(ABORT, 'C6: VERIFICADO requires excerpt_found = 1'); END;
```

### Migración 0005 (v1.4.0)

0005 hace contigua la cadena de versiones de sesgo y añade la base terminal de t\_clv. VERIFICADO con `sqlite3` 3.53.1 de Python sobre 0001–0005, con el protocolo de abajo: los 14 casos de prueba dan el resultado esperado y `PRAGMA foreign_key_check` sale vacío.

**Comprobación 1: reconstrucción de `positions` y FKs hijas.** En 0001–0004 no existen tablas `clv` ni `settlements`. `settle()` escribe en `positions`, y ninguna tabla tiene una FK hacia `positions`. VERIFICADO con un barrido de `pragma_foreign_key_list` sobre todas las tablas tras 0004: cero referencias.

Las FKs propias de `positions` (hacia `decisions` y `markets`) siguen activas tras la reconstrucción: un INSERT con un `decision_id` inexistente se rechaza. No se usa `legacy_alter_table`. Para que esto no dependa de la suerte, el migrador sigue este protocolo en toda migración:

1. `PRAGMA foreign_keys = OFF` fuera de transacción.
2. `BEGIN`, el script y `PRAGMA foreign_key_check`. Si devuelve filas, `ROLLBACK` y error.
3. `COMMIT` y `PRAGMA foreign_keys = ON`.

Un test del migrador falla si una migración reconstruye una tabla que tiene FKs hijas sin listarlas en su cabecera.

**Comprobación 2: base terminal de t\_clv.** La cadena completa es:

1. t\_clv = max(t\_entrada + 6 h, min(t\_entrada + 7 d, end\_date − 24 h)), con `clv_basis = 'standard'`.
2. Si el mercado resolvió antes: t\_clv' = resolved\_at − 24 h (`early_24h`), válido si ≥ t\_entrada + 6 h.
3. Si no es válido: t\_clv'' = resolved\_at − 1 h (`terminal_1h`), válido si > t\_entrada.
4. Si tampoco: `unmeasurable`, fuera de M5 y contado aparte.

Los picks `terminal_1h` entran en M5, y el informe muestra su fracción. Si supera el 10%, se marca la lectura de P4 como contaminada por información cercana a la resolución.

**Comprobación 3: contigüidad de `calibration_params`.**

- Hay exactamente una versión abierta (`applies_to_utc` NULL), garantizado por un índice único parcial.
- Cada alta debe ser abierta y empezar después del inicio de la versión abierta. El mismo trigger cierra la anterior con `applies_to_utc = applies_from_utc` de la nueva.
- El único UPDATE permitido es ese cierre, de NULL a valor, sin tocar nada más.
- Un alta no puede empezar antes del t0 de un forecast ya guardado: así nunca reasigna forecasts existentes.
- `identity-v0` pasa a ser el primer eslabón, abierto hasta la primera versión ajustada.

Solapes y huecos son imposibles por construcción. Si el corte mensual se retrasa, sigue aplicando la última versión ajustada, nunca la identidad. Eso deja obsoletos el trigger de solapes, el registro `bias_fallback_log` y la alerta de 0004. La alerta diaria pasa a ser: versión abierta con `applies_from_utc` hace más de 35 días.

```sql
-- 0005: spec 1.4.0 (contigüidad de calibration_params; t_clv terminal)
-- Se ejecuta con el protocolo de migración de 1.4.0 (foreign_keys=OFF fuera de transacción + foreign_key_check).

-- Contigüidad: exactamente una versión abierta (applies_to_utc NULL); cada alta cierra la anterior
DROP TRIGGER trg_calib_noupdate;          -- 0004: inmutable total; se sustituye por "solo cierre"
DROP TRIGGER trg_calib_no_overlap;        -- 0004: el solape queda imposible por construcción
DROP TRIGGER trg_forecasts_bias_fallback; -- 0004: la caída a identidad queda imposible tras la primera versión ajustada
DROP TABLE bias_fallback_log;
UPDATE calibration_params SET applies_to_utc = NULL
 WHERE version = 'identity-v0'
   AND NOT EXISTS (SELECT 1 FROM calibration_params WHERE version <> 'identity-v0');
CREATE UNIQUE INDEX ux_calib_single_open ON calibration_params ((1)) WHERE applies_to_utc IS NULL;

CREATE TRIGGER trg_calib_close_only BEFORE UPDATE ON calibration_params
WHEN NOT (OLD.applies_to_utc IS NULL AND NEW.applies_to_utc IS NOT NULL
      AND NEW.version IS OLD.version AND NEW.fitted_at IS OLD.fitted_at AND NEW.n_train IS OLD.n_train
      AND NEW.shrink_w IS OLD.shrink_w AND NEW.platt_a IS OLD.platt_a AND NEW.platt_b IS OLD.platt_b
      AND NEW.bucket_table_json IS OLD.bucket_table_json AND NEW.oos_delta_brier IS OLD.oos_delta_brier
      AND NEW.active IS OLD.active AND NEW.fit_from_utc IS OLD.fit_from_utc AND NEW.cutoff_utc IS OLD.cutoff_utc
      AND NEW.applies_from_utc IS OLD.applies_from_utc AND NEW.n_cells_ok IS OLD.n_cells_ok
      AND NEW.n_cells_pooled IS OLD.n_cells_pooled AND NEW.n_cells_identity IS OLD.n_cells_identity)
BEGIN SELECT RAISE(ABORT, 'calibration_params: only closing the open version is allowed'); END;

CREATE TRIGGER trg_calib_append BEFORE INSERT ON calibration_params
BEGIN
  SELECT RAISE(ABORT, 'contiguity: new version must be open (applies_to_utc NULL)')
   WHERE NEW.applies_to_utc IS NOT NULL;
  SELECT RAISE(ABORT, 'contiguity: applies_from must be after the open version start')
   WHERE NEW.applies_from_utc <= (SELECT applies_from_utc FROM calibration_params WHERE applies_to_utc IS NULL);
  SELECT RAISE(ABORT, 'contiguity: would reassign existing forecasts')
   WHERE EXISTS (SELECT 1 FROM forecasts f WHERE f.t0 >= NEW.applies_from_utc);
  UPDATE calibration_params SET applies_to_utc = NEW.applies_from_utc WHERE applies_to_utc IS NULL;
END;

-- El trigger de forecasts admite la versión abierta (applies_to_utc NULL)
DROP TRIGGER trg_forecasts_v12_required;
CREATE TRIGGER trg_forecasts_v14_required BEFORE INSERT ON forecasts
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL OR NEW.bias_version IS NULL
  OR NEW.t_evidence > NEW.t0
  OR NEW.category NOT IN ('a','b','c','d')
  OR NOT EXISTS (SELECT 1 FROM calibration_params cp
                 WHERE cp.version = NEW.bias_version
                   AND NEW.t0 >= cp.applies_from_utc
                   AND NEW.t0 < COALESCE(cp.applies_to_utc, '9999-12-31T23:59:59Z'))
BEGIN SELECT RAISE(ABORT, 'forecast invariant violated (D4/D5/D6/M4/1.4)'); END;

-- t_clv terminal: base de medición y suelo de 6 h solo para las bases standard y early_24h
ALTER TABLE positions    ADD COLUMN clv_basis TEXT CHECK (clv_basis IN ('standard','early_24h','terminal_1h'));
ALTER TABLE shadow_picks ADD COLUMN clv_basis TEXT CHECK (clv_basis IN ('standard','early_24h','terminal_1h'));
DROP TRIGGER trg_positions_clv_after_entry;
CREATE TRIGGER trg_positions_clv_v14 BEFORE UPDATE OF t_clv, clv_status, clv_basis ON positions
WHEN NEW.clv_status = 'measured' AND (
      NEW.t_clv IS NULL OR NEW.clv_basis IS NULL
   OR julianday(NEW.t_clv) <= julianday(NEW.opened_at)
   OR (NEW.clv_basis IN ('standard','early_24h') AND (julianday(NEW.t_clv) - julianday(NEW.opened_at)) * 24 < 6))
BEGIN SELECT RAISE(ABORT, 't_clv rule violated (1.4)'); END;
```

## (d) JSON Schema del objeto `analysis`

El schema es JSON Schema 2020-12. VERIFICADO con `jsonschema` 4.26: es válido y rechaza tres casos de prueba. Uno, un ajuste ESPECULACION con delta distinto de 0. Dos, una contra-búsqueda vacía sin motivo de al menos 20 caracteres. Tres, un PICK con filtros fallidos.

La coherencia aritmética entre campos no se puede expresar en JSON Schema, así que la comprueba el validador pydantic (`model_validator`) con tolerancia 1e-6:

Cambios de la 1.1.0 en el schema, VERIFICADOS con `jsonschema` 4.26 (el patrón acepta F1–F10 y rechaza F0 y F11):

- `schema_version` pasa a 1.1.0.
- `market_implied` añade `t_evidence` y `mid_t_evidence` (D4).
- `outside_view` añade `class_sha` y `level` (D2).
- `filters_failed` usa `^F(10|[1-9])$` (M1).
- `market.category` sigue siendo a–d; la coherencia con `markets.category` la cubre la invariante D6.

* `p_model = sigmoid(logit_base + sum_delta_logit)`
* `p_final = sigmoid(w·logit(p_model) + (1−w)·logit(p_implied_debiased))`
* `sum_delta_logit = Σ adjustments.delta_logit`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "pmsys/analysis/v1",
  "title": "analysis",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version","analysis_id","market","rules","market_implied","outside_view","evidence","contra_search","adjustments","red_team","estimate","decision","meta"],
  "$defs": {
    "prob": {"type": "number", "minimum": 0, "maximum": 1},
    "ts": {"type": "string", "format": "date-time", "pattern": "(Z|[+-]00:00)$"},
    "label": {"enum": ["VERIFICADO","INFERIDO","ESPECULACION","SIN_VERIFICAR"]},
    "evidence_ref": {"type": "string", "pattern": "^[a-f0-9]{64}$"}
  },
  "properties": {
    "schema_version": {"const": "1.1.0"},
    "analysis_id": {"type": "string", "minLength": 1},
    "market": {
      "type": "object", "additionalProperties": false,
      "required": ["market_id","question","category","end_date_utc","horizon_days"],
      "properties": {
        "market_id": {"type": "string"},
        "question": {"type": "string"},
        "category": {"enum": ["a","b","c","d"]},
        "end_date_utc": {"$ref": "#/$defs/ts"},
        "horizon_days": {"type": "number", "minimum": 0}
      }
    },
    "rules": {
      "type": "object", "additionalProperties": false,
      "required": ["rules_sha","ambiguity_score","ambiguity_reasons","void_conditions"],
      "properties": {
        "rules_sha": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "ambiguity_score": {"type": "integer", "minimum": 0, "maximum": 10},
        "ambiguity_reasons": {"type": "array", "items": {"type": "object", "additionalProperties": false,
          "required": ["code","points","quote"],
          "properties": {"code": {"type": "string"}, "points": {"type": "integer", "minimum": 1, "maximum": 2}, "quote": {"type": "string"}}}},
        "void_conditions": {"type": "array", "items": {"type": "string"}}
      }
    },
    "market_implied": {
      "type": "object", "additionalProperties": false,
      "required": ["t0","t_evidence","mid_t_evidence","best_bid","best_ask","mid","spread","depth_usd_2ticks","p_implied","p_implied_debiased","what_price_discounts","why_could_be_wrong"],
      "properties": {
        "t0": {"$ref": "#/$defs/ts"}, "t_evidence": {"$ref": "#/$defs/ts"}, "mid_t_evidence": {"$ref": "#/$defs/prob"},
        "best_bid": {"$ref": "#/$defs/prob"}, "best_ask": {"$ref": "#/$defs/prob"},
        "mid": {"$ref": "#/$defs/prob"}, "spread": {"type": "number", "minimum": 0},
        "depth_usd_2ticks": {"type": "number", "minimum": 0},
        "p_implied": {"$ref": "#/$defs/prob"}, "p_implied_debiased": {"$ref": "#/$defs/prob"},
        "what_price_discounts": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "why_could_be_wrong": {"type": "array", "minItems": 1, "items": {"type": "string"}}
      }
    },
    "outside_view": {
      "type": "object", "additionalProperties": false,
      "required": ["ref_class","class_sha","level","k","n","base_rate","ci95","source","citations"],
      "properties": {
        "ref_class": {"type": "string"}, "class_sha": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "level": {"type": "integer", "minimum": 0, "maximum": 4},
        "k": {"type": "integer", "minimum": 0}, "n": {"type": "integer", "minimum": 20},
        "base_rate": {"$ref": "#/$defs/prob"},
        "ci95": {"type": "array", "prefixItems": [{"$ref": "#/$defs/prob"}, {"$ref": "#/$defs/prob"}], "minItems": 2, "maxItems": 2},
        "source": {"enum": ["polymarket_resolved","external"]},
        "citations": {"type": "array", "items": {"$ref": "#/$defs/evidence_ref"}}
      }
    },
    "evidence": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["evidence_id","url","published_at","retrieved_at","excerpt","tier","stance","label","excerpt_found"],
        "properties": {
          "evidence_id": {"$ref": "#/$defs/evidence_ref"},
          "url": {"type": "string", "format": "uri"},
          "published_at": {"anyOf": [{"$ref": "#/$defs/ts"}, {"type": "null"}]},
          "retrieved_at": {"$ref": "#/$defs/ts"},
          "excerpt": {"type": "string", "minLength": 1, "maxLength": 300},
          "tier": {"enum": ["A","B","C"]},
          "stance": {"enum": ["pro_yes","pro_no","neutral"]},
          "label": {"$ref": "#/$defs/label"},
          "excerpt_found": {"type": "boolean"}
        }
      }
    },
    "contra_search": {
      "type": "object", "additionalProperties": false,
      "required": ["queries","found","absent_reason"],
      "properties": {
        "queries": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "found": {"type": "boolean"},
        "absent_reason": {"type": ["string","null"]}
      },
      "if": {"properties": {"found": {"const": false}}},
      "then": {"properties": {"absent_reason": {"type": "string", "minLength": 20}}}
    },
    "adjustments": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["reason","delta_logit","evidence_ids","label"],
        "properties": {
          "reason": {"type": "string"},
          "delta_logit": {"type": "number", "minimum": -1.5, "maximum": 1.5},
          "evidence_ids": {"type": "array", "items": {"$ref": "#/$defs/evidence_ref"}},
          "label": {"enum": ["VERIFICADO","INFERIDO","ESPECULACION"]}
        },
        "allOf": [
          {"if": {"properties": {"label": {"const": "ESPECULACION"}}}, "then": {"properties": {"delta_logit": {"const": 0}}}},
          {"if": {"properties": {"label": {"const": "VERIFICADO"}}}, "then": {"properties": {"evidence_ids": {"minItems": 1}}}}
        ]
      }
    },
    "red_team": {
      "type": "object", "additionalProperties": false,
      "required": ["case_market_right","case_market_wrong","falsifiers"],
      "properties": {
        "case_market_right": {"type": "string", "minLength": 1},
        "case_market_wrong": {"type": "string", "minLength": 1},
        "falsifiers": {"type": "array", "minItems": 1, "items": {
          "type": "object", "additionalProperties": false,
          "required": ["observable","by_date","direction","delta_logit"],
          "properties": {
            "observable": {"type": "string"},
            "by_date": {"type": "string", "format": "date"},
            "direction": {"enum": ["toward_yes","toward_no"]},
            "delta_logit": {"type": "number"}
          }}}
      }
    },
    "estimate": {
      "type": "object", "additionalProperties": false,
      "required": ["logit_base","sum_delta_logit","p_model","shrink_w","p_final","arithmetic"],
      "properties": {
        "logit_base": {"type": "number"},
        "sum_delta_logit": {"type": "number", "minimum": -1.5, "maximum": 1.5},
        "p_model": {"$ref": "#/$defs/prob"},
        "shrink_w": {"$ref": "#/$defs/prob"},
        "p_final": {"$ref": "#/$defs/prob"},
        "arithmetic": {"type": "array", "minItems": 3, "items": {"type": "string"}}
      }
    },
    "decision": {
      "type": "object", "additionalProperties": false,
      "required": ["verdict","side","edge_net","filters_failed","sizing_outcome","stake_usd"],
      "properties": {
        "verdict": {"enum": ["PICK_YES","PICK_NO","NO_TRADE","INSUFFICIENT_EVIDENCE"]},
        "side": {"enum": ["YES","NO",null]},
        "edge_net": {"type": ["number","null"]},
        "filters_failed": {"type": "array", "items": {"pattern": "^F(10|[1-9])$"}},
        "sizing_outcome": {"enum": ["SIZED","NO_TRADE_FILTER","NO_TRADE_SIZE","NO_TRADE_CAP","NO_TRADE_STOP"]},
        "stake_usd": {"type": "number", "minimum": 0}
      },
      "if": {"properties": {"verdict": {"enum": ["PICK_YES","PICK_NO"]}}},
      "then": {"properties": {"filters_failed": {"maxItems": 0}, "sizing_outcome": {"const": "SIZED"}}}
    },
    "meta": {
      "type": "object", "additionalProperties": false,
      "required": ["rules_version","revision","prompt_shas","models","cost_usd","created_at"],
      "properties": {
        "rules_version": {"type": "string"},
        "revision": {"type": "integer", "minimum": 0, "maximum": 3},
        "prompt_shas": {"type": "object", "additionalProperties": {"type": "string"}},
        "models": {"type": "object", "additionalProperties": {"type": "string"}},
        "cost_usd": {"type": "number", "minimum": 0},
        "created_at": {"$ref": "#/$defs/ts"}
      }
    }
  }
}
```

## (e) Fuentes

Las 8 fuentes son gratuitas. Todas las cuotas de la columna "Límite" se respetan al 50% con token bucket. La latencia es la del sistema, no la de la fuente: la fuente se consulta una vez por ciclo de 12 h.

| Fuente | Uso | Cobertura | Latencia efectiva | Límite (estado) | Fiabilidad | Coste |
| --- | --- | --- | --- | --- | --- | --- |
| [Gamma API](https://docs.polymarket.com/api-reference/rate-limits.md) `gamma-api.polymarket.com` | Mercados, reglas, endDate, estado UMA, resultado | Todos los mercados de Polymarket internacional | ≤ 12 h | General 4,000 req/10 s; `/markets` 300 req/10 s (VERIFICADO) | Tier A para metadatos. Fuentes secundarias reportan campos `null` en mercados cerrados (SIN VERIFICAR) | 0 |
| CLOB API `clob.polymarket.com` | `/book`, `/prices-history`, `/clob-markets/{condition_id}` (mos, mts, fd) | Todos los tokens con order book | Libro: tiempo real en t0. Historial: `fidelity` en minutos ([ref](https://docs.polymarket.com/developers/CLOB/timeseries.md)) | Según tabla oficial por endpoint; general 15,000 req/10 s (VERIFICADO) | Tier A. Migró a CLOB V2 en abril de 2026 ([changelog](https://docs.polymarket.com/changelog.md)): riesgo de cambio de esquema | 0 |
| Geoblock `polymarket.com/api/geoblock` | Jurisdicción antes de cada pick en vivo | IP del VPS | Por pick | No publicado (SIN VERIFICAR) | Tier A | 0 |
| GDELT DOC 2.0 `api.gdeltproject.org/api/v2/doc/doc` | Descubrir noticias: URL, fecha, idioma, país | \~65 idiomas, ventana móvil de 3 meses, actualización \~15 min | ≤ 12 h | 1 req/5 s; responde 429 si se excede (fuente secundaria) | Tier B como índice. El texto de la noticia hereda el tier de su medio | 0 |
| FRED `api.stlouisfed.org` | Series macro (d): inflación, empleo, tasas | Series oficiales de EE. UU. | Según calendario de publicación | 120 req/min por clave (fuentes secundarias). Una fuente menciona 6,000/día (SIN VERIFICAR) | Tier A | 0 (clave gratuita) |
| [CourtListener](https://wiki.free.law/c/courtlistener/help/api/rest/v4/overview) v4 | Litigios en mercados de política (b) | Tribunales de EE. UU. | ≤ 12 h | 5/min, 50/h, 125/día por cuenta autenticada (VERIFICADO) | Tier A | 0 |
| RSS oficiales (allowlist en `sources.toml`) | Comunicados de gobiernos, bancos centrales y órganos electorales | Lo que liste la allowlist | ≤ 12 h | Por feed | Tier A | 0 |
| Descarga directa de URL (`evidence/fetch.py`) | Texto para verificar que el excerpt existe | URL de GDELT y RSS | En el ciclo | 1 req/2 s por dominio, respeta robots.txt | Hereda el tier del dominio | 0 |

Tiers (fijos, no se infieren por LLM):

- **A**: fuente primaria u oficial. Puede sostener un ajuste VERIFICADO por sí sola.
- **B**: agencia o medio con correcciones públicas. Hacen falta 2 fuentes B independientes para un ajuste VERIFICADO.
- **C**: el resto. Solo puede producir INFERIDO o ESPECULACION.

La allowlist de RSS empieza vacía. Ningún feed entra sin URL comprobada (R12); la primera tanda la propones tú en Fase 2.

## (f) Plan de evaluación

Se promociona a vivo solo si se cumplen P1–P7 a la vez sobre los forecasts congelados. Se puntúa cada mercado analizado, opere o no, porque "no operar" también emite p\_final.

**Regla anti-fuga.** No hay backtest con LLM sobre mercados ya resueltos. Los modelos conocen hechos hasta su fecha de corte, así que cualquier backtest histórico con LLM está contaminado (INFERIDO). Solo cuenta el pronóstico hacia delante, con `forecasts.t0` anterior a la resolución. Los backtests sin LLM (sesgo del precio por bucket) sí son válidos.

**Volumen necesario.** INFERIDO: con horizontes uniformes de 2 a 90 días, \~75% de los forecasts emitidos en 6 meses resuelven dentro de la ventana. Para 200 resueltos hacen falta ≥ 270 forecasts. Objetivo operativo (1.4.0): 75 forecasts nuevos por mes. Meses 1–3: las 4 categorías, ≥ 10 por categoría. Desde el mes 4: solo las 2 categorías activas según la regla de concentración de abajo, ≥ 25 por categoría. INFERIDO: 200 resueltos llegan hacia el mes 4–5.

### Métricas

| ID | Métrica | Definición | Rol |
| --- | --- | --- | --- |
| M1 | ΔBrier pareado vs mid\_t0 | media\[(p\_final − y)² − (mid\_t0 − y)²\]; VOID excluido | Primaria: es el precio contra el que se opera |
| M1b | ΔBrier pareado vs mid\_t\_evidence | media\[(p\_final − y)² − (mid\_t\_evidence − y)²\]; VOID excluido | Diagnóstico obligatorio en el mismo informe que M1 (D4) |
| M2 | ΔBrier vs cierre | Como M1, con el precio de cierre en lugar de mid\_t0 | Informativa (T1) |
| M3 | Log loss | p recortada a \[0.01, 0.99\] | Informativa |
| M4 | Calibración | 10 buckets de ancho 0.1; ECE ponderado; pendiente e intercepto de la regresión logística y \~ logit(p\_final) | Gate |
| M5 | CLV a horizonte fijo | Por pick SIZED: mid del lado en t\_clv − coste de entrada por acción (VWAP + comisión), con t\_clv = max(t\_entrada + 6 h, min(t\_entrada + 7 d, end\_date − 24 h)) (C2). Como F3 se evalúa en t\_entrada, end\_date − 24 h ≥ t\_entrada + 24 h, así que la cota inferior solo actúa ante datos anómalos. Si el mercado resolvió antes de t\_clv, se usa t\_clv' = resolved\_at − 24 h. Si t\_clv' < t\_entrada + 6 h, se usa la base terminal t\_clv'' = resolved\_at − 1 h (`clv_basis = 'terminal_1h'`, reportada aparte). Si t\_clv'' ≤ t\_entrada, el pick queda `clv_status = 'unmeasurable'`, no tiene M5 y su tasa se reporta. Un trigger de 0005 exige t\_clv > t\_entrada y, salvo con base terminal, t\_clv ≥ t\_entrada + 6 h. Media y % positivo | Gate (P4) e indicador adelantado |
| M6 | P&L papel | Neto de comisión y VWAP; ROI; drawdown máximo | Gate |
| M7 | Cobertura | % de análisis que acaban en pick; % INSUFFICIENT\_EVIDENCE; tasa de VOID por categoría (VOID / resueltos de la categoría) | Diagnóstico |
| M8 | Coste | USD de LLM por forecast puntuado | Gate |
| M9 | Atribución | M1 por categoría, por horizonte (2–14, 15–45, 46–90 d) y con y sin ajustes LLM (p\_model frente a p\_implied\_debiased) | Diagnóstico |
| M10 | CLV sombra | M5 calculado sobre decisiones NO\_TRADE\_SIZE, con el coste del tamaño mínimo de orden (tabla `shadow_picks`) | **Indicador, no gate.** No entra en P1–P7 ni en la regla del mes 3 |

### Umbrales de promoción a Fase 6a

| ID | Condición | Umbral |
| --- | --- | --- |
| P1 | Forecasts resueltos puntuables | n ≥ 200 |
| P2 | M1 agregado | Límite superior del IC 95% unilateral (bootstrap pareado, 10,000 réplicas, semilla fija) < 0 |
| P3 | Calibración | ECE ≤ 0.05 (buckets con n ≥ 10); pendiente en \[0.8, 1.2\]; \|intercepto\| ≤ 0.2 |
| P4 | CLV de picks (M5) | n\_picks SIZED con M5 medible ≥ 15, contando cada mercado una sola vez y con el registro vivo si existe (vista `v_p4_picks`, C9); CLV medio > 0 con límite inferior del IC 90% unilateral (t de Student) > 0 |
| P5 | P&L papel | P&L neto ≥ 0; drawdown pico a valle ≤ 15% dentro de los últimos 3 meses del periodo evaluado; drawdown del periodo completo ≤ 30% (B2) |
| P6 | Operación | ≥ 95% de ciclos completados; 0 violaciones de `idem_key`; gasto LLM ≤ cap\_mensual (30 USD) en cada mes |
| P7 | Atribución | M1 de p\_final < M1 de p\_implied\_debiased solo. Si no, el LLM no añade valor y se promociona solo el modelo sin LLM |

**Fase 6a → 6b**: 2 órdenes manuales ejecutadas, con slippage medido ≤ 1 tick frente al VWAP previsto y comisión real igual a la calculada (± 0.001 por acción).

**Picks de 6a y P4 (1.2/M2).** Las órdenes de 6a no cuentan para P4 ni para la reevaluación de P4 en 6b-C. Cada orden de 6a sale de una decisión que ya existe como pick de papel y cuenta una sola vez, como pick de papel; el fill de 6a no añade una observación. Motivo: su tamaño está forzado al mínimo fuera de Kelly, y n = 2 no aporta potencia. Su CLV se registra solo para validar la ejecución.

**Bankroll de 6a y 6b (1.2/M3).**

| Opción | Capital total comprometido | Consecuencia | Recomendación |
| --- | --- | --- | --- |
| A. Secuencial sobre el mismo bankroll de 50 USDC, con ledger contable separado | 50 USDC | 6a usa 5 USDC de la misma wallet con su propio ledger (`live_6a`) y su propia serie de equity. Al empezar 6b, la wallet se repone a 50 USDC (se cubren las pérdidas de 6a y se retiran sus ganancias) y la serie `live_6b` arranca con pico = 50 | **Adoptar** |
| B. Bote separado: 5 USDC para 6a + 50 USDC para 6b | 55 USDC | Supera el bankroll objetivo de 50 que fijaste | Rechazar |
| C. Secuencial sin reposición | 50 USDC | Las órdenes de tamaño forzado de 6a contaminan el pico y el stop de 6b | Rechazar |

**Selección de categorías para vivo (T3)**: M1 por categoría contraído hacia el agregado (Bayes empírico normal-normal). Se eligen las 1–2 categorías con n ≥ 40, M1 contraído < 0 y CLV medio > 0. Etiqueta obligatoria en el informe: INFERIDO (potencia \~0.3 con n ≈ 50).

**Fallo**: si al mes 9 no se cumple P2, el veredicto es "sin ventaja demostrada". No se promociona y no se relajan umbrales a posteriori.

### Veredicto si P2 pasa y P4 falla por potencia (B1)

Veredicto: **promoción condicionada a 6b (6b-C)**, después de 6a. Aplica solo si el fallo de P4 es por potencia y no por señal.

- **Fallo por potencia**: P1, P2, P3, P5, P6 y P7 pasan, y P4 falla porque n\_picks < 15, o porque con n ≥ 15 el CLV medio es > 0 pero el límite inferior del IC 90% es ≤ 0.
- **Fallo por señal**: n ≥ 15 y CLV medio ≤ 0. Veredicto: "sin ventaja ejecutable". No hay promoción y el papel continúa.

| Opción | Consecuencia | Coste y riesgo | Recomendación |
| --- | --- | --- | --- |
| (a) Promoción condicionada a 6b-C, con capital en riesgo reducido y M10 como vigilancia | Genera muestra de CLV real sin esperar meses de papel | Pérdida máxima acotada a la exposición de 6b-C (12.5 USDC) | **Adoptar** |
| (b) Cierre limpio | Descarta un edge demostrado en P2, el criterio de éxito que definiste | 0 | Rechazar |
| (c) Prórroga con gate solo de P4 | Con tasa de pick del 2% hacen falta 15 meses para n = 15 (tabla de potencia); puede no tener final | 13.65–25 USD de LLM por mes adicional: más que lo que arriesga (a) | Rechazar |

Justificación: el fallo de P4 por potencia es estructural, no evidencia contra el edge. El valor principal de 6b-C es la parada temprana con riesgo acotado: comprueba en vivo, con 12.5 USDC expuestos como máximo, que el CLV no es negativo. No es una vía probable de promoción. Con n = 15, la potencia de P4 es 0.37 (μ = +0.02), así que el desenlace más probable de 6b-C es la vuelta a papel. Es preferible a (b) porque prueba la ejecución real del edge, y a (c) porque cuesta menos que esperar.

**Reglas de 6b-C:**

1. **Capital en riesgo.** Exposición abierta total ≤ 25% de B (12.5 USDC), cap por posición 5% de B (2.5 USDC), máximo 4 posiciones. Kelly 1/4 se calcula sobre B = 50, no sobre el capital reducido, para no multiplicar los NO\_TRADE\_SIZE.
2. **Vigilancia.** M5 de los picks de 6b-C y M10. M10 solo puede abrir una revisión manual (media < 0 con n ≥ 15); nunca promociona ni degrada.
3. **Parada temprana (válvula de seguridad, no gate).** Si el CLV medio de los primeros 8 picks de 6b-C es < −0.03, se vuelve a papel (umbral justificado más abajo).
4. **Reevaluación de P4.** Se hace al acumular 15 picks con M5 (papel + 6b-C, sin 6a por 1.2/M2, con cada mercado una sola vez y el registro vivo si existe por C9) o a los 6 meses, lo que ocurra antes:
   - P4 pasa: 6b pleno.
   - Falla por señal: vuelta a papel.
   - Sigue sin potencia a los 6 meses: vuelta a papel con veredicto "edge de forecast sin ventaja ejecutable demostrada".
5. Durante 6b-C siguen vigentes el stop del 15% y los filtros F1–F10.

**Umbral de la parada temprana.** Se recalibró en la 1.3.0 a partir de una observación de la revisión. INFERIDO, con σ del CLV = 0.08 y aproximación normal. A 1–2.5 picks vivos por mes, 8 picks tardan 3–8 meses y 12 picks 5–12 meses.

| Regla | Falso aborto si μ = 0 | Falso aborto si μ = +0.02 | Detección si μ = −0.03 | Recomendación |
| --- | --- | --- | --- | --- |
| 8 picks, < −0.02 (1.2.0) | 0.24 | 0.08 | 0.64 | Rechazar: falso aborto alto |
| 12 picks, < −0.02 | 0.19 | 0.04 | 0.67 | Rechazar: suele llegar después de la ventana de 6 meses de 6b-C |
| 8 picks, < −0.03 | 0.14 | 0.04 | 0.50 | **Adoptar** |
| 12 picks, < −0.03 | 0.10 | 0.02 | 0.50 | Rechazar: igual de lenta que la de 12 picks y −0.02 |

La detección del caso dañino baja de 0.64 a 0.50. Es aceptable porque el stop del 15% y la reevaluación de P4 siguen activos. Es una válvula de seguridad, no un gate: con 1–2.5 picks vivos al mes, 8 picks tardan 3–8 meses, así que lo más probable es que no se dispare dentro de la ventana de 6 meses de 6b-C.

### P5 y drawdown (B2)

P5 pasa si se cumplen las 3 condiciones:

1. P&L neto del periodo ≥ 0.
2. Drawdown pico a valle ≤ 15% dentro de los últimos 3 meses naturales del periodo evaluado (pico y valle calculados solo en esa ventana).
3. Drawdown del periodo completo ≤ 30%, como techo de catástrofe.

**Mínimo de picks en la ventana de P5.** Con pocos picks, la condición 2 es casi trivial: con 22 picks en 9 meses, la ventana de 3 meses tiene \~7. Eso hace que el gate sea más duro cuanto mejor funciona el sistema.

| Opción | Efecto | Recomendación |
| --- | --- | --- |
| Solo documentar la asimetría | La condición 2 no discrimina a tasas de pick bajas | Rechazar |
| La ventana de la condición 2 se amplía hacia atrás hasta contener ≥ 10 picks; si el periodo entero tiene < 10, se usa el periodo entero | Misma exigencia mínima con cualquier tasa de pick | **Adoptar** |

**Techo de la ventana de P5 (1.4.0).** "Hasta 10 picks o el inicio del periodo, lo que sea más corto" es literalmente la regla de la 1.3.0, y a tasas muy bajas sigue llegando al inicio del periodo. Para que no se coma el periodo entero hace falta un techo temporal.

| Opción | A tasa de pick del 2% (\~1.5 picks/mes) | Recomendación |
| --- | --- | --- |
| Lectura literal (sin techo temporal) | La ventana cubre los 9 meses completos | Rechazar |
| Ampliar hasta 10 picks con techo de 6 meses. Si en 6 meses hay < 10 picks, la condición 2 se evalúa sobre esos 6 meses y el informe la marca "n < 10" | La ventana nunca supera 6 meses; los 3 primeros meses del periodo quedan fuera | **Adoptar** |

El stop real del 15% de la ejecución en vivo (h) no cambia; B2 solo redefine el gate de papel.

INFERIDO (simulación propia, 8,000–10,000 réplicas). Supuestos: picks secuenciales independientes; precio del lado uniforme entre 0.10 y 0.90; edge creído 0.06; Kelly 1/4 con cap del 10%; 22 y 45 picks (tasas de pick del 5% y 10% a 9 meses). Con edge real igual al creído, el drawdown supera el 15% en algún momento en el 25% de las trayectorias con 22 picks y en el 53% con 45.

Tasa de fallo de P5 (incluye P&L ≥ 0):

| Opción | Con edge real 0.06 (n = 22 / 45) | Sin edge (n = 22 / 45) | Recomendación |
| --- | --- | --- | --- |
| (a) Drawdown máximo del periodo ≤ 15% | 0.35 / 0.52 | 0.60 / 0.79 | Rechazar: el falso rechazo crece con la muestra |
| (b) Pico a valle ≤ 15% en los últimos 3 meses + techo del 30% en el periodo | 0.29 / 0.28 | 0.55 / 0.61 | **Adoptar** |
| (c) 15% con cláusula de recuperación al volver al pico + techo del 30% | 0.32 / 0.37 | 0.58 / 0.69 | Rechazar: depende de que la recuperación caiga antes del corte |

Justificación de (b): tiene el menor falso rechazo con edge real y la misma o mejor separación entre "con edge" y "sin edge" (0.26–0.33 frente a 0.25–0.27). El techo del 30% cubre el hueco de (b): una catástrofe temprana.

INFERIDO: el componente P&L ≥ 0 explica casi todo el fallo restante con edge real (\~0.28). No se cambia en la 1.2.0 porque está fuera de la lista; queda propuesto para la próxima revisión.

### Ciclo de vida tras la promoción (C10)

1. **El papel continúa siempre**, en paralelo con cualquier modo vivo, con la misma selección, cuota y scoring. M1, M1b y P1–P7 se siguen calculando sobre los forecasts de papel.
2. **Revisión trimestral.** `live_review` corre cada 3 meses desde el inicio de 6b o de 6b-C. En 6b-C, además, siguen vigentes sus reglas de B1. Se aplica la primera fila que se cumpla:

| # | Condición (n\_live = picks vivos acumulados desde la entrada en el modo, contados con `v_p4_picks`) | Resultado | Prob. de disparo con μ = +0.02 / μ = −0.03 |
| --- | --- | --- | --- |
| 1 | Stop del 15% | STOPPED | — |
| 2 | P2 sobre todos los forecasts acumulados falla (límite superior del IC 95% ≥ 0) | BACK\_TO\_PAPER | — |
| 3 | n\_live ≥ 8 y CLV medio < −0.03 | BACK\_TO\_PAPER | 0.04 / 0.50 (n = 8) |
| 4 | n\_live ≥ 15 y CLV medio ≤ 0 (P4 falla por señal) | BACK\_TO\_PAPER | 0.17 / 0.93 (n = 15) |
| 5 | M1 de los últimos 6 meses (n ≥ 100) con estimación puntual > 0 | 1.ª vez en 6b: DEGRADE\_TO\_6B\_C. 2.ª revisión seguida, o ya en 6b-C: BACK\_TO\_PAPER | — |
| 6 | En 6b-C: n\_live ≥ 15 y límite inferior del IC 90% > 0 | UPGRADE\_TO\_6B | 0.37 / — (n = 15) |
| 7 | n\_live < 8 | CONTINUE, marcada "sin decisión por potencia" | — |
| 8 | Ninguna de las anteriores, incluido P4 fallando por potencia en 6b | CONTINUE | — |

Regla precomprometida de la revisión trimestral (1.4.0), con la misma lógica de potencia que la parada temprana (σ = 0.08, aproximación normal). Un trimestre trae 3–7 picks vivos, por eso las reglas de CLV usan el acumulado desde la entrada en el modo y no el trimestre.

En 6b, que P4 falle por potencia ya no degrada (sí lo hacía en la 1.3.0): con potencia de 0.37–0.53, degradar por potencia produciría vaivenes entre modos sin evidencia en contra.

**Qué actúa en la revisión trimestral de 6b (1.4.1).** El único gate trimestral sobre la calidad del pronóstico es P2: filas 2 y 5. Las filas 3 y 4 son válvulas de seguridad sobre CLV negativo, con la misma lógica que la parada temprana, no el gate P4. En 6b, P4 es advisory: se calcula y se informa, pero que no se demuestre CLV > 0 (fallo por potencia) no produce ninguna acción. P4 solo actúa como gate en dos sitios: la promoción inicial (`promotion_check`) y la subida de 6b-C a 6b (fila 6).

3. **Al cambiar de modo**, las posiciones abiertas se mantienen hasta vencimiento con los caps del modo en que se abrieron. Las nuevas usan los caps del modo nuevo.
4. **Volver a vivo tras BACK\_TO\_PAPER** exige un `promotion_check` completo sobre forecasts con t0 posterior a la vuelta, con al menos 3 meses de datos.
5. La revisión de categorías a 6b + 3 meses (1.2/M8) se hace en la primera revisión trimestral.

### Potencia de P4 (D1)

Con una tasa de pick del 2%, P4 es inalcanzable incluso a 9 meses. Con 5% se alcanza n = 15 en el mes 6, pero con potencia ≤ 0.72. P4 sigue siendo un gate exigente; no se relaja más.

Supuestos (INFERIDO):

- 50 forecasts por mes.
- σ del CLV a 7 días = 0.08 por acción.
- Test t unilateral con α = 0.10, equivalente a pedir límite inferior del IC 90% > 0. La potencia sale de la t no central.
- n\_picks = floor(tasa × 50 × meses). Se ignoran los picks de los últimos 7 días, que aún no tienen M5.

Cada celda da n\_picks y potencia (μ = +0.02 / μ = +0.04 de CLV medio verdadero).

| Tasa de pick | Forecasts/mes | Mes 3 | Mes 6 | Mes 9 |
| --- | --- | --- | --- | --- |
| 2% | 50 | n = 3 · 0.18 / 0.28 | n = 6 · 0.24 / 0.44 | n = 9 · 0.28 / 0.56 (n < 15: P4 imposible) |
| 5% | 50 | n = 7 · 0.25 / 0.48 | n = 15 · 0.37 / 0.72 | n = 22 · 0.45 / 0.85 |
| 10% | 50 | n = 15 · 0.37 / 0.72 | n = 30 · 0.53 / 0.92 | n = 45 · 0.65 / 0.98 |

M10 (CLV sombra) aumenta la muestra para lectura temprana, pero no cuenta para P4.

**Con 75 forecasts/mes (1.4.0).** Mismos supuestos; cada celda da n\_picks y potencia (μ = +0.02 / μ = +0.04).

| Tasa de pick | Mes 3 | Mes 6 | Mes 9 |
| --- | --- | --- | --- |
| 2% | n = 4 · 0.20 / 0.34 | n = 9 · 0.28 / 0.56 | n = 13 · 0.34 / 0.68 (n < 15: P4 imposible) |
| 5% | n = 11 · 0.31 / 0.62 | n = 22 · 0.45 / 0.85 | n = 33 · 0.55 / 0.94 |
| 10% | n = 22 · 0.45 / 0.85 | n = 45 · 0.65 / 0.98 | n = 67 · 0.77 / 1.00 |

### Regla precomprometida del mes 3 (D1)

La tasa de pick se mide una sola vez, el día 1 del mes 4 a 00:00 UTC: picks SIZED en papel divididos entre forecasts emitidos en los meses 1–3. Si es < 3%, se aplica X una vez. No hay segunda iteración.

| Opción para X | Efecto sobre p\_final y M1/M1b | Riesgo | Recomendación |
| --- | --- | --- | --- |
| A. Bajar F4 de 0.05 a 0.03 de edge neto | Ninguno: solo cambia qué forecasts se convierten en pick; el scoring queda intacto | Picks de edge fino, aunque ya netos de comisión y VWAP | **Adoptar** |
| B. Subir w de 0.30 a 0.45 | Cambia p\_final a mitad de muestra: M1 mezcla dos modelos y pisa la recalibración mensual de w | Más ruido del LLM dentro de la probabilidad | Rechazar |
| C. Ampliar el horizonte de papel de 90 a 120 días | Cambia la composición de la muestra y reduce los resueltos dentro de la ventana | Picks fuera del máximo de 45 días en vivo: no representan lo que se operaría | Rechazar |

Al aplicar A:

1. Cambia `rules_version`.
2. Cada pick queda etiquetado con el régimen de F4 vigente.
3. P4 se evalúa sobre todos los picks y el informe los desglosa por régimen.
4. F4 nunca baja de 0.03.
5. Si en el mes 6 la tasa sigue < 3%, no hay más cambios: P4 se evalúa tal cual y su fallo se reporta como "sin potencia".

### Latencia: M1 frente a M1b (D4)

Es una regla precomprometida que se evalúa en cada informe mensual desde n ≥ 100 forecasts resueltos.

**Diagnóstico de latencia.** Se da si se cumple cualquiera de estas condiciones:

- M1b cumple el criterio de P2 (límite superior del IC 95% < 0) y M1 no lo cumple.
- M1 − M1b ≥ 0.003, con el límite inferior del IC 90% del diferencial pareado > 0.

Si M1 y M1b fallan a la vez, el problema no es la latencia y no se aplica X.

| Opción para X | Coste LLM/mes | Efecto | Recomendación |
| --- | --- | --- | --- |
| A. Pasar Sonnet y Opus de Batch a síncrono y decidir en el mismo ciclo; objetivo t0 − t\_evidence ≤ 2 h | +9.30 USD (13.65 → 22.95): cabe en el tope mensual de 25 y en el diario de 1.50 | Elimina el desfase de 1–2 ciclos | **Adoptar** |
| B. Acortar el ciclo a 6 h | +2.03 USD (triaje ×2); el batch sigue tardando hasta 24 h | Reduce poco el desfase | Rechazar |
| C. Usar mid\_t\_evidence como benchmark primario | 0 | Mide una ventaja que no se puede ejecutar | Rechazar |

Al aplicar A:

1. Cambia `rules_version`.
2. M1 y M1b se reportan por régimen.
3. X se aplica una sola vez.
4. Si el gasto real del mes siguiente supera 25 USD, `BudgetExceeded` solo actúa como último seguro, después de la escalera de recorte precomprometida de abajo. No se sube el tope.

**Escalera de recorte precomprometida (1.2/M1).** Desde el día 5 de cada mes se calcula a diario la proyección P = gasto\_del\_mes / días\_transcurridos × días\_del\_mes. Si P > cap\_mensual, se aplica el siguiente escalón. Entre escalones pasan al menos 3 días, para medir su efecto.

| Escalón | Acción | Ahorro estimado/mes con 75 forecasts | Efecto sobre el scoring |
| --- | --- | --- | --- |
| 1 | Pre-filtro a Opus: \|p\_model − mid\| pasa de ≥ 0.07 a ≥ 0.10 | ≈ 3–6 USD (INFERIDO; depende de la distribución de discrepancias) | Ninguno sobre la muestra; menos mercados con síntesis Opus |
| 2 | Red team y síntesis de Opus pasan a Sonnet síncrono | 7.20 USD (60 llamadas × 0.24 → × 0.12) | Cambia el modelo de síntesis; M1 y M1b se reportan por régimen |
| 3 | Cuota mensual de forecasts de 75 a 60 | ≈ 3.4–4.1 USD | Reduce la muestra y retrasa P1; último recurso |

Cada escalón cambia `rules_version` y queda en `system_state.budget_step`. Reversión (C7): al inicio de cada mes se revierte como mucho un escalón, el último aplicado, y solo si el gasto real del mes cerrado más el ahorro estimado de ese escalón cabe en el 90% del tope: gasto\_mes\_cerrado ≤ 0.9 × cap\_mensual − ahorro\_estimado\_del\_escalón (1.4.0). Con cap\_mensual = 30 equivale a gasto ≤ 27 − ahorro USD. `BudgetExceeded` sigue siendo el seguro final.

**Interacción de X con la escalera (C7).**

| Regla de reversión | Con X activo (coste base 22.95 USD) | Recomendación |
| --- | --- | --- |
| (A) Gasto del mes cerrado < 20 USD (1.2.0) | Nunca revierte: degradación permanente | Rechazar |
| (B) Gasto < 0.9 × coste base vigente (lo que pidió la revisión) | Umbral de 20.66 USD. Los escalones bajan el gasto justo por debajo de ese umbral, así que revierte y vuelve a escalar en meses alternos | Rechazar: oscila |
| (C) Gasto + ahorro estimado del último escalón ≤ 0.9 × cap\_mensual, un escalón por mes | Solo revierte si el escalón cabe. Con el tope de 25 de la 1.3.0 y gasto real ≈ 21 USD, el escalón 1 (ahorro ≈ 3) no revierte; los demás, cuando haya margen. No oscila por construcción | **Adoptar** |

(C) no es una fracción del coste base como pedía la revisión. La recomiendo igual porque (B) oscila y (C) incorpora el coste base a través del gasto real observado.

**Orden.**

1. X tiene prioridad: corrige el benchmark primario. Se activa con la regla mensual de latencia y la escalera nunca lo deshace.
2. La escalera actúa sobre el coste con X incluido.
3. Si con X activo y los 3 escalones aplicados la proyección sigue > cap\_mensual, corta `BudgetExceeded`. X sigue activo y la causa se reporta.
4. Activar X cuando ya hay escalones aplicados no los revierte; la reversión sigue la regla (C).

**Acoplamiento documentado (1.4.0).** Con X solo en a (22.84–26.33 USD) no se activa ningún escalón. Si la regla de latencia extiende X a todas las categorías (33.30 USD > 30), la escalera aplica el escalón 1 (≈ 3–6 USD). Solo si eso no basta, aplica también el 2 (7.20 USD).

Revertir cualquiera de los dos exige gasto ≤ 27 − ahorro: 21–24 USD para el 1 y 19.80 USD para el 2. Con X completo, el gasto real tras los escalones es ≈ 20–30 USD, así que los escalones aplicados quedan fijos mientras X completo siga activo. Si se llegó al escalón 2, Opus queda fuera de forma permanente.

Es el comportamiento esperado de la regla, no un fallo. El informe mensual lo muestra como "escalones fijos por X completo", para que nadie lo lea como una avería a mitad de 6b.

### Bucle de recalibración (mensual)

1. Ajustar `w` (shrinkage) y Platt (a, b) con validación temporal expandida: entrenar en meses 1..k y evaluar en k+1.
2. Activar la versión nueva de `calibration_params` solo si mejora el ΔBrier fuera de muestra en ≥ 0.002 y n\_train ≥ 100.
3. Recalcular la tabla de sesgo por bucket de `p_implied_debiased` con la regla de corte temporal de "Tabla de sesgo del precio (D5)" en (b): ajuste con resueltos en \[c\_m − 365 d, c\_m) y aplicación a forecasts con t0 ∈ \[c\_m, c\_{m+1}), sin LLM.
4. Cada versión cambia `rules_version`. Los forecasts ya congelados no se recalculan.

## (g) Riesgos

El riesgo dominante es R1: que no haya ventaja medible. La salida esperada más probable del sistema es "no operar", y el diseño lo trata como resultado válido, no como fallo.

| ID | Riesgo | Impacto | Mitigación | Detección |
| --- | --- | --- | --- | --- |
| R1 | El mercado es eficiente en estas categorías; no hay edge | Alto | Shrinkage hacia el precio; umbral de edge neto; P2 y P7 como gates | M1 ≥ 0 a n = 200 |
| R2 | El LLM inventa citas o cifras | Alto | El excerpt debe aparecer literal en el texto descargado; si no, pasa a SIN\_VERIFICAR y aporta 0 | Tasa de `excerpt_found = 0` > 5% → alerta |
| R3 | Fuga de información en la evaluación | Alto | Sin backtests con LLM; `forecasts` inmutable por trigger; t0 < resolución | Test que inserta un forecast con t0 posterior a la resolución y espera rechazo |
| R4 | Evaluación con poca potencia | Medio | Test agregado; CLV como indicador adelantado; sin relajar umbrales | Informe de potencia mensual |
| R5 | Ambigüedad de resolución o disputa UMA | Alto | Filtro F5 (ambigüedad ≤ 4); excluir mercados con `uma_status` de propuesta o disputa según `uma_status_map.toml`, con dominio verificado en el bloqueante V2 (B6) | Mercados VOID o disputados por mes |
| R6 | Comisiones y tamaño mínimo se comen el edge | Alto | Edge neto con VWAP y comisión conservadora; NO\_TRADE\_SIZE (T2) | Comisión real en 6a frente a la calculada |
| R7 | Cambio de esquema en la API (CLOB V2 ya ocurrió en abril de 2026) | Medio | Modelos con `extra="forbid"` en la capa normalizada y `SchemaDrift` explícito; fixtures reales | Test de contrato diario contra 1 mercado real |
| R8 | Rate limits o caída de una fuente | Bajo | Token bucket al 50%, backoff con jitter, checkpoints reanudables | Ciclos incompletos > 5% |
| R9 | Exceder el presupuesto LLM | Medio | Corte duro antes de cada llamada con coste estimado; tope 1.50 USD/día y cap\_mensual (30 USD)/mes | `llm_calls` agregado por mes |
| R10 | Exposición correlacionada (mismo evento o elección) | Alto | Caps por clúster (sección h); neg\_risk del mismo evento = mismo clúster | Exposición por clúster en cada ciclo |
| R11 | Jurisdicción: cambio de lista o IP del VPS fuera de MX | Alto | Chequeo de geoblock antes de cada pick en vivo; picks manuales desde tu jurisdicción real | `blocked = true` → sistema en NO\_TRADE |
| R12 | Inyección de instrucciones vía texto web | Medio | El texto web va delimitado como dato; salida forzada a schema; ningún agente tiene herramientas de escritura | Test con un documento que contiene instrucciones adversarias |
| R13 | Fuga de secretos | Medio | Variables de entorno; `.env` fuera del repo; claves de solo lectura donde existan | Escaneo de secretos en pre-commit |
| R14 | Disco o VPS perdido | Bajo | Backup diario de SQLite (`.backup`) a almacenamiento externo; restauración probada | Restore mensual verificado |

## (h) Gestión de capital y filtros duros

Un pick sale solo si pasa los 10 filtros, el sizing Kelly 1/4 supera el tamaño mínimo de orden y ningún cap se rompe. Cualquier otra salida queda registrada como NO\_TRADE con su código.

### Edge (definición operativa del brief)

Por lado, con el libro del token de ese lado y el tamaño candidato:

- `cost_YES = VWAP_ask(YES) + fee(YES)`; `edge_YES = p_final − cost_YES`
- `cost_NO = VWAP_ask(NO) + fee(NO)`; `edge_NO = (1 − p_final) − cost_NO`

Se evalúa el lado con mayor `edge_net`.

### Filtros duros

| Código | Condición para pasar |
| --- | --- |
| F1 Liquidez | Volumen 24 h ≥ 1,000 USDC y profundidad ≥ 100 USDC a 2 ticks del mejor precio del lado |
| F2 Spread | best\_ask − best\_bid ≤ 0.04 |
| F3 Horizonte | 2 ≤ días a end\_date ≤ 90 (papel) o 45 (vivo); se evalúa en t\_entrada (la decisión), no en la selección (C2) |
| F4 Edge | edge\_net ≥ 0.05 (0.03 si se activa la regla del mes 3) |
| F5 Ambigüedad | ambiguity\_final ≤ 4 |
| F6 Evidencia | ≥ 1 evidencia Tier A o ≥ 2 Tier B independientes, VERIFICADO y con `excerpt_found = 1` (C6), a favor del lado; contra-búsqueda ejecutada |
| F7 Zona de precio | Precio del lado entre 0.05 y 0.95 |
| F8 Estado | active = 1, closed = 0, `uma_status` mapeado a `open_no_proposal` en `config/uma_status_map.toml` (V2, B6). Un valor no mapeado falla F8 (fail-closed) y emite `SchemaDrift`. Hasta cerrar V2, cualquier `uma_status` no nulo falla F8 |
| F9 Sistema | Presupuesto disponible. En vivo, además, sin stop activo y geoblock OK. En papel el stop no bloquea (M4) |
| F10 Fuente de resolución monitorizable | Cada fuente de `ResolutionSpec.resolution_sources`, normalizada a dominio o id de entidad, está en `config/resolution_sources.toml`. Cada entrada de esa allowlist debe tener feed, API o URL monitorizada en la tabla (e). Si el texto no nombra ninguna fuente, F10 falla |

### Sizing

```latex
f^{*} = \frac{\pi - c}{1 - c}, \qquad \text{stake} = \min\left(0.25\, f^{*} B,\; 0.10\, B,\; \text{cupo del clúster},\; \text{cupo total}\right)
```

Aquí π es la probabilidad del lado según p\_final y c el coste por acción con comisión. Las acciones son floor(stake / c) al paso mínimo de tamaño (SIN VERIFICAR: precisión de `size`). Si el stake queda por debajo de min\_cost(c) (T2, según \`min\_order\_unit\`, B4), el resultado es NO\_TRADE\_SIZE. Con la unidad en acciones esto equivale a que las acciones queden por debajo de `min_order_size`. Nunca se redondea hacia arriba.

| Parámetro | Papel y 6b (`CAPS_PAPER`, `CAPS_6B`) | 6b-C (`CAPS_6B_C`, C1) |
| --- | --- | --- |
| Fracción Kelly | 0.25 sobre B = 50 | 0.25 sobre B = 50 |
| Cap por posición | 10% de B = 5 USDC | 5% de B = 2.5 USDC |
| Cap por clúster correlacionado | 20% de B = 10 USDC | 10% de B = 5 USDC |
| Exposición abierta total | 50% de B = 25 USDC | 25% de B = 12.5 USDC |
| Posiciones abiertas máximas | 8 | 4 |
| Stop de sistema | Equity MTM (a mid) ≤ 0.85 × pico → stop definitivo de la ejecución real. El ledger de papel calcula su propio drawdown solo para P5 y nunca se detiene (1.2/M4) | Igual que 6b, sobre la serie `live_6b_c` |
| Reanudar tras stop | `pmsys resume --ack-stop "<motivo>"`, después de revisión manual del informe automático | Igual |

6a no usa `Caps`: son como máximo 2 órdenes de tamaño mínimo con ledger propio (1.2/M3).

**Clústeres.** Mismo `event_id` o mercados neg\_risk del mismo evento; misma elección o país y fecha; misma publicación macro (por ejemplo, el mismo dato y mes). Las reglas viven en `clusters.toml`. El LLM puede proponer un clúster, pero solo entra tras aprobación manual.

### Aritmética de ejemplo

Ejemplo 1, Politics, π = 0.62, ask YES = 0.52:

1. fee = 0.04 × 0.52 × 0.48 = 0.0100 → c = 0.530
2. edge\_net = 0.62 − 0.530 = 0.090 → pasa F4
3. f\* = 0.090 / 0.470 = 0.1915 → 0.25 × 0.1915 × 50 = 2.39 USDC
4. Mínimo = 5 × 0.530 = 2.65 USDC > 2.39 → **NO\_TRADE\_SIZE**

Ejemplo 2, Geopolitics (comisión 0), π = 0.24, ask YES = 0.15:

1. c = 0.150; edge\_net = 0.090
2. f\* = 0.090 / 0.850 = 0.1059 → 0.25 × 0.1059 × 50 = 1.32 USDC
3. Acciones = floor(1.32 / 0.15) = 8 ≥ 5 → **SIZED**, stake 1.20 USDC

Si V1 resuelve que la unidad es USDC (B4), el mínimo del Ejemplo 2 pasa a 5 USDC > 1.32 y el resultado es NO\_TRADE\_SIZE. Con B = 50, por la fórmula de T2 solo serían viables picks sobre favoritos: c ≥ 0.80 con edge ≥ 0.08.

INFERIDO: con B = 50, los picks viables se concentran en precios alejados de 0.50 y en Geopolitics. Es una consecuencia de la estructura de costes, no una preferencia del modelo.

## Presupuesto LLM y enrutado

Desde la 1.4.0 el tope es \`cap\_mensual = 30 USD\` (en \`settings.toml\`) con 75 forecasts al mes. El coste estimado es 22.84 USD en los meses 1–3 y 19.35–26.33 USD desde el mes 4 (detalle en "Plan de muestra y presupuesto (1.4.0)"). La tabla siguiente es la estimación de la 1.3.0 con 50 forecasts; se conserva como base del cálculo. El tope es duro: `LlmClient` estima el coste antes de cada llamada y lanza `BudgetExceeded` si la llamada superaría 1.50 USD en el día o cap\_mensual en el mes.

### Plan de muestra y presupuesto (1.4.0)

Decisión tuya, con 3 partes:

- `cap_mensual = 30 USD`.
- 75 forecasts al mes, concentrados desde el mes 4 en las 2 mejores categorías (regla en (f)).
- Análisis síncrono (X de D4) desde el inicio solo en la categoría a, geopolítica.

A 30 USD al mes durante 9 meses son 270 USD de LLM frente a un bankroll de 50. Es un proyecto de investigación con una apuesta viva simbólica: el gasto se justifica por la información, no por el bankroll.

| Partida | Llamadas/mes | Coste/mes (USD) |
| --- | --- | --- |
| Triaje (Haiku) | 9,000 | 2.03 |
| Parser de reglas (Haiku) | 400 | 0.22 |
| Vista externa + síntesis (Sonnet, batch) | 150 | 6.75 |
| Red team + síntesis tras el pre-filtro (Opus, batch) | 60 | 7.20 |
| Red team del resto (Sonnet, batch) | 90 | 3.15 |
| **Base, todo en batch** |  | **19.35** |
| + X en a, meses 1–3 (≈ 25% de los forecasts en síncrono) |  | +3.49 → **22.84** |
| + X en a desde el mes 4, si a es activa (≈ 50%) |  | +6.98 → **26.33** |
| Desde el mes 4, si a no es activa |  | **19.35** |
| X extendido a b–d por la regla de latencia de D4 |  | +13.95 → 33.30: supera 30 y activa la escalera |

Corrección a la cifra de la revisión: sus 2.33 USD son el 25% del sobrecoste de X calculado con 50 forecasts (9.30). Con 75 forecasts ese sobrecoste es 13.95 y su 25% es 3.49. El total queda en 22.84 USD, también bajo 30.

Con X ya activo en a, la regla de latencia de D4 se evalúa solo sobre b–d. Si se dispara, extiende X a b–d.

**Margen frente a la escalera (1.4.1).** El escalón 1 se dispara cuando la proyección del mes supera `cap_mensual` (30 USD). El valor 27 USD (0.9 × cap\_mensual) es solo el umbral de reversión, no de disparo. En el peor caso previsto (meses 4+ con a activa, 26.33 USD) el margen es de 3.67 USD, un 12% del coste.

Precios por millón de tokens (entrada / salida). Fuentes secundarias de octubre de 2026; la página oficial no se pudo abrir desde aquí, así que están SIN VERIFICAR contra platform.claude.com:

- Haiku 5.5: 0.10 / 0.50 para prompts ≤ 100K
- Sonnet 5.5: 2 / 10
- Opus 5.5: 4 / 20
- Batch API: −50%

| Tarea | Modelo | Llamadas/mes | Tokens por llamada (entrada / salida) | Coste/mes (USD) |
| --- | --- | --- | --- | --- |
| Triaje de mercados nuevos o con cambio | Haiku, síncrono | 9,000 (150 × 60 ciclos) | 1,500 / 150 | 2.03 |
| Parser de reglas | Haiku, síncrono | 400 | 3,000 / 500 | 0.22 |
| Vista externa + síntesis de evidencia | Sonnet, batch | 100 | 25,000 / 4,000 | 4.50 |
| Red team + síntesis final, tras pre-filtro | Opus, batch | 40 | 30,000 / 6,000 | 4.80 |
| Red team del resto | Sonnet, batch | 60 | 20,000 / 3,000 | 2.10 |
| **Total** |  |  |  | **13.65** |

INFERIDO: los tokens de razonamiento cuentan como salida, y las estimaciones de salida ya los incluyen. Si el mes 1 supera 18 USD, se baja el esfuerzo de Opus antes de tocar el número de forecasts.

**Pre-filtro a Opus**: solo pasan los mercados que cumplen las 3 condiciones:

- |p\_model(Sonnet) − mid| ≥ 0.07
- F1, F2, F3, F5 y F7 pasados
- Stake Kelly estimado ≥ min\_cost(c) (T2; depende de \`min\_order\_unit\`, B4)

Si un mercado no puede acabar en pick, no paga Opus.

**Batch y t0**: el batch devuelve en horas (fuente secundaria: normalmente menos de 24 h), así que el análisis pedido en el ciclo N se consume en N+1 o N+2. La evidencia se congela con su `retrieved_at`. t0 y mid\_t0 se fijan en el momento de la decisión, con libro fresco. Si el mid se movió ≥ 0.05 entre evidencia y decisión, se fuerza una revisión antes de decidir.

**Congelación de la evidencia (D4).** Al cerrar el paquete de evidencia de un análisis, en la misma transacción se lee el libro del token YES y se guardan en `analyses`:

- `t_evidence`: instante de congelación.
- `mid_t_evidence`: mid en ese instante.

`record_forecast` los copia a `forecasts`, y el trigger de 0002 exige t\_evidence ≤ t0. mid\_t0 sigue siendo el benchmark primario (M1) porque es el precio contra el que se opera. M1b, contra mid\_t\_evidence, es diagnóstico obligatorio en el mismo informe.

## Orden de construcción y registro de verificación

La Fase 2 empieza cerrando los 8 puntos SIN VERIFICAR de la tabla siguiente con fixtures reales. Cada módulo se entrega con sus tests en verde antes de abrir el siguiente.

### Bloqueantes de entrada a Fase 2 (B4, B6)

No se empieza ningún módulo de los pasos 2–8 del orden hasta cerrar V1 y V2. El paso 1 (core, db, http) sí puede avanzar en paralelo.

**V1. Unidad de `mos` / `orderMinSize` (B4).**

- **Método, en orden:**
  1. Documentación oficial de Polymarket.
  2. Lógica de validación de tamaño en el código público de `py-clob-client-v2`.
  3. Solo si 1 y 2 no lo resuelven o discrepan: una orden post-only GTC de `mos` acciones a precio 0.01 en un mercado líquido (nocional ≈ 0.05 USDC), desde la cuenta de la tarea 1.1/M6, cancelada en cuanto se acepte. Si se acepta con nocional menor que `mos` USDC, la unidad es acciones; si la rechaza el validador de tamaño mínimo, es USDC.
- **Fixture:** `tests/fixtures/clob_markets_mos.json` con `/clob-markets/{condition_id}` de 20 mercados reales de las 4 categorías.
- **Aceptación:**
  - Dos fuentes independientes coinciden, o se ejecutó el test 3 (con su order id registrado).
  - `min_order_unit` queda escrito en `settings.toml` con URL, fecha de consulta y extracto.
  - Si es `"usdc"`, se ejecutó la contingencia de T2 y tienes delante la decisión de B\_live.

**Estado de V1 (2026-11-09): unidad = acciones, a falta del test 3 o de una segunda fuente independiente.**

- **Método 1, VERIFICADO.** [Place orders](https://docs.polymarket.com/trading/place-orders.md) (endpoints de `clob.polymarket.com`) define `min_order_size` como el número mínimo de acciones que el CLOB acepta por orden. La misma página fija 2 decimales de tamaño para todos los tick sizes, lo que cierra también el pendiente "precisión de `size`": 0.01 acciones.
- **Método 2, neutral.** El código de `py-clob-client-v2` 1.2.1 (sdist de PyPI) no valida el tamaño mínimo en cliente: delega en el servidor. Tipa `min_order_size` sin unidad, así que no confirma ni contradice.
- **Fuentes secundarias:** varias guías de terceros dicen "5 acciones mínimo para limit orders" y "1 USD mínimo para market orders". Lo segundo está SIN VERIFICAR en fuente oficial; no afecta al sizing porque la ejecución manual usa limit orders.
- **Para cerrar V1 con el criterio de aceptación** (dos fuentes independientes) falta el test 3, que necesita la cuenta fondeada de 1.1/M6, o una segunda fuente oficial. Mientras tanto, `min_order_unit = "shares"` queda como valor provisional en `settings.toml` y la contingencia de T2 no se activa.

**Estado de V2 (2026-11-09): no ejecutable desde este entorno.** El proxy de salida rechaza `gamma-api.polymarket.com` y `clob.polymarket.com`. El barrido tiene que correr en tu VPS, o aquí si añades esos dominios a la lista permitida en Settings > Capabilities.

**V2. Dominio de `umaResolutionStatus` (B6).**

- **Método:** barrido completo de `/markets/keyset` con `closed=false` y con `closed=true` (resueltos en los últimos 365 días), registrando cada valor distinto de `umaResolutionStatus` con su recuento. El filtro `uma_resolution_status` de `/markets` (VERIFICADO como parámetro) se usa después para buscar ejemplos de cada valor. Si el barrido no contiene mercados abiertos en propuesta o en disputa, se repite a diario durante un máximo de 14 días.
- **Fixture:** `tests/fixtures/uma_status_values.json` con `{valor: {count, market_id_ejemplo, observado_en}}`.
- **Mapeo:** `config/uma_status_map.toml` asigna cada valor observado a uno de 4 estados: `open_no_proposal`, `proposed`, `disputed`, `resolved`.
- **Aceptación:**
  - El 100% de los valores observados están mapeados.
  - Hay al menos un ejemplo real de `proposed` y otro de `disputed`. Si a los 14 días no apareció alguno, queda constancia escrita y solo los valores vistos en mercados abiertos sin actividad UMA pasan F8.
  - Test: un valor no mapeado hace fallar F8 y emite `SchemaDrift`.
- **Mientras V2 no cierre**, F8 es fail-closed para cualquier `uma_status` no nulo.

### Orden

1. `core` (modelos, errores, clock, ids) + `infra.db` con la migración 0001 y `infra.http` con fake de red.
2. `ingest.gamma`, `ingest.clob`, `ingest.geoblock`, con fixtures grabados y un test de contrato real diario.
3. `normalize` + `rules.parser`: primero la rúbrica determinista, con los tests de fecha, zona horaria, DST, "by" frente a "on" y VOID.
4. `analysis.market_implied` + tabla de sesgo por bucket sin LLM (ya da una primera línea base medible).
5. `decision.costs`, `filters`, `sizing`, `risk`, con property tests (stake ≤ caps, nunca por debajo del mínimo, monotonía en edge).
6. `ledger.paper` + `eval.scoring`/`calibration`. A partir de aquí el sistema puede puntuar la línea base sin LLM.
7. `infra.llm` + `evidence` + `outside_view` + `red_team` + `synthesis` (Fase 3–4).
8. `pipeline` reanudable + CLI + backups. Arranque de papel.

INFERIDO: el paso 6 antes del 7 importa. Permite medir P7 (¿el LLM añade algo sobre la línea base sin LLM?) desde el día 1.

### Registro de verificación (R2, R12)

Todas las consultas se hicieron el 2026-11-04. Ninguna de estas páginas muestra fecha de publicación por página, salvo donde se indica.

| Afirmación usada en la spec | Estado | Fuente | Extracto |
| --- | --- | --- | --- |
| MX no está restringido; endpoint de geoblock y sus campos | VERIFICADO | [Geographic Restrictions](https://docs.polymarket.com/api-reference/geoblock.md) | MX ausente de las listas Blocked y Close-only; `blocked`, `ip`, `country`, `region` |
| `mos`, `mts` y `fd` (r, e, to) en `/clob-markets/{condition_id}` | VERIFICADO (unidad de `mos` SIN VERIFICAR) | [Get CLOB market info](https://docs.polymarket.com/api-reference/markets/get-clob-market-info.md) | "Minimum order size", ejemplo 5 |
| Fórmula y tasas de comisión; solo pagan los takers; Geopolitics 0 | VERIFICADO (exponente SIN VERIFICAR) | [Fees](https://docs.polymarket.com/trading/fees.md) | "Makers are never charged fees. Only takers pay fees." |
| Rate limits de Gamma y CLOB | VERIFICADO | [Rate Limits](https://docs.polymarket.com/api-reference/rate-limits.md) | Gamma `/markets` 300 req/10 s; general 15,000 req/10 s |
| CLOB V2 en el host estándar desde el 28 de abril de 2026 | VERIFICADO | [Changelog](https://docs.polymarket.com/changelog.md) | Desde el 28 de abril, V2 corre en clob.polymarket.com |
| `/prices-history`: parámetros `market`, `startTs`, `endTs`, `interval`, `fidelity` | VERIFICADO | [Timeseries](https://docs.polymarket.com/developers/CLOB/timeseries.md) | `fidelity`: resolución en minutos |
| Resolución por UMA Optimistic Oracle, con bond y disputa | VERIFICADO | [Resolution](https://docs.polymarket.com/concepts/resolution) | Cualquiera puede proponer y disputar un resultado |
| Campos de Gamma (`orderMinSize`, `umaResolutionStatus`, `resolutionSource`) | VERIFICADO presencia; dominios SIN VERIFICAR | [List markets](https://docs.polymarket.com/api-reference/markets/list-markets) | Aparecen en el esquema de respuesta |
| GDELT: 1 req/5 s, sin clave, ventana de 3 meses | Fuente secundaria (SIN VERIFICAR en gdeltproject.org) | [Jentic GDELT](https://jentic.com/apis/api.gdeltproject.org/gdelt) | Mensaje 429: limitar a una petición cada 5 s |
| FRED: 120 req/min por clave | Fuente secundaria (SIN VERIFICAR) | [fredr NEWS](https://erised.las.iastate.edu/CRAN/web/packages/fredr/news/news.html) | El límite parece ser 120 peticiones por minuto |
| CourtListener: 5/min, 50/h, 125/día | VERIFICADO | [REST API v4.4](https://wiki.free.law/c/courtlistener/help/api/rest/v4/overview) | Usuario autenticado: hasta 5 req/min, 50/h, 125/día |
| Precios de Haiku, Sonnet y Opus 5.5 y descuento batch | Fuente secundaria (SIN VERIFICAR en la página oficial) | [Maxim, 2026-10-29](https://www.getmaxim.ai/articles/claude-api-pricing/) | Precios por millón de tokens de las cuatro familias |
| CX22 descontinuado; CX23 a 5.49 EUR y no disponible para pedido | Fuente secundaria (SIN VERIFICAR) | [Bitdoze](https://www.bitdoze.com/es/hetzner-cloud-precios-2026/) | CX23 pasa de 2.99 a 5.49 EUR y no se puede pedir |
| Potencia del test con n = 50 / 200 | INFERIDO | Simulación propia (1,500 réplicas, semillas 7 y 11) | — |

### Pendientes de cerrar en Fase 2

- [ ] Movido a bloqueante V1 (B4): unidad de `mos` y `orderMinSize` (acciones o USDC) y precisión de `size`
- [ ] Semántica de `fd.e` frente a la fórmula publicada
- [ ] Movido a bloqueante V2 (B6): dominio de valores de `umaResolutionStatus`
- [ ] Tag IDs de Gamma para las categorías a, b, c, d
- [ ] Límite de rango de `/prices-history` por `fidelity`
- [ ] Precios oficiales de la API de Anthropic y latencia real del batch
- [ ] Rate limit del endpoint de geoblock
- [ ] Primera allowlist de RSS oficiales (la propones tú)

### Tareas añadidas a Fase 2 en la 1.1.0

- [ ] **(M2) Tasa de paso de F5.** Medir la tasa de paso con la rúbrica 1.1.0 sobre ≥ 200 mercados elegibles reales grabados como fixtures. Si es < 30%, etiquetar a mano 100 de esos mercados (ambiguo sí/no) y reajustar los puntos de la rúbrica hasta superar el 30%, sin que pase ninguno de los etiquetados como ambiguos. Cada ajuste sube `parser_version`. Aceptación: informe con tasa de paso, distribución del score y, si hubo ajuste, la rúbrica nueva con su tasa.
- [ ] **(M6) Fondeo y KYC del venue para no residentes en EE. UU. (MX).** Aceptación, con las 3 condiciones:
  - Fuente oficial de Polymarket con URL, fecha de consulta y extracto que describa el método de depósito, el token de colateral (USDC o pUSD, SIN VERIFICAR) y los requisitos de KYC aplicables a un residente en México.
  - Depósito de prueba ≤ 5 USDC acreditado y retiro ≥ 1 USDC completado a una dirección propia, con los hashes de transacción registrados.
  - Sin las dos anteriores, la Fase 6a no arranca.
- [ ] **(D2) Semántica de fechas en mercados cerrados.** Verificar `startDate` y `closedTime` sobre 50 mercados resueltos, cotejados con la fecha de resolución visible. Si `closedTime` no es la resolución, se documenta el campo sustituto antes de construir clases.
- [ ] **(D5) Historial de precios de mercados resueltos.** Verificar que `/prices-history` devuelve historial con `fidelity = 60` para tokens de mercados resueltos hace hasta 365 días.
- [ ] **(D3) Tag IDs por categoría.** Cerrar `categories.toml`, incluida la regla de prioridad, y grabar un universo completo como fixture.

### Tareas añadidas a Fase 2 en la 1.3.0

Las dos allowlists se cierran juntas, antes del paso 7 del orden (evidencia). F10 solo bloquea picks: M1, M1b y P1–P3 no dependen de él, así que el scoring puede arrancar sin las allowlists.

- [ ] **(C8) Allowlist inicial de `resolution_sources.toml`.**
  - Método:
    - Sobre el fixture del universo de la tarea D3, extraer `resolution_sources` de todos los mercados elegibles con `rules.parser`.
    - Normalizar a dominio o id de entidad y contar la frecuencia de cada fuente.
    - Para cada fuente, registrar un canal monitorizable gratuito (feed, API o URL), ya presente en la tabla (e) o nuevo.
  - Aceptación:
    - La allowlist cubre ≥ 60% de los mercados elegibles del fixture; es decir, F10 pasa en ≥ 60%.
    - Cada entrada tiene una URL descargada con éxito desde el VPS, con fecha.
    - Tú apruebas la lista.
    - Un test de F10 sobre el fixture da la tasa de paso esperada.
    - Si con canales gratuitos la cobertura queda por debajo del 60%, se reporta la tasa real y su efecto sobre la tasa de pick antes de continuar.
- [ ] **Allowlist inicial de RSS oficiales** (la tarea ya pendiente, ahora con criterio).
  - Aceptación:
    - ≥ 1 feed por categoría a–d.
    - Cada feed se descarga y `evidence/rss.py` lo parsea en un test con fixture grabado.
    - Tú apruebas la lista.

## Criterios de aceptación (1.1.0)

La spec 1.1.0 se acepta si cada fila tiene texto implementable en su sección y un test definido. La Fase 2 termina cuando todos los tests de esta tabla pasan.

| ID | Criterio | Verificación |
| --- | --- | --- |
| AC-D1 | P4 exige n ≥ 15 y límite inferior del IC 90% > 0. M10 existe y no aparece en `PromotionVerdict`. La regla del mes 3 aplica A una sola vez | Test de `promotion_check`: 14 picks → P4 falla por n. Test de que M10 no figura entre los gates |
| AC-D2 | Dos ejecuciones del mismo mercado dan el mismo `class_sha` y `members_sha`. La cadena se recorre L0 → L4 en orden. L4 < 20 → `REFCLASS_EXHAUSTED` | Tests unitarios sobre una base de fixtures con recuentos controlados por nivel |
| AC-D3 | Mismo universo + mismo `cycle_id` → mismo lote de 150. La URL generada no contiene `order`, `volume_num_*` ni `liquidity_num_*`. Enumeración incompleta → `selection_runs.status = 'failed'`. Cada mercado visto tiene fila en `selection_members` | Test con HTTP falso; aserción sobre las URL; test de fallo a mitad de paginación |
| AC-D4 | Todo analysis y forecast tiene `t_evidence ≤ t0` y `mid_t_evidence`. El informe mensual incluye M1 y M1b y evalúa la regla de latencia | Trigger de 0002 + test del generador de informes |
| AC-D5 | Ningún mercado del ajuste tiene `resolved_at ≥ cutoff_utc`. Todo forecast tiene t0 dentro de la ventana de su `bias_version`. Celdas < 30 → agregadas o identidad | Test de invariantes + trigger `trg_calib_cutoff` |
| AC-D6 | 'other' nunca llega a `analyses` ni a `forecasts` | Test de `CategoryInvariantError` + INSERT directo rechazado por trigger |
| AC-M1 | F10 implementado; `filters_failed` acepta F1–F10 y rechaza F0 y F11 | Test de `jsonschema` + test de `apply_filters` sin fuente nombrada |
| AC-M2 | Fecha sin hora o sin zona suma +1. Existe el informe de tasa de paso de F5 | Test de rúbrica + tarea M2 cerrada |
| AC-M3 | Tope diario 1.50 USD; mensual cap\_mensual = 30 USD | Test de `BudgetExceeded` en 1.50 y en 30 |
| AC-M4 | Con stop activo, el ciclo de papel termina `done` y la decisión en vivo sale `NO_TRADE_STOP` | Test de integración con `system_state` en stop |
| AC-M5 | M7 incluye la tasa de VOID por categoría | Test del informe |
| AC-M6 | La tarea de fondeo y KYC está cerrada con sus 3 condiciones antes de 6a | Bloqueo en `promotion_check` para 6a |

**Criterios añadidos en 1.2.0 (1.2/M9).**

| ID | Criterio | Verificación |
| --- | --- | --- |
| AC-B1 | P2 pasa y P4 falla por potencia → veredicto 6b-C. P4 falla por señal → sin promoción. En 6b-C se respetan los caps de 12.5 / 2.5 USDC y 4 posiciones, y la parada temprana | Test de `promotion_check` en 3 escenarios: (i) P2 pasa y n\_picks = 9 → `PROMOTE_6B_C`; (ii) n = 16 y CLV medio −0.01 → `NO_PROMOTION_SIGNAL`; (iii) 8 picks de 6b-C con CLV medio −0.03 → `BACK_TO_PAPER`. Test de `risk_check`: el quinto pick o el que supera 12.5 USDC sale `NO_TRADE_CAP` |
| AC-B2 | P5 = P&L ≥ 0 + drawdown ≤ 15% en los últimos 3 meses + drawdown del periodo ≤ 30% | Test con series de equity sintéticas: (i) drawdown del 20% en el mes 2, ≤ 10% en los meses 7–9 y P&L > 0 → pasa; (ii) 16% en el mes 8 → falla; (iii) 35% en cualquier momento → falla |
| AC-B3 | Buckets H1a/H1b con centros 5 y 11; H2 y H3 en 30 y 68 | Test: un forecast a 3 días va a H1a y uno a 9 días a H1b. Test de que el ajuste usa τ\_H con esos centros. El informe muestra la fracción de H1a con vida < 5 días |
| AC-B4 | V1 cerrado antes de los pasos 2–8. El sizing respeta `min_order_unit` | El arranque falla si `settings.toml` no tiene `min_order_unit`. Test: el Ejemplo 2 da `SIZED` con "shares" y `NO_TRADE_SIZE` con "usdc" |
| AC-B5 | `analyses` inmutable; INSERT con t\_evidence > t0 rechazado | Tests de UPDATE, DELETE e INSERT inválido contra 0003 (VERIFICADOS en esta revisión) |
| AC-B6 | V2 cerrado con fixture y mapeo; F8 fail-closed | Test: un valor no mapeado → F8 falla y emite `SchemaDrift`. Antes de V2, cualquier `uma_status` no nulo → F8 falla |
| AC-1.2/M1 | La escalera de recorte se aplica en orden, con ≥ 3 días entre escalones, antes de `BudgetExceeded` | Test con gasto simulado que proyecta 30 USD/mes |
| AC-1.2/M2 | P4 excluye `live_6a` | Test de `promotion_check` con 2 fills de 6a |
| AC-1.2/M3 | La serie `live_6b` empieza en 50 con pico 50, sea cual sea el resultado de 6a | Test de ledger |
| AC-1.2/M4 | `identity-v0` se acepta el mes 1 y se rechaza cuando hay una versión ajustada vigente | Test contra 0003 (VERIFICADO en esta revisión) |
| AC-1.2/M5 | La compactación conserva las filas triadas y seleccionadas, y la SMD da el mismo valor antes y después | Test sobre un ciclo sintético |
| AC-1.2/M6 | DELETE rechazado en las 3 tablas de clases | Test contra 0003 |
| AC-1.2/M7 | `ts` sin milisegundos rechazado en `book_snapshots` y `equity` | Test contra 0003 (VERIFICADO en esta revisión) |
| AC-1.2/M8 | Hay una revisión de categorías programada a 6b + 3 meses | Test del planificador de informes |

**Criterios añadidos en 1.3.0.**

| ID | Criterio | Verificación |
| --- | --- | --- |
| AC-C1 | `risk_check` aplica `CAPS_BY_MODE[mode]`; `positions.mode` admite `live_6b_c` | Test: en 6b-C, el quinto pick o el que supera 12.5 USDC sale `NO_TRADE_CAP`; en 6b se admiten 8. Test de CHECK contra 0004 (VERIFICADO) |
| AC-C2 | t\_clv ≥ t\_entrada + 6 h; resolución temprana → `unmeasurable` | Test con un mercado resuelto 3 h después de la entrada → `clv_status = 'unmeasurable'`. Trigger de 0004 (VERIFICADO) |
| AC-C3 | Sin versiones solapadas ni editables; caída a identidad registrada; alerta a 7 días | Tests contra 0004 (VERIFICADOS). Test de la alerta diaria con un calendario sin versión futura |
| AC-C4 | La SMD se reproduce tras compactar con ambas definiciones | Test sobre un ciclo sintético, antes y después de compactar |
| AC-C5 | La sección 0 refleja que el papel no se detiene | Revisión del documento (cerrado en 1.3.0) |
| AC-C6 | F6 no cuenta evidencias con `excerpt_found = 0` | Trigger de 0004 (VERIFICADO) + test de `apply_filters` con una evidencia sin excerpt → F6 falla |
| AC-C7 | La escalera revierte un escalón al mes solo si cabe en 22.5 USD; X nunca se deshace | Test con gasto simulado de 21 USD con X activo: el escalón 1 no revierte |
| AC-C8 | Las allowlists de resolución y RSS cumplen su criterio antes del paso 7 | Tareas de 1.3.0 cerradas |
| AC-C9 | Un mercado cuenta una vez en P4, con el registro vivo | `v_p4_picks` contra 0004 (VERIFICADO) |
| AC-C10 | El papel sigue con un modo vivo activo; `live_review` aplica la tabla de ciclo de vida | Test de integración con `live_6b` activo: el ciclo de papel termina `done`. Un test por cada fila de la tabla |
| AC-C11 | `promotion_check` y `live_review` devuelven los enums de (b) con la precedencia definida | Un test por valor de `PromotionOutcome` y de `LiveOutcome`, más uno con P7 fallando → `variant = NO_LLM` |
| AC-O1 | Parada temprana de 6b-C con 8 picks y umbral −0.03 | Test: 8 picks con media −0.025 → CONTINUE; con −0.035 → BACK\_TO\_PAPER |
| AC-O2 | La ventana de la condición 2 de P5 se amplía hasta contener ≥ 10 picks | Test con 7 picks en los últimos 3 meses: la ventana se extiende |

**Criterios añadidos en 1.4.0.**

| ID | Criterio | Verificación |
| --- | --- | --- |
| AC-1.4/1 | Las migraciones siguen el protocolo de FKs; `foreign_key_check` vacío tras cada una | Test del migrador. Barrido de FKs hijas (VERIFICADO: ninguna hacia `positions`) |
| AC-1.4/2 | Cadena de t\_clv standard → early\_24h → terminal\_1h → unmeasurable | Tests con resolución a las 3 h de la entrada (terminal\_1h) y a los 30 min de la entrada (`unmeasurable`). Trigger de 0005 (VERIFICADO) |
| AC-1.4/3 | Cadena de versiones contigua: una sola abierta, solo cierre, sin reasignar forecasts | Tests contra 0005 (VERIFICADOS): alta cerrada, alta anterior a la abierta, edición, reapertura, alta retroactiva |
| AC-1.4/4 | La revisión trimestral aplica las 8 filas en orden | Un test por fila, más uno con n\_live = 7 → CONTINUE "sin decisión por potencia" |
| AC-1.4/5 | La escalera usa `0.9 × cap_mensual − ahorro` y `cap_mensual` sale de `settings.toml` | Test con cap\_mensual = 30 y gasto de 21 USD: el escalón 1 (ahorro 3) revierte. Con cap\_mensual = 25 no revierte |
| AC-1.4/6 | Concentración del mes 4: 2 categorías activas por M1 contraído; E1 y cuota 25 | Test con 4 categorías sintéticas y empate resuelto por n |
| AC-1.4/7 | X activo solo en a desde el inicio; la regla de latencia se evalúa solo en b–d | Test de enrutado: un forecast de a va en síncrono; uno de b, en batch |
| AC-1.4/8 | Ventana de P5 con techo de 6 meses | Test con 1.5 picks/mes: la ventana se corta en 6 meses y el informe la marca "n < 10" |

## Changelog

| ID | Sección | Resumen del cambio |
| --- | --- | --- |
| V | Cabecera | Versión 1.1.0 |
| D1 | (f) Métricas, Umbrales, Potencia de P4, Regla del mes 3; (h) F4 | P4 pasa a n ≥ 15 manteniendo el IC 90%. Nuevo M10 (CLV sombra de NO\_TRADE\_SIZE, solo indicador). Tabla de potencia para tasas de 2/5/10% a 3/6/9 meses. Regla del mes 3 con X = bajar F4 a 0.03 |
| D2 | (b) Clase de referencia; (b) `BaseRate` y `base_rate`; (d) `outside_view`; (c) 0002 | RefClassQuery tipado, regla de pertenencia, dimensiones dentro y fuera, cadena L0–L4, registro de clases externas con validación, congelación y hash |
| D3 | (b) pipeline.select; (c) 0002 | Consulta `/markets/keyset` por tag sin orden ni filtros de volumen, paginación por cursor, deduplicación, elegibilidad E1–E6, recorte estratificado por hash, metadatos y auditoría SMD/Horvitz–Thompson |
| D4 | (f) M1b y regla de latencia; Presupuesto LLM; (b) `record_forecast`; (d) `market_implied`; (c) 0002 | Columnas `t_evidence` y `mid_t_evidence`; M1 primario y M1b diagnóstico; X = análisis síncrono |
| D5 | (b) Tabla de sesgo del precio; (f) bucle paso 3; (c) 0002 | Corte mensual, ventana de ajuste de 365 d, aplicación al mes siguiente, n ≥ 30 por celda, agregación y luego identidad, persistencia del corte con trigger |
| D6 | 1 (T7); (b) Invariante de categoría; (c) 0002 | 'other' excluido en E1, conservado en `markets`, aserción en `analyze()` y trigger en `forecasts` |
| M1 | (h) Filtros; (d) patrón; (a) árbol | F10 con allowlist `resolution_sources.toml`; patrón `^F(10\|[1-9])$` |
| M2 | (b) rúbrica; Tareas de Fase 2 | Fecha sin hora o sin zona: de +2 a +1; tarea de tasa de paso de F5 |
| M3 | Presupuesto LLM | Tope diario de 0.80 a 1.50 USD |
| M4 | (b) errores; (h) tabla de capital y F9 | `SystemStopped` solo en la ruta de ejecución real; el papel y el scoring continún |
| M5 | (f) M7 | Tasa de VOID por categoría |
| M6 | Tareas de Fase 2 | Verificación de fondeo y KYC con criterio de aceptación |
| J1 | (f) M5 | Fuera de lista. CLV redefinido a horizonte fijo (t\_entrada + 7 d o end\_date − 24 h). Con el precio de cierre posterior a la resolución, el CLV equivale al P&L por acción (σ ≈ 0.5) y la tabla de potencia de D1 no tendría sentido. Columnas `t_clv` y `clv_h` en 0002 |
| J2 | (a) árbol | Fuera de lista. Tres ficheros de config (`event_types.toml`, `ref_external.toml`, `resolution_sources.toml`), requeridos por D2 y M1 |
| J3 | (b) errores | Fuera de lista. `CategoryInvariantError` y `SelectionIncomplete`, requeridos por D6 y D3 |
| J4 | (g) R9 | Fuera de lista. Tope diario actualizado a 1.50 USD para que sea coherente con M3 |
| J5 | (b) pipeline.select, paso 8 | Fuera de lista. El triaje no puede emitir probabilidad ni edge. Sin esta restricción, el sesgo que D3 quita en el recorte reaparecería en el paso de triaje a forecast |
| J6 | (c) | Fuera de lista. Los cambios de esquema van en una migración 0002 y no editan 0001, con tabla de trade-off. VERIFICADO: 0001 + 0002 ejecutan y los triggers rechazan los casos inválidos |

### Changelog 1.2.0

| ID | Sección | Resumen del cambio |
| --- | --- | --- |
| V | Cabecera | Versión 1.2.0; prefijo "1.2/" para las correcciones menores |
| B1 | (f) Veredicto si P2 pasa y P4 falla por potencia | Definidos el fallo por potencia y el fallo por señal. Opciones (a), (b) y (c); se adopta (a), 6b-C, con caps reducidos, parada temprana y reevaluación de P4 a 15 picks o 6 meses |
| B2 | (f) Umbrales P5; P5 y drawdown | P5 = P&L ≥ 0 + drawdown ≤ 15% en los últimos 3 meses + techo del 30%. Simulación de tasas de fallo de las 3 opciones |
| B3 | (b) Tabla de sesgo, puntos 3–4; Buckets de calibración | H1 partido solo en calibración: H1a \[2, 8) con centro 5 y H1b \[8, 15) con centro 11. H2 y H3 verificados centrados. Sesgo residual documentado |
| B4 | 0 (Dependencia abierta); 1 (T2, contingencia); (h) Sizing y Ejemplo 2; Presupuesto (pre-filtro); Bloqueantes V1 | `min_cost(c)` según unidad; procedimiento si la unidad es USDC con tabla rehecha y decisión de B\_live; V1 como primer bloqueante |
| B5 | (c) Migración 0003 | `analyses` inmutable (opción B de 3); trigger de INSERT con t\_evidence ≤ t0 |
| B6 | (h) F8; (g) R5; Bloqueantes V2 | Dominio de `umaResolutionStatus` como bloqueante con fixture, mapeo y criterio de aceptación; F8 fail-closed |
| 1.2/M1 | (f) Latencia, punto 4 y escalera | Recorte precomprometido en 3 escalones antes de `BudgetExceeded` |
| 1.2/M2 | (f) Fase 6a → 6b | Las órdenes de 6a no cuentan para P4 |
| 1.2/M3 | (f) Fase 6a → 6b | Secuencial sobre el mismo bankroll con ledger separado y reposición a 50 al iniciar 6b |
| 1.2/M4 | (c) 0003 | Semilla `identity-v0`; el trigger exige una versión existente y vigente desde el mes 1 |
| 1.2/M5 | (c) 0003 | Compactación a 90 días en `selection_members_agg`; las filas triadas y seleccionadas se conservan |
| 1.2/M6 | (c) 0003 | DELETE abortado en `ref_classes`, `ref_class_members` y `market_ref_class` |
| 1.2/M7 | (c) 0003 | `ts` con milisegundos en `book_snapshots` y `equity` |
| 1.2/M8 | 1 (T3) | Revisión de categorías a 6b + 3 meses |
| 1.2/M9 | Criterios de aceptación | Tabla añadida con tests para B1–B6 y 1.2/M1–M8 |
| J7 | (a) árbol | Fuera de lista. `uma_status_map.toml`, requerido por B6 |
| J8 | (c) 0003 | Fuera de lista. UPDATE abortado también en `ref_classes`, por coherencia con su congelación (D2) |
| J9 | (b) Buckets de calibración | Fuera de lista. Si más del 20% de los forecasts de H1a tienen vida < 5 días, su celda pasa a identidad. Acota el sesgo residual que B3 obliga a documentar |
| J10 | 1 (T3) | Fuera de lista. Una categoría que sale de la selección cierra solo por vencimiento, para no generar ventas forzadas con comisión |
| J11 | (h) Sizing | Fuera de lista. Eliminada una frase duplicada ("el resultado es NO\_TRADE\_SIZE") que dejó la edición de B4 |
| J12 | (f) P5 y drawdown | Fuera de lista, sin cambio normativo. Se señala que P&L ≥ 0 explica la mayor parte del falso rechazo de P5; queda propuesto para la próxima revisión |

### Changelog 1.3.0

| ID | Sección | Resumen del cambio |
| --- | --- | --- |
| V | Cabecera; 0; 1 | Versión 1.3.0. T1 = C, T2 = C y T3 = B registradas como aprobadas en la sección 0 y en los encabezados de la sección 1 |
| C1 | (b) Caps por modo; (b) `risk_check`; (h) tabla de capital; (c) 0004 | `Caps` y `CAPS_BY_MODE` con el perfil 6b-C; modo `live_6b_c` mediante la reconstrucción de `positions` |
| C2 | (f) M5; (h) F3; (c) 0004 | t\_clv = max(t\_entrada + 6 h, min(t\_entrada + 7 d, end\_date − 24 h)); F3 se evalúa en t\_entrada; `clv_status` con valor `unmeasurable`; trigger |
| C3 | (c) 0004 | `calibration_params` inmutable y sin solapes; `bias_fallback_log`; alerta diaria a 7 días; versión mensual siempre insertada |
| C4 | (c) 0004; (b) pipeline.select, punto 10 | Sumas ponderadas en `selection_members_agg`; definición exacta de la SMD |
| C5 | 0 | Fila de stop: el papel no se detiene |
| C6 | (h) F6; (c) 0004 | VERIFICADO exige `excerpt_found = 1` (filtro, trigger y validador) |
| C7 | Presupuesto: escalera y orden con X | Reversión por holgura (opción C de 3; no es fracción del coste base, justificado); X tiene prioridad sobre la escalera |
| C8 | Tareas de Fase 2 en 1.3.0 | Allowlist de `resolution_sources.toml` con criterio (≥ 60% de cobertura); la de RSS con criterio |
| C9 | (f) P4; B1 punto 4; (c) 0004 | Un mercado cuenta una vez, con el registro vivo; vista `v_p4_picks` |
| C10 | (f) Ciclo de vida tras la promoción | El papel continúa siempre; revisión trimestral con tabla de consecuencias |
| C11 | (b) Caps por modo y veredictos | `PromotionOutcome`, `ModelVariant`, `PromotionVerdict`, `LiveOutcome` y `LiveReview`, con precedencias |
| O1 | (f) B1 punto 3 y umbral de la parada temprana | 8 picks y umbral −0.03 (opción de 4 en tabla) |
| O2 | (f) P5 | Ventana de la condición 2 ampliada hasta ≥ 10 picks |
| O3 | (f) B1, justificación | 6b-C presentada como parada temprana con riesgo acotado, no como vía probable de promoción |
| J13 | (h) tabla de capital | Fuera de lista. Cap por clúster de 6b-C fijado en 10% de B (5 USDC), que B1 no definía y `Caps` exige |
| J14 | (f) Ciclo de vida, puntos 3 y 4 | Fuera de lista. Las posiciones abiertas conservan los caps de su modo; volver a vivo tras BACK\_TO\_PAPER exige 3 meses de datos nuevos. Ambos son necesarios para que C10 sea implementable |
| J15 | (c) 0004 | Fuera de lista. Trigger que impide borrar o editar `identity-v0`, de lo que depende la garantía "siempre hay una versión vigente" de C3 |

### Changelog 1.4.0

| ID | Sección | Resumen del cambio |
| --- | --- | --- |
| V | Cabecera | Versión 1.4.0 |
| 1.4/1 | (c) 0005 | Verificado que ninguna tabla referencia `positions` (no existen `clv` ni `settlements`); protocolo de migración con FKs y test del migrador |
| 1.4/2 | (f) M5; (c) 0005 | Base terminal `resolved_at − 1 h`; `clv_basis`; trigger que exime a la base terminal del suelo de 6 h |
| 1.4/3 | (c) 0005 | Cadena contigua de versiones de sesgo (una abierta, solo cierre, sin altas retroactivas); `identity-v0` como primer eslabón. Sustituye el trigger de solapes, `bias_fallback_log` y la alerta de 0004 |
| 1.4/4 | (f) Ciclo de vida | Revisión trimestral precomprometida en 8 filas con probabilidades de disparo; P4 por potencia en 6b ya no degrada |
| 1.4/C7 | Presupuesto: reversión y acoplamiento | Umbral `0.9 × cap_mensual − ahorro`; acoplamiento con X completo documentado (escalones fijos y Opus fuera si se llegó al 2) |
| 1.4/O1 | (f) B1 punto 3 y umbral | La parada temprana queda escrita como válvula de seguridad, no como gate |
| 1.4/O2 | (f) P5 | Techo de 6 meses en la ventana de la condición 2, con tabla. La fórmula literal de la revisión coincidía con la regla de la 1.3.0 y no cumplía su propósito |
| 1.4/S | 0; Presupuesto; (f) Volumen y concentración; (f) potencia de P4; (b) pipeline.select; (g) R9; P6; AC-M3 | cap\_mensual = 30 USD; 75 forecasts/mes; concentración en 2 categorías desde el mes 4; X solo en a desde el inicio; tabla de costes recalculada (22.84 / 26.33 / 19.35 USD) con corrección del 2.33 de la revisión a 3.49; tabla de potencia a 75/mes; escalera recalculada (7.20 USD el escalón 2; cuota 75 → 60) |
| J16 | Presupuesto: ejemplo de C7 | Fuera de lista. El ejemplo "gasto ≈ 21 no revierte" se etiqueta como válido con el tope de 25 de la 1.3.0, porque con 30 sí revierte |
| J17 | (f) M5 | Fuera de lista. Marca de P4 "contaminada" si los picks terminal\_1h superan el 10%, porque esa base mide cerca de la resolución |

### Changelog 1.4.1

| ID | Sección | Resumen del cambio |
| --- | --- | --- |
| V | Cabecera | Versión 1.4.1 |
| 1.4.1/1 | (f) Ciclo de vida | En 6b, P4 es advisory. El único gate trimestral sobre el pronóstico es P2; las filas 3–4 son válvulas de CLV negativo |
| 1.4.1/2 | Presupuesto: plan 1.4.0 | Aclarado que el escalón 1 se dispara con P > cap\_mensual (30) y no con 27 (reversión); margen de 3.67 USD. `cap_mensual` sigue en 30 |

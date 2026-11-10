# ADR-0002: Capas y niveles de importación

- Estado: Aceptada
- Fecha: 2026-11-09

## Contexto

La spec (a) define la cadena `core ← infra ← ingest/evidence ← analysis ← synthesis ← decision ←
ledger ← eval ← pipeline` y dice que un test de import la comprueba, pero no ubica `normalize`,
`rules` ni `cli`, ni dice si `ingest` y `evidence` pueden importarse entre sí.

## Decisión

Cada subpaquete de `pmsys` tiene un nivel entero y solo puede importar de niveles estrictamente
menores. Dos módulos del mismo nivel no pueden importarse entre sí.

| Nivel | Módulo | Nota |
| --- | --- | --- |
| 1 | `core` | errores, modelos, reloj, ids |
| 2 | `infra` | `db`, `http`, `llm` (un solo nivel: son módulos del mismo paquete) |
| 3 | `ingest` | hermana de `evidence`: se comunican por objetos de dominio |
| 4 | `normalize` | entre `ingest` y los niveles que usan `Market` |
| 5 | `rules`, `evidence` | los filtros no importan `decision`: reciben un contexto y devuelven un veredicto |
| 6 | `analysis` | |
| 7 | `synthesis` | |
| 8 | `decision` | |
| 9 | `ledger` | la spec lo llama `ledger`, no `execute` |
| 10 | `eval` | por encima de `ledger`, como en la cadena de la spec |
| 11 | `pipeline` | |
| 12 | `cli` | |

`config` no es un subpaquete: la configuración se lee de `config/*.toml` y `settings.toml`.

## Consecuencias

- `tests/unit/test_layering.py` aplica esta tabla. Un módulo nuevo debe añadirse a `LAYERS`.
- Se desvía de la tabla propuesta en la revisión en dos puntos, para respetar la spec (que gana si
  hay conflicto): `ledger` y `eval` no comparten nivel (la cadena de (a) pone `eval` sobre
  `ledger`) y `pipeline` tiene nivel propio. `db` y `http` quedan en `infra`, como en (a).

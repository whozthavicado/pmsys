# ADR-0002: Capas sin ubicar en la spec

- Estado: Propuesta (pendiente de confirmación del autor de la spec)
- Fecha: 2026-11-09

## Contexto

La spec (a) define la cadena de dependencias
`core ← infra ← ingest/evidence ← analysis ← synthesis ← decision ← ledger ← eval ← pipeline` y
dice que un test de import la comprueba. Pero el árbol incluye también `normalize/`, `rules/` y
`cli.py`, que no aparecen en la cadena, y no dice si `ingest` y `evidence` pueden importarse entre
sí.

## Decisión provisional

`tests/unit/test_layering.py` aplica la cadena tal cual está escrita: un módulo solo importa de
su capa o de una inferior, con `ingest` y `evidence` en la misma capa. `normalize`, `rules` y
`cli` no se restringen hasta que la spec los ubique.

## Consecuencias

Cuando la spec fije su posición, se añaden a `LAYERS` en el test y esta ADR pasa a Aceptada.

# ADR-0001: Convención de ramas

- Estado: Aceptada
- Fecha: 2026-11-09

## Contexto

El trabajo de la Fase 2 se divide en pasos (spec, "Orden de construcción") y cada paso en PRs
pequeños, uno por módulo.

## Por qué no existe una rama `fase2` (ni `fase-2` con `fase-2/paso-1`)

Un ref de Git es un fichero: `refs/heads/fase2` no puede ser a la vez el directorio que
`refs/heads/fase2/paso1` necesita. Git lo rechaza:

```text
fatal: cannot lock ref 'refs/heads/fase2/paso1': 'refs/heads/fase2' exists;
cannot create 'refs/heads/fase2/paso1'
```

Se intentó ya con `fase-2` y `fase-2/paso-1`, y se propuso `fase2` y `fase2/paso1`; los dos pares
chocan por el mismo motivo. Si una rama de fase tiene que convivir con ramas de paso, `fase2` solo
puede ser un prefijo (directorio), nunca una rama. No crees una rama `fase2`.

## Decisión

- `main` es la rama estable. Solo recibe cambios por PR; protegida por ruleset (sin force push ni
  borrado).
- `faseN/integracion`: rama de integración de la fase N (por ejemplo `fase2/integracion`).
- `faseN/pasoM`: rama de integración del paso M (por ejemplo `fase2/paso1`).
- `pM-<modulo>`: rama de trabajo de un PR (por ejemplo `p1-esqueleto`, `p1-migraciones`,
  `p1-http`). Se crea desde la rama del paso y se fusiona hacia ella.
- Un PR por módulo. Un módulo no se fusiona sin su test de aceptación en verde.
- Los PR de trabajo se fusionan con squash; los de integración (paso → fase → `main`) con
  merge commit para conservar el historial por módulo.
- Mensajes de commit: prefijo convencional (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

## Consecuencias

- La rama de cada PR indica el paso al que pertenece.
- Los nombres `fase-2`, `fase-2-paso-1` y `fase2` como rama ya no se usan.

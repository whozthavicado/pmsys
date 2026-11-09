# ADR-0001: Convención de ramas

- Estado: Aceptada
- Fecha: 2026-11-09

## Contexto

El trabajo de la Fase 2 se divide en pasos (spec, "Orden de construcción") y cada paso en PRs
pequeños, uno por módulo. Git no permite que existan a la vez una rama `fase-2` y otra
`fase-2/paso-1`: el nombre `fase-2` ya ocupa la ruta que la segunda necesitaría como directorio.

## Decisión

- `main` es la rama estable. Solo recibe cambios por PR; nadie hace push directo ni force push.
- `fase-N`: rama de integración de una fase (por ejemplo `fase-2`).
- `fase-N-paso-M`: rama de integración de un paso (por ejemplo `fase-2-paso-1`). El separador es
  un guion, nunca una barra, para evitar el conflicto de rutas descrito arriba.
- `pM-<modulo>`: rama de trabajo de un PR (por ejemplo `p1-esqueleto`, `p1-migraciones`,
  `p1-http`). Se crea desde la rama del paso y se fusiona hacia ella.
- Un PR por módulo. Un módulo no se fusiona sin su test de aceptación en verde.
- Los PR de trabajo se fusionan con squash; los de integración (paso → fase → `main`) con
  merge commit para conservar el historial por módulo.
- Mensajes de commit: prefijo convencional (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

## Consecuencias

- La rama de cada PR indica el paso al que pertenece.
- No hay forma de proteger `main` por ruleset mientras el repositorio sea privado en un plan
  gratuito; la regla "solo por PR" se cumple por disciplina hasta que cambie el plan.

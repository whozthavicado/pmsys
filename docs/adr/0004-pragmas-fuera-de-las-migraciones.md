# ADR-0004: Los PRAGMA no pertenecen a las migraciones

- Estado: Aceptada
- Fecha: 2026-11-09

## Contexto

El bloque DDL de la spec (c) empieza con `PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;`.
Ninguno de los dos tiene sentido dentro de una migración:

- `foreign_keys` es por conexión y no persiste, así que fijarlo en un script no afecta a las
  conexiones futuras. Además es un no-op dentro de una transacción, y el protocolo de migración
  de la 1.4.0 exige `foreign_keys = OFF` fuera de ella.
- `journal_mode = WAL` persiste en el fichero, pero es una propiedad de la base y no esquema, y
  no puede cambiarse dentro de una transacción.

## Decisión

`migrations/0001_init.sql` conserva el DDL de la spec sin esas dos líneas (lleva una cabecera que
remite a esta ADR). El reparto es:

- `infra.db.connect` fija `foreign_keys = ON` y `busy_timeout` en cada conexión.
- `infra.db.bootstrap` fija `journal_mode = WAL` y `synchronous = NORMAL` antes de migrar.
- `infra.db.SqliteDb.migrate` sigue el protocolo de la 1.4.0 (`foreign_keys = OFF` fuera de
  transacción, `BEGIN`, script, `foreign_key_check`, `COMMIT`, `foreign_keys = ON`).

Un test impide que vuelvan a aparecer `PRAGMA` en el código de cualquier migración, y otro
comprueba que el resto de cada archivo es idéntico, byte a byte, al bloque `sql` de la spec.

## Consecuencias

- Es un desvío mínimo y deliberado del texto de la spec (c); el esquema no cambia.
- Las migraciones 0002–0005 se copian tal cual de la spec.

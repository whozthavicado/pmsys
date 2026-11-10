# scripts/

## v2_sweep.py: cierre de V2 (dominio de `umaResolutionStatus`)

Solo lectura (GET). Hay que correrlo desde un entorno con acceso a `gamma-api.polymarket.com`
(el VPS); no corre en el entorno de desarrollo, cuyo proxy rechaza ese host.

```sh
uv sync --locked
uv run python scripts/v2_sweep.py --find-examples
```

Códigos de salida: `0` barrido completo, `2` abortado (forma de respuesta ambigua o cursor en
bucle), `3` incompleto (se alcanzó `--max-pages`; no sirve para cerrar V2).

Salida:

- `tests/fixtures/uma_status_values.json`: fixture de la spec. En ejecuciones repetidas conserva el
  primer `observado_en` y el ejemplo de cada valor.
- `reports/v2_sweep_<fecha>.json` (no versionado): recuentos abiertos/cerrados, nulos, campo
  ausente, ejemplos, páginas.
- `reports/uma_status_map.proposed.toml` (no versionado): **propuesta**. Los valores sin
  coincidencia exacta con un estado quedan como `REVISAR`. Una persona copia el resultado revisado
  a `config/uma_status_map.toml`; el script nunca escribe en `config/`.

Repetición diaria si el barrido no contiene ejemplos abiertos de `proposed` o `disputed` (máximo
14 días, spec V2). Ejemplo de cron en el VPS:

```cron
15 6 * * * cd /ruta/a/pmsys && uv run python scripts/v2_sweep.py --find-examples
```

Criterio de aceptación (spec V2): 100% de los valores observados mapeados, y al menos un ejemplo
real de `proposed` y otro de `disputed` (o constancia escrita a los 14 días).

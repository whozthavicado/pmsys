# scripts/

## v2_sweep.py: cierre de V2 (dominio de `umaResolutionStatus`)

Solo lectura (GET). Hay que correrlo desde un entorno con acceso a `gamma-api.polymarket.com`
(el VPS); no corre en el entorno de desarrollo, cuyo proxy rechaza ese host.

```sh
uv sync --locked
uv run python scripts/v2_sweep.py --find-examples
```

Códigos de salida: `0` barrido completo, `2` abortado (forma de respuesta ambigua, cursor en
bucle, o ya hay un estado guardado y no pasaste `--resume`), `3` incompleto (se alcanzó
`--max-pages` en alguna pasada; no sirve para cerrar V2), `4` interrumpido por la red (el estado
quedó guardado).

**Reanudar.** El barrido dura horas y Gamma a veces corta la respuesta. Cada 10 páginas y al
terminar cada pasada guarda `reports/v2_state.json` (cursor + contadores, escritura atómica). Tras
una caída: `uv run python scripts/v2_sweep.py --find-examples --resume` retoma desde ahí, con la
misma ventana de fechas de la corrida original, sin recontar. Además, si el cliente agota sus
reintentos, el script espera 60 s y reintenta la misma página hasta `--patience-min` (30 por
defecto) antes de rendirse. `--max-pages` es por pasada (20.000 por defecto).

Salida:

- `tests/fixtures/uma_status_values.json`: fixture de la spec. En ejecuciones repetidas conserva el
  primer `observado_en` y el ejemplo de cada valor.
- `tests/fixtures/uma_status_crosstab.json`: cruce (abierto/cerrado) por (valor, `null`, campo
  ausente). La ausencia del campo es un estado propio: un cerrado sin campo es un resuelto sin
  estado, no un abierto sin propuesta. Lleva `completo: false` si se alcanzó el tope de páginas.
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

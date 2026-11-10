# ADR-0005: Cliente HTTP, reintentos e idempotencia

- Estado: Aceptada
- Fecha: 2026-11-10

## Contexto

La spec (b) fija `HostPolicy`, la fórmula de backoff y que `RateLimited`, `UpstreamError` 5xx y
`UpstreamTimeout` se reintentan en `infra.http`. No dice qué pasa con `Retry-After` mayor que el
techo, con los 4xx, las redirecciones, los POST ni cómo se miden los límites por host.

## Decisión

- **Transporte inyectable** (`Transport`) sobre `urllib` de la biblioteca estándar: sin
  dependencias nuevas. No sigue redirecciones (una 3xx es `UpstreamError`) y exige `https`.
- **Backoff:** `uniform(0, min(max_delay, base * 2**attempt))`, como en la spec. `max_retries`
  reintentos, es decir `max_retries + 1` intentos.
- **`Retry-After`:** si llega en segundos, es un suelo del retraso. Si supera `max_delay_s`, se
  falla de inmediato con el error original (`RateLimited.retry_after_s` lo informa): bloquear un
  ciclo durante más que el techo no ayuda. La forma de fecha HTTP se trata como ausente.
- **Qué se reintenta:** 429, 5xx, timeouts y fallos de conexión (estos últimos como
  `UpstreamError(status=0)`). Cualquier otro 4xx y cualquier 3xx se propagan sin reintento. Un
  cuerpo 2xx que no es JSON es `SchemaDrift`.
- **Token bucket por host, empieza lleno**, capacidad `max_req`, recarga `max_req / window_s`.
  Los reintentos consumen tokens. Un host sin política es un error de programación (`ValueError`).
- **Idempotencia de POST:** la clave `Idempotency-Key = sha256("POST|url|json_canónico(body)")` es
  la misma en todos los reintentos de una llamada y en llamadas idénticas. **SIN VERIFICAR** que
  algún endpoint de Polymarket la respete: el paso 1 solo usa GET. Es una defensa, no una garantía.
- **Mensajes de error:** solo host y estado, nunca URL con parámetros, cabeceras ni cuerpo.
- **Fixtures:** `RecordingTransport` graba (solo cabeceras de respuesta `content-type` y
  `retry-after`; nunca las de la petición) y `ReplayTransport` sirve sin red; una petición no
  grabada falla en vez de caer a la red.

## Límites por defecto (al 50%, R8)

| Host | Política | Origen |
| --- | --- | --- |
| `gamma-api.polymarket.com` | 150 / 10 s | `/markets` 300 req/10 s, VERIFICADO |
| `clob.polymarket.com` | 7.500 / 10 s | general 15.000 req/10 s, VERIFICADO; por endpoint SIN VERIFICAR |
| `polymarket.com` (geoblock) | 5 / 10 s | SIN VERIFICAR (pendiente de Fase 2); conservador, no medido |
| `api.gdeltproject.org` | 1 / 10 s | 1 req/5 s, fuente secundaria SIN VERIFICAR |

## Consecuencias

- `core.errors` ya existe y `MigrationError` pasa a ser un `PmsysError`.
- `core.ids` aporta `idem_key` y `canonical_json` con la misma definición que la spec.
- Las fixtures de `tests/fixtures/http/` son sintéticas (host `api.example.test`); las grabaciones
  reales de Gamma y CLOB dependen de V2 y de un entorno con acceso a esos hosts.

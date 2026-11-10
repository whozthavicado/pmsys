# Fixtures HTTP

Formato de `pmsys.infra.replay` (un JSON por petición, nombre = `sha256(método|url)[:20]`).

Las de este directorio son **sintéticas** (`"synthetic": true`, host `api.example.test`): sirven para
probar el cliente y el replay. Las grabaciones reales de Gamma/CLOB se hacen con
`RecordingTransport` desde una red con acceso (la V2 corre en el VPS) y van en `tests/fixtures/`.

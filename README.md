# pmsys

Sistema cuantitativo de picks para Polymarket. El contrato del proyecto es
[`docs/spec.md`](docs/spec.md) (v1.4.1). Si el código contradice la spec, gana la spec.

## Desarrollo

Requiere Python 3.12 y [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

Los tests corren con la red bloqueada (`pytest-socket`). Los secretos solo se leen de variables
de entorno; ver `.env.example`.

Las decisiones de diseño no triviales están en [`docs/adr/`](docs/adr/).

## Licencia

[MIT](LICENSE). Esto no es asesoramiento financiero: el sistema es un proyecto de investigación.

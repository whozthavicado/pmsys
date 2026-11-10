"""Grabación y reproducción de respuestas HTTP como fixtures JSON.

``RecordingTransport`` envuelve un transporte real y guarda cada intercambio; ``ReplayTransport``
sirve lo grabado sin red. Un fichero por petición, nombrado por ``sha256(método|url)``.
Solo se conservan las cabeceras de respuesta de una lista blanca (nada de cookies ni tokens), y
nunca se guardan las cabeceras de la petición.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pmsys.core.ids import idem_key
from pmsys.infra.http import Transport, TransportResponse

KEPT_RESPONSE_HEADERS = frozenset({"content-type", "retry-after"})


class FixtureNotFound(LookupError):
    """Se pidió algo que no está grabado: en un test, es un fallo, no un fallback a la red."""


class FixtureResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: int
    headers: dict[str, str] = {}
    body: str  # texto UTF-8 (los endpoints son JSON)


class Fixture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: str
    url: str
    recorded_at: str | None = None  # ISO-8601 UTC; None en las sintéticas
    synthetic: bool = False
    response: FixtureResponse


def fixture_name(method: str, url: str) -> str:
    return f"{idem_key(method.upper(), url)[:20]}.json"


class RecordingTransport:
    def __init__(self, inner: Transport, directory: Path, *, recorded_at: str) -> None:
        self._inner = inner
        self._dir = directory
        self._recorded_at = recorded_at

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> TransportResponse:
        resp = self._inner.send(method, url, headers=headers, body=body, timeout_s=timeout_s)
        fx = Fixture(
            method=method.upper(),
            url=url,
            recorded_at=self._recorded_at,
            response=FixtureResponse(
                status=resp.status,
                headers={k: v for k, v in resp.headers.items() if k in KEPT_RESPONSE_HEADERS},
                body=resp.body.decode("utf-8"),
            ),
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / fixture_name(method, url)
        path.write_text(fx.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return resp


class ReplayTransport:
    def __init__(self, directory: Path) -> None:
        self._fixtures: dict[tuple[str, str], Fixture] = {}
        for path in sorted(directory.glob("*.json")):
            fx = Fixture.model_validate(json.loads(path.read_text(encoding="utf-8")))
            self._fixtures[(fx.method, fx.url)] = fx
        self.requests: list[tuple[str, str]] = []

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> TransportResponse:
        key = (method.upper(), url)
        self.requests.append(key)
        fx = self._fixtures.get(key)
        if fx is None:
            raise FixtureNotFound(f"sin fixture para {key[0]} {key[1]}")
        return TransportResponse(
            status=fx.response.status,
            headers=dict(fx.response.headers),
            body=fx.response.body.encode("utf-8"),
        )

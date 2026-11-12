"""Cliente HTTP con backoff + jitter, token bucket por host e idempotencia (spec 1.4.1, (b)).

Todo lo que toca el mundo exterior es inyectable: ``Transport`` (red), ``Timer`` (reloj y sleep)
y ``uniform`` (jitter). Los tests no abren sockets (pytest-socket los bloquea).
"""

from __future__ import annotations

import http.client
import json
import random
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import SplitResult, urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from pmsys.core.errors import (
    PmsysError,
    RateLimited,
    SchemaDrift,
    UpstreamError,
    UpstreamTimeout,
)
from pmsys.core.ids import canonical_json, idem_key
from pmsys.core.jsontypes import JsonValue

IDEMPOTENCY_HEADER = "Idempotency-Key"
USER_AGENT = "pmsys/0.1"


class HostPolicy(BaseModel):
    """Política por host: token bucket y reintentos."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str
    max_req: int = Field(gt=0)
    window_s: float = Field(gt=0)
    max_retries: int = Field(default=5, ge=0)
    base_delay_s: float = Field(default=1.0, ge=0)
    max_delay_s: float = Field(default=60.0, ge=0)


# Token bucket al 50% del límite oficial (R8). Ver ADR-0005 para el origen de cada cifra.
DEFAULT_POLICIES: tuple[HostPolicy, ...] = (
    # /markets: 300 req/10 s (VERIFICADO) -> 150. El general de Gamma (4.000/10 s) queda holgado.
    HostPolicy(host="gamma-api.polymarket.com", max_req=150, window_s=10.0),
    # General 15.000 req/10 s (VERIFICADO) -> 7.500. Límites por endpoint: SIN VERIFICAR.
    HostPolicy(host="clob.polymarket.com", max_req=7500, window_s=10.0),
    # Límite del geoblock: SIN VERIFICAR (pendiente de Fase 2). Valor conservador, no medido.
    HostPolicy(host="polymarket.com", max_req=5, window_s=10.0),
    # 1 req/5 s (fuente secundaria, SIN VERIFICAR) -> 1 req/10 s.
    HostPolicy(host="api.gdeltproject.org", max_req=1, window_s=10.0),
)


class Timer(Protocol):
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class SystemTimer:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)  # claves en minúsculas
    body: bytes = b""


class TransportTimeout(Exception):
    """El transporte agotó el tiempo de espera."""


class TransportError(Exception):
    """Fallo de conexión sin respuesta HTTP (DNS, conexión rechazada, TLS...)."""


class Transport(Protocol):
    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> TransportResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class UrllibTransport:
    """Transporte real con la biblioteca estándar: sin dependencias ni redirecciones."""

    def __init__(self, opener: urllib.request.OpenerDirector | None = None) -> None:
        self._opener = opener or urllib.request.build_opener(_NoRedirect)

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> TransportResponse:
        req = urllib.request.Request(url, data=body, headers=dict(headers), method=method)  # noqa: S310 - https validado por el cliente
        try:
            return self._exchange(req, timeout_s)
        except TimeoutError as exc:
            raise TransportTimeout from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError | socket.timeout):
                raise TransportTimeout from exc
            raise TransportError from exc
        except (OSError, http.client.HTTPException) as exc:
            # HTTPException cubre una respuesta cortada a media lectura
            # (IncompleteRead) o una conexión cerrada sin respuesta: no es un
            # OSError, pero es tan transitorio como uno y se reintenta igual.
            raise TransportError from exc

    def _exchange(self, req: urllib.request.Request, timeout_s: float) -> TransportResponse:
        try:
            with self._opener.open(req, timeout=timeout_s) as resp:
                return TransportResponse(
                    status=resp.getcode() or 0,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    body=resp.read(),
                )
        except urllib.error.HTTPError as exc:
            # Un error HTTP sigue siendo una respuesta; leer su cuerpo también
            # puede cortarse, y eso lo atrapa `send`.
            return TransportResponse(
                status=exc.code,
                headers={k.lower(): v for k, v in exc.headers.items()},
                body=exc.read(),
            )


class HttpClient(Protocol):
    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonValue: ...
    def post_json(self, url: str, body: JsonValue) -> JsonValue: ...


_EPS = 1e-9


class TokenBucket:
    """Capacidad ``max_req``, recarga ``max_req / window_s`` por segundo. Empieza lleno."""

    def __init__(self, policy: HostPolicy, timer: Timer) -> None:
        self._capacity = float(policy.max_req)
        self._rate = policy.max_req / policy.window_s
        self._timer = timer
        self._tokens = self._capacity
        self._last = timer.monotonic()

    def acquire(self) -> None:
        while True:
            now = self._timer.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens >= 1.0 - _EPS:  # tolerancia: evita esperas de 0 s por redondeo
                self._tokens = max(0.0, self._tokens - 1.0)
                return
            self._timer.sleep((1.0 - self._tokens) / self._rate)


def parse_retry_after(value: str | None) -> float | None:
    """Solo la forma en segundos; una fecha HTTP o un valor inválido cuenta como ausente."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 and seconds != float("inf") else None


def backoff_delay(
    policy: HostPolicy, attempt: int, uniform: Callable[[float, float], float]
) -> float:
    """``uniform(0, min(max_delay, base * 2**attempt))`` (full jitter)."""
    ceiling = min(policy.max_delay_s, policy.base_delay_s * 2.0**attempt)
    return uniform(0.0, ceiling)


class RetryingHttpClient:
    def __init__(
        self,
        transport: Transport,
        policies: Mapping[str, HostPolicy] | None = None,
        *,
        timer: Timer | None = None,
        uniform: Callable[[float, float], float] = random.uniform,
        headers: Mapping[str, str] | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self._transport = transport
        self._policies = dict(policies or {p.host: p for p in DEFAULT_POLICIES})
        self._timer = timer or SystemTimer()
        self._uniform = uniform
        self._headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        self._timeout_s = timeout_s
        self._buckets: dict[str, TokenBucket] = {}

    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> JsonValue:
        full = f"{url}?{urlencode(params)}" if params else url
        return self._request("GET", full, None, {})

    def post_json(self, url: str, body: JsonValue) -> JsonValue:
        # La misma clave en todos los reintentos: si el servidor la respeta, no duplica efectos.
        payload = canonical_json(body)
        key = idem_key("POST", url, payload)
        headers = {"Content-Type": "application/json", IDEMPOTENCY_HEADER: key}
        return self._request("POST", url, payload.encode("utf-8"), headers)

    # ------------------------------------------------------------------ internals

    def _bucket(self, parts: SplitResult) -> tuple[HostPolicy, TokenBucket]:
        host = parts.hostname or ""
        policy = self._policies.get(host)
        if policy is None:
            raise ValueError(f"host sin política configurada: {host!r}")
        bucket = self._buckets.get(host)
        if bucket is None:
            bucket = self._buckets[host] = TokenBucket(policy, self._timer)
        return policy, bucket

    def _request(
        self, method: str, url: str, body: bytes | None, extra: Mapping[str, str]
    ) -> JsonValue:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise ValueError("solo se admiten URLs https")
        policy, bucket = self._bucket(parts)
        host = policy.host
        headers = {**self._headers, **extra}

        for attempt in range(policy.max_retries + 1):
            bucket.acquire()
            retry_after: float | None = None
            failure: PmsysError
            try:
                resp = self._transport.send(
                    method, url, headers=headers, body=body, timeout_s=self._timeout_s
                )
            except TransportTimeout:
                failure = UpstreamTimeout(host=host)
            except TransportError:
                failure = UpstreamError(host=host, status=0)
            else:
                if 200 <= resp.status < 300:
                    return _decode(host, resp.body)
                retry_after = parse_retry_after(resp.headers.get("retry-after"))
                if resp.status == 429:
                    failure = RateLimited(host=host, retry_after_s=retry_after)
                elif resp.status >= 500:
                    failure = UpstreamError(host=host, status=resp.status)
                else:
                    raise UpstreamError(host=host, status=resp.status)

            if attempt == policy.max_retries:
                raise failure
            delay = backoff_delay(policy, attempt, self._uniform)
            if retry_after is not None:
                if retry_after > policy.max_delay_s:
                    raise failure  # esperar más que el techo no tiene sentido en un ciclo
                delay = max(delay, retry_after)
            self._timer.sleep(delay)
        raise AssertionError("inalcanzable")  # pragma: no cover


def _decode(host: str, raw: bytes) -> JsonValue:
    try:
        value: JsonValue = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SchemaDrift(source=host, field="body") from exc
    return value

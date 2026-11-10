"""Fakes para probar infra.http sin red."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

from pmsys.infra.http import (
    HostPolicy,
    TransportError,
    TransportResponse,
    TransportTimeout,
)

HOST = "api.example.test"
BASE = f"https://{HOST}"


class FakeTimer:
    """Reloj monótono falso: ``sleep`` avanza el tiempo y lo registra."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class Sent:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None


@dataclass
class ScriptedTransport:
    """Responde en orden con lo programado; una excepción programada se lanza."""

    script: deque[TransportResponse | Exception]
    sent: list[Sent] = field(default_factory=list)

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> TransportResponse:
        self.sent.append(Sent(method, url, dict(headers), body))
        item = self.script.popleft()
        if isinstance(item, Exception):
            raise item
        return item


def ok(body: str = '{"ok":true}') -> TransportResponse:
    return TransportResponse(status=200, body=body.encode())


def status(code: int, **headers: str) -> TransportResponse:
    return TransportResponse(status=code, headers=headers, body=b"{}")


def script(*items: TransportResponse | Exception) -> ScriptedTransport:
    return ScriptedTransport(deque(items))


def policy(**kw: float) -> HostPolicy:
    base: dict[str, float] = {"max_req": 1000, "window_s": 1.0, "max_retries": 3}
    base.update(kw)
    return HostPolicy.model_validate({"host": HOST, **base})


TIMEOUT = TransportTimeout()
CONN_ERROR = TransportError()

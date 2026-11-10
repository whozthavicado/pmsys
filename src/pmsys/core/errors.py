"""Jerarquía de errores (spec 1.4.1, (b) «Errores comunes»).

Los mensajes nunca incluyen URLs con parámetros, cabeceras ni cuerpos: solo host y estado.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal


class PmsysError(Exception):
    """Raíz de todos los errores del sistema."""


class RateLimited(PmsysError):
    def __init__(self, *, host: str, retry_after_s: float | None = None) -> None:
        super().__init__(f"{host}: límite de peticiones (429)")
        self.host = host
        self.retry_after_s = retry_after_s


class UpstreamError(PmsysError):
    def __init__(self, *, host: str, status: int) -> None:
        super().__init__(f"{host}: respuesta HTTP {status}")
        self.host = host
        self.status = status


class UpstreamTimeout(PmsysError):
    def __init__(self, *, host: str) -> None:
        super().__init__(f"{host}: tiempo de espera agotado")
        self.host = host


class SchemaDrift(PmsysError):
    """Falta un campo esperado o cambió de tipo."""

    def __init__(self, *, source: str, field: str) -> None:
        super().__init__(f"{source}: esquema inesperado en «{field}»")
        self.source = source
        self.field = field


class NormalizationError(PmsysError):
    def __init__(self, *, market_id: str, field: str) -> None:
        super().__init__(f"mercado {market_id}: no se pudo normalizar «{field}»")
        self.market_id = market_id
        self.field = field


class BudgetExceeded(PmsysError):
    def __init__(self, *, scope: Literal["day", "month"], spent_usd: float) -> None:
        super().__init__(f"presupuesto {scope} excedido: {spent_usd:.2f} USD")
        self.scope = scope
        self.spent_usd = spent_usd


class LlmSchemaViolation(PmsysError):
    """Tras 2 reintentos."""

    def __init__(self, *, task: str, attempts: int) -> None:
        super().__init__(f"{task}: salida fuera de esquema tras {attempts} intentos")
        self.task = task
        self.attempts = attempts


class InsufficientEvidence(PmsysError):
    """Termina en «no operar»."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(f"evidencia insuficiente: {reason}")
        self.reason = reason


class InsufficientReferenceClass(PmsysError):
    def __init__(self, *, n: int) -> None:
        super().__init__(f"clase de referencia insuficiente: n={n} < 20")
        self.n = n


class IdempotencyConflict(PmsysError):
    def __init__(self, *, key: str) -> None:
        super().__init__(f"conflicto de idempotencia: {key}")
        self.key = key


class SystemStopped(PmsysError):
    """Solo en la ruta de ejecución real (M4)."""

    def __init__(self, *, since: datetime, reason: str) -> None:
        super().__init__(f"sistema detenido desde {since.isoformat()}: {reason}")
        self.since = since
        self.reason = reason


class CategoryInvariantError(PmsysError):
    """D6."""

    def __init__(self, *, market_id: str) -> None:
        super().__init__(f"mercado {market_id}: invariante de categoría violado")
        self.market_id = market_id


class SelectionIncomplete(PmsysError):
    """D3."""

    def __init__(self, *, tag_id: int) -> None:
        super().__init__(f"enumeración incompleta del tag {tag_id}")
        self.tag_id = tag_id

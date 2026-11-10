"""Claves de idempotencia (sha256) y JSON canónico."""

from __future__ import annotations

import hashlib
import json

from pmsys.core.jsontypes import JsonValue


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: JsonValue) -> str:
    """Misma definición que la spec (D2): claves ordenadas, sin espacios, sin escapar unicode."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def idem_key(*parts: str) -> str:
    """``sha256("a|b|c")``, el formato de ``idem_key`` y ``rank_key`` de la spec."""
    return sha256_hex("|".join(parts))

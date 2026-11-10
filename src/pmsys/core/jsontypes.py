"""Tipo JSON recursivo para las fronteras de módulo (sin ``Any``)."""

from __future__ import annotations

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None

"""Stable, JSON-serializable public errors."""
from __future__ import annotations
from typing import Any

class NamingError(ValueError):
    def __init__(self, code: str, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or []

    def as_dict(self) -> dict[str, Any]:
        return {'code': self.code, 'message': str(self), 'details': self.details}

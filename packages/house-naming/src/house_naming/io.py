"""Strict, bounded JSON I/O: duplicate keys and non-finite numbers are errors."""
from __future__ import annotations
import json
import math
from typing import Any
from .errors import NamingError

def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise NamingError('duplicate-json-key', f'Duplicate JSON key: {key!r}')
        obj[key] = value
    return obj

def _constant(value: str) -> Any:
    raise NamingError('non-finite-number', f'Non-finite JSON number: {value}')

def _float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        _constant(text)
    return value

def loads(text: str | bytes, *, max_bytes: int = 16_777_216) -> Any:
    size = len(text.encode('utf-8')) if isinstance(text, str) else len(text)
    if size > max_bytes:
        raise NamingError('input-too-large', f'Input exceeds {max_bytes} bytes')
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
    except NamingError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise NamingError('invalid-json', 'Input is not valid supported JSON') from exc

def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + '\n'

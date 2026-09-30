"""Strict, bounded JSON I/O: duplicate keys and non-finite numbers are errors."""
from __future__ import annotations
import json
import math
from pathlib import Path
import sys
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


def read_json(path: str | Path, *, max_bytes: int = 65_536) -> Any:
    """Read bounded strict JSON from a file, or stdin when the path is '-'."""
    if str(path) == '-':
        payload = sys.stdin.buffer.read(max_bytes + 1)
    else:
        with Path(path).open('rb') as stream:
            payload = stream.read(max_bytes + 1)
    return loads(payload, max_bytes=max_bytes)

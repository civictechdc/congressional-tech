"""Retain the upstream bytes separately from the small GPO CSV.

Cached replay never invents a retrieval time. Source rosters remain XML evidence;
being named in MODS is not an assertion of attendance at a hearing.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path


def observation(data: bytes, url: str, media_type: str, *, retrieved_at=None):
    try:
        body, encoding = data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        body, encoding = base64.b64encode(data).decode('ascii'), 'base64'
    return {
        'url': url, 'media_type': media_type, 'sha256': hashlib.sha256(data).hexdigest(),
        'body': body, 'body_encoding': encoding, 'retrieved_at': retrieved_at,
        'acquisition': 'http' if retrieved_at else 'cached-replay',
    }


def body_bytes(value):
    body = value['body']
    if value['body_encoding'] not in ('utf-8', 'base64'):
        raise ValueError(f"Unsupported upstream body encoding: {value['body_encoding']}")
    data = body.encode('utf-8') if value['body_encoding'] == 'utf-8' else base64.b64decode(body, validate=True)
    if hashlib.sha256(data).hexdigest() != value['sha256']:
        raise ValueError(f"Retained upstream digest mismatch: {value['url']}")
    return data


def read(path: Path | None):
    if path is None or not Path(path).exists():
        return {}
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        result = {}
        for line in stream:
            value = json.loads(line)
            package = value['package_id']
            if package in result:
                raise ValueError(f'Duplicate GPO evidence package: {package}')
            for field in ('mods', 'failed_mods'):
                if value.get(field):
                    body_bytes(value[field])
            for item in value.get('transcripts', {}).values():
                body_bytes(item)
            result[package] = value
        return result


def write(values, path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    # Stable gzip headers keep a replay with identical data byte-identical.
    with temporary.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as stream:
        for package in sorted(values):
            stream.write((json.dumps(values[package], ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n').encode())
    temporary.replace(path)

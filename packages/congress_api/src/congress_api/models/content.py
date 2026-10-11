"""Exact upstream bytes alongside typed interpretation, using the GPO body shape."""
import base64
import hashlib
import codecs
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, model_validator

from .base import SourceModel


@dataclass(frozen=True)
class CapturedBody:
    """Internal acquired bytes; receipts retain the existing RawContent shape."""
    data: bytes
    media_type: str
    sha256: str = field(init=False)
    body_encoding: str = field(init=False)

    def __post_init__(self):
        try:
            self.data.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeDecodeError:
            encoding = 'base64'
        object.__setattr__(self, 'body_encoding', encoding)
        object.__setattr__(self, 'sha256', hashlib.sha256(self.data).hexdigest())

    @classmethod
    def from_bytes(cls, data, media_type):
        return cls(data, media_type)

    def source_dict(self):
        return dict(media_type=self.media_type, body=self,
                    body_encoding=self.body_encoding, sha256=self.sha256)


@dataclass(frozen=True)
class CapturedFile:
    """Owned native response file; never construct this from serialized input."""
    path: Path
    media_type: str
    sha256: str = field(init=False)
    body_encoding: str = field(init=False)
    size: int = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'path', Path(self.path))
        digest, size = hashlib.sha256(), 0
        decoder = codecs.getincrementaldecoder('utf-8')()
        with self.path.open('rb') as source:
            while chunk := source.read(1024**2):
                digest.update(chunk)
                size += len(chunk)
                if decoder is not None:
                    try:
                        decoder.decode(chunk)
                    except UnicodeDecodeError:
                        decoder = None
        if decoder is not None:
            try:
                decoder.decode(b'', final=True)
            except UnicodeDecodeError:
                decoder = None
        object.__setattr__(self, 'size', size)
        object.__setattr__(self, 'sha256', digest.hexdigest())
        object.__setattr__(self, 'body_encoding', 'utf-8' if decoder is not None else 'base64')

    def __len__(self):
        return self.size

    def prefix(self, limit=8192):
        with self.path.open('rb') as source:
            return source.read(limit)

    def read_bytes(self):
        return self.path.read_bytes()

    def close(self):
        self.path.unlink(missing_ok=True)

    def source_dict(self):
        return dict(media_type=self.media_type, body=self,
                    body_encoding=self.body_encoding, sha256=self.sha256)


def content_body(content):
    """Validate metadata while preserving an acquired file or byte payload."""
    body = content.get('body')
    if isinstance(body, (CapturedBody, CapturedFile)):
        if any(content.get(key) != getattr(body, key)
               for key in ('media_type', 'body_encoding', 'sha256')):
            raise ValueError('Captured body metadata mismatch')
        return body if isinstance(body, CapturedFile) else body.data
    return RawContent.model_validate(content).body_bytes()


def content_bytes(content):
    """Materialize only for consumers that require a bounded byte payload."""
    body = content_body(content)
    return body.read_bytes() if isinstance(body, CapturedFile) else body


def capture_files(value):
    """Find owned files without retaining their surrounding provider payloads."""
    if isinstance(value, CapturedFile):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from capture_files(child)
    elif isinstance(value, list):
        for child in value:
            yield from capture_files(child)


def close_capture_files(value):
    """Release owned files, including prior attempts, after all readers finish."""
    for body in capture_files(value):
        body.close()


class RawContent(SourceModel):
    media_type: str
    body: str
    body_encoding: Literal['utf-8', 'base64']
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

    @classmethod
    def from_bytes(cls, data: bytes, media_type: str) -> 'RawContent':
        try:
            body, encoding = data.decode('utf-8'), 'utf-8'
        except UnicodeDecodeError:
            body, encoding = base64.b64encode(data).decode('ascii'), 'base64'
        return cls(media_type=media_type, body=body, body_encoding=encoding,
                   sha256=hashlib.sha256(data).hexdigest())

    def body_bytes(self) -> bytes:
        return self.body.encode('utf-8') if self.body_encoding == 'utf-8' else base64.b64decode(self.body, validate=True)

    @model_validator(mode='after')
    def verify_body(self):
        if hashlib.sha256(self.body_bytes()).hexdigest() != self.sha256:
            raise ValueError('Retained upstream digest mismatch: body does not match its SHA-256')
        return self

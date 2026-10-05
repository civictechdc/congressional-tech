"""Exact upstream bytes alongside typed interpretation, using the GPO body shape."""
import base64
import hashlib
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


def content_bytes(content):
    """Validate serialized input, or reuse bytes verified during acquisition."""
    body = content.get('body')
    if isinstance(body, CapturedBody):
        if any(content.get(key) != getattr(body, key)
               for key in ('media_type', 'body_encoding', 'sha256')):
            raise ValueError('Captured body metadata mismatch')
        return body.data
    return RawContent.model_validate(content).body_bytes()


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

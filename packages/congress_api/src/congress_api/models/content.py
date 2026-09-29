"""Exact upstream bytes alongside typed interpretation, using the GPO body shape."""
import base64
import hashlib
from typing import Literal

from pydantic import Field, model_validator

from .base import SourceModel


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

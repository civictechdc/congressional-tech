"""Retain original model responses before transcript interpretation."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from congress_api.models.content import RawContent
from congress_api.models.transcription import GeminiResponseCapture


def retain_response(response, directory: Path, *, model: str, start: float, end: float, attempt: int):
    """Save the SDK's HTTP response text and generated text before interpretation.

    The SDK supplies decoded HTTP text, not original transport bytes. A missing
    HTTP body remains explicitly absent; the generated text is not its substitute.
    """
    observed = dt.datetime.now(dt.timezone.utc)
    http = getattr(response, 'sdk_http_response', None)
    body = getattr(http, 'body', None)
    generated = response.text
    capture = GeminiResponseCapture(
        model=model, start=start, end=end, observed_at=observed.isoformat(),
        response=RawContent.from_bytes(body.encode('utf-8'), 'application/json') if body is not None else None,
        generated=RawContent.from_bytes(generated.encode('utf-8'), 'application/json') if generated is not None else None,
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{start:g}-{end:g}-{observed.strftime("%Y%m%dT%H%M%S%fZ")}-{attempt}.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(capture.model_dump_json(by_alias=True), encoding='utf-8')
    temporary.replace(path)

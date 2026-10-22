"""Retain original model responses before transcript interpretation."""

from __future__ import annotations

from collections.abc import Sequence
import datetime as dt
import json
from pathlib import Path

from congress_shared.custody import write_atomic_bytes

from congress_api.models.content import RawContent
from congress_api.models.transcription import GeminiResponseCapture
from congress_api.retention.weekly_tables import WeeklyRetentionTables, transcript_to_row


def retain_response(
    response,
    directory: Path,
    *,
    model: str,
    start: float,
    end: float,
    attempt: int,
    weekly_tables: WeeklyRetentionTables | None = None,
):
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
    stem = f'{start:g}-{end:g}-{observed.strftime("%Y%m%dT%H%M%S%fZ")}-{attempt}'
    path = directory / f'{stem}.json'
    payload_bytes = capture.model_dump_json(by_alias=True).encode('utf-8')
    write_atomic_bytes(
        path,
        payload_bytes,
        temp_path=path.with_suffix('.tmp'),
    )
    if weekly_tables is not None:
        weekly_tables.upsert_rows(
            "transcripts",
            [transcript_to_row(stem, json.loads(payload_bytes.decode("utf-8")))],
        )


def read_captures(
    weekly_tables: WeeklyRetentionTables,
    *,
    capture_ids: Sequence[str] | None = None,
) -> dict[str, dict]:
    """Read retained Gemini response captures from the incremental ``transcripts`` table."""
    if capture_ids is not None:
        arrow_table = weekly_tables.read_keys("transcripts", capture_ids, key="capture_id")
        return {
            row["capture_id"]: json.loads(row["payload_json"])
            for row in arrow_table.to_pylist()
        }
    return {
        row["capture_id"]: json.loads(row["payload_json"])
        for row in weekly_tables.iter_rows("transcripts", columns=("capture_id", "payload_json"))
    }

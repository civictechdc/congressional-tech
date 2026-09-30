"""Validate generated transcript JSON while preserving unknown values."""

from __future__ import annotations

from congress_api.models.transcription import GeminiTranscriptResponse


def parse_generated_response(text: str) -> GeminiTranscriptResponse:
    """Validate model-produced JSON without dropping unknown fields or labels."""
    return GeminiTranscriptResponse.model_validate_json(text)

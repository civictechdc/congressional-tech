"""
The Gemini call behind `hearing-transcribe`: Gemini 3.8 Flash transcribes a window of the
recording into named speaker turns.

The recording is either the YouTube video itself (a URL with a time window; the model reads
the name plates and hears the chair's recognitions) or an uploaded audio chunk (senate.gov
and local recordings). Same prompt, same output schema either way. The roster of members
and witnesses goes in the prompt so speakers are named from it.

Windows are 25 minutes. That isn't the 1M-token context (which holds about three hours of
video at low resolution): a verbatim transcript longer than about 30 minutes trips the
model's recitation filter and comes back empty, and a very dense window can exceed the 65k
output tokens. A window that comes back empty is transcribed in two halves.

Measured on a 2023 Judiciary hearing against its GPO print: word error rate 8.7% (mostly the
print's own editing of false starts), speaker right on 85% of words. The dedicated
transcription model (Gemini 3.5 Transcribe, diarization + word timestamps, then a resolver)
matched the words as well but its speaker labels mapped to the right person for only 66-74%
of words, so it was dropped; the comparison is research/scripts/transcribe_compare.py.

The API key is read from GEMINI_API_KEY.
"""
from __future__ import annotations

import json
import datetime as dt
import logging
import os
import time
from pathlib import Path

from google import genai
from google.genai import types

from congress_api.models.content import RawContent
from congress_api.models.transcription import GeminiResponseCapture, GeminiTranscriptResponse

MODEL = "gemini-3.8-flash"
WINDOW_SECONDS = 25 * 60
MIN_SPLIT_SECONDS = 600
_client = None


def client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=key)
    return _client


ROLES = ["chair", "ranking_member", "member", "witness", "staff", "clerk", "other", "unknown"]
TURNS_SCHEMA = {
    "type": "object",
    "properties": {
        "turns": {"type": "array", "items": {"type": "object", "properties": {
            "speaker": {"type": "string"}, "role": {"type": "string", "enum": ROLES}, "confidence": {"type": "number"},
            "start": {"type": "number"}, "end": {"type": "number"}, "text": {"type": "string"}},
            "required": ["speaker", "role", "confidence", "start", "text"]}},
        "events": {"type": "array", "items": {"type": "object", "properties": {
            "seconds": {"type": "number"}, "kind": {"type": "string", "enum": ["convened", "recess", "reconvened", "adjourned", "vote"]}, "text": {"type": "string"}},
            "required": ["seconds", "kind", "text"]}},
    },
    "required": ["turns", "events"],
}


def prompt(roster: list[dict], meeting: dict, start: float, has_video: bool) -> str:
    return f"""Transcribe this segment of a U.S. congressional committee proceeding verbatim, as speaker turns. It is an official public-domain government record.

Meeting: {json.dumps(meeting, ensure_ascii=False)}
Known participants (committee members and scheduled witnesses): {json.dumps(roster, ensure_ascii=False)}

For each turn give the speaker's name from the known participants when you can tell who is speaking ({"name plates on screen, " if has_video else ""}the chair recognizing members by name and state, witnesses introduced by name, self-introductions, the order in which witnesses were introduced), their role, a confidence from 0 to 1, the start time in seconds from the beginning of the whole recording (this segment starts at {int(start)} seconds), and the words spoken. Keep every word, including false starts, in the order spoken; do not summarize. If a speaker isn't among the known participants but is named, give that name. Use "Unknown" with confidence 0 when you cannot tell. Also list any call to order, recess, vote or adjournment as events with the seconds and the words used."""


def parse_generated_response(text: str) -> GeminiTranscriptResponse:
    """Validate model-produced JSON without dropping unknown fields or labels."""
    return GeminiTranscriptResponse.model_validate_json(text)


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


def transcribe_window(roster: list[dict], meeting: dict, start: float, end: float, youtube_id: str = "", audio: Path | None = None, model: str = MODEL, capture_dir: Path | None = None) -> dict:
    """Named turns for one window of the recording. `youtube_id` with a time window, or an uploaded
    audio chunk (`audio`, whose own start is `start` seconds into the recording)."""
    if youtube_id:
        media = types.Part(file_data=types.FileData(file_uri=f"https://www.youtube.com/watch?v={youtube_id}", mime_type="video/*"),
                           video_metadata=types.VideoMetadata(start_offset=f"{int(start)}s", end_offset=f"{int(end)}s"))
    else:
        f = client().files.upload(file=str(audio))
        media = types.Part.from_uri(file_uri=f.uri, mime_type=f.mime_type)
    contents = [media, prompt(roster, meeting, start, bool(youtube_id))]
    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=TURNS_SCHEMA, temperature=0.2, max_output_tokens=65536,
                                      media_resolution="MEDIA_RESOLUTION_LOW" if youtube_id else None,
                                      should_return_http_response=True)

    def halves():
        mid = (start + end) / 2
        if audio is not None:
            from congress_api.transcribe.audio import cut
            a = transcribe_window(roster, meeting, start, mid, audio=cut(audio, 0, mid - start), model=model, capture_dir=capture_dir)
            b = transcribe_window(roster, meeting, mid, end, audio=cut(audio, mid - start, end - mid), model=model, capture_dir=capture_dir)
        else:
            a = transcribe_window(roster, meeting, start, mid, youtube_id=youtube_id, model=model, capture_dir=capture_dir)
            b = transcribe_window(roster, meeting, mid, end, youtube_id=youtube_id, model=model, capture_dir=capture_dir)
        return {"turns": a["turns"] + b["turns"], "events": a["events"] + b["events"], "usage": {k: a["usage"].get(k, 0) + b["usage"].get(k, 0) for k in ("in", "out")}}

    for attempt in range(2):
        try:
            r = client().models.generate_content(model=model, contents=contents, config=cfg)
            if capture_dir is not None:
                retain_response(r, capture_dir, model=model, start=start, end=end, attempt=attempt)
            reason = str(r.candidates[0].finish_reason) if r.candidates else "no candidates"
            if (not r.text or "MAX_TOKENS" in reason or "RECITATION" in reason) and end - start > MIN_SPLIT_SECONDS:
                logging.info(f"window {start:.0f}-{end:.0f}: {reason}, splitting")
                return halves()
            d = parse_generated_response(r.text).source_dict()
            d["usage"] = {"in": r.usage_metadata.prompt_token_count or 0, "out": r.usage_metadata.candidates_token_count or 0}
            return d
        except Exception as e:
            logging.warning(f"window {start:.0f}-{end:.0f}: {str(e)[:200]}; retrying")
            time.sleep(15 * (attempt + 1))
    return halves() if end - start > MIN_SPLIT_SECONDS else {"turns": [], "events": [], "usage": {"in": 0, "out": 0}}

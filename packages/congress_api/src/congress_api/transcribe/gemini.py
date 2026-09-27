"""
The two Gemini calls behind `hearing-transcribe`.

1. `transcribe_chunk`: Gemini 3.5 Transcribe on one audio chunk (up to 30 minutes with
   diarization), verbatim mode with speaker diarization and word-level timestamps. Returns
   utterances: {speaker_label, start, end, text, words}.
2. `resolve_speakers`: a general Gemini model reads the diarized transcript with the hearing's
   roster and witness list (and the YouTube video itself when there is one, so it can see
   name plates and hear introductions) and maps each speaker label to a person, with a
   confidence and the evidence. Returns {label: {name, role, confidence, evidence}}.

The API key is read from GEMINI_API_KEY.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from google import genai
from google.genai import types

TRANSCRIBE_MODEL = "gemini-3.5-transcribe"
RESOLVER_MODEL = "gemini-3.8-flash"
_client = None


def client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=key)
    return _client


def seconds(offset: str | None) -> float | None:
    return float(offset.rstrip("s")) if offset else None


def transcribe_chunk(path: Path, offset: float = 0.0, model: str = TRANSCRIBE_MODEL, attempts: int = 3) -> list[dict]:
    """Utterances for one audio chunk, times shifted by `offset` seconds into the whole recording."""
    c = client()
    f = c.files.upload(file=str(path))
    cfg = types.GenerateContentConfig(audio_transcription_config=types.AudioTranscriptionConfig(mode="VERBATIM", diarization=True, word_timestamp=True, language_codes=["en-US"]))
    for attempt in range(attempts):
        try:
            r = c.models.generate_content(model=model, contents=[types.Part.from_uri(file_uri=f.uri, mime_type=f.mime_type)], config=cfg)
            break
        except Exception as e:  # rate limits, transient 5xx
            logging.warning(f"{path.name}: {str(e)[:120]}; retrying")
            time.sleep(20 * (attempt + 1))
    else:
        raise RuntimeError(f"transcription failed for {path.name}")
    out = []
    for p in (r.candidates[0].content.parts or []):
        tr = getattr(p, "audio_transcription", None)
        if not tr or not (tr.text or "").strip():
            continue
        words = [{"word": w.word, "start": round((seconds(w.start_offset) or 0) + offset, 2), "end": round((seconds(w.end_offset) or 0) + offset, 2)} for w in (tr.words or [])]
        out.append({"speaker_label": tr.speaker_label or "spk:?", "start": words[0]["start"] if words else offset, "end": words[-1]["end"] if words else offset,
                    "text": tr.text.strip(), "words": words})
    try:
        c.files.delete(name=f.name)
    except Exception:
        pass
    return out


def stitch(chunks: list[tuple[list[dict], float, float]]) -> list[dict]:
    """Join chunk utterances. `chunks` is [(utterances, chunk_start, chunk_end)], overlapping by a few
    seconds: words of a later chunk that start before the previous chunk's end are dropped, and
    speaker labels are made unique per chunk (`c1:spk:0`) since diarization restarts each chunk."""
    out, prev_end = [], -1.0
    for n, (utts, start, end) in enumerate(chunks):
        for u in utts:
            words = [w for w in u["words"] if w["start"] >= prev_end] if n else u["words"]
            if not words and u["words"]:
                continue
            text = " ".join(w["word"] for w in words) if words != u["words"] else u["text"]
            out.append({**u, "speaker_label": f"c{n}:{u['speaker_label']}", "words": words, "text": text, "start": words[0]["start"] if words else u["start"], "end": words[-1]["end"] if words else u["end"]})
        prev_end = end
    return out


RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "speakers": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "name": {"type": "string"}, "role": {"type": "string", "enum": ["chair", "ranking_member", "member", "witness", "staff", "clerk", "other", "unknown"]},
            "confidence": {"type": "number"}, "evidence": {"type": "string"}}, "required": ["label", "name", "role", "confidence", "evidence"]}},
        "time_convened": {"type": "string"}, "time_adjourned": {"type": "string"},
        "events": {"type": "array", "items": {"type": "object", "properties": {"seconds": {"type": "number"}, "kind": {"type": "string", "enum": ["convened", "recess", "reconvened", "adjourned", "vote"]}, "text": {"type": "string"}}, "required": ["seconds", "kind", "text"]}},
    },
    "required": ["speakers", "events"],
}


def resolve_speakers(utterances: list[dict], roster: list[dict], meeting: dict, youtube_id: str = "", model: str = RESOLVER_MODEL) -> dict:
    """Map diarization labels to people. `roster` items: {name, role, party, state, organization, position}."""
    lines = []
    for u in utterances:
        lines.append(f"[{u['speaker_label']} @{int(u['start'] // 60)}:{int(u['start'] % 60):02d}] {u['text'][:600]}")
    transcript = "\n".join(lines)
    prompt = f"""You are attributing speakers in a U.S. congressional committee proceeding.

Meeting: {json.dumps(meeting, ensure_ascii=False)}
Known participants (members of the committee, and the scheduled witnesses): {json.dumps(roster, ensure_ascii=False)}

Below is a machine transcript with speaker labels from diarization. Labels restart in each chunk (c0:, c1:, ...), so the same person carries different labels across chunks. Work out who each label is, using: the chair opens and recognizes members by name and state ("the gentleman from Virginia, Mr. Cline"); the ranking member speaks second; witnesses are introduced by name and give statements in order; members ask questions in five-minute rounds and are recognized by name; speakers name themselves ("Thank you, Mr. Chairman, I'm ..."); staff or clerks call the roll. {"You also have the video: read the name plates and captions on screen." if youtube_id else ""}
Give every label a name from the known participants when the evidence supports it, a role, a confidence from 0 to 1, and one sentence of evidence. If a speaker is not among the known participants but names themself, give that name with role "other" or "witness". If you cannot tell, name "Unknown" with confidence 0.
Also give the wall-clock times the proceeding was called to order and adjourned if they are spoken or shown, and the recording seconds of any recess, reconvening, vote or adjournment.

TRANSCRIPT
{transcript}"""
    contents: list = []
    if youtube_id:
        contents.append(types.Part(file_data=types.FileData(file_uri=f"https://www.youtube.com/watch?v={youtube_id}", mime_type="video/*")))
    contents.append(prompt)
    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=RESOLVE_SCHEMA, media_resolution="MEDIA_RESOLUTION_LOW" if youtube_id else None, temperature=0.2)
    for attempt in range(3):
        try:
            r = client().models.generate_content(model=model, contents=contents, config=cfg)
            return json.loads(r.text)
        except Exception as e:
            logging.warning(f"resolver: {str(e)[:160]}; retrying" if attempt < 2 else f"resolver failed: {str(e)[:300]}")
            if youtube_id and attempt == 1:
                contents, cfg.media_resolution = [prompt], None  # fall back to the transcript alone
            time.sleep(15 * (attempt + 1))
    return {"speakers": [], "events": []}


VIDEO_TURNS_SCHEMA = {
    "type": "object",
    "properties": {"turns": {"type": "array", "items": {"type": "object", "properties": {
        "speaker": {"type": "string"}, "role": {"type": "string", "enum": ["chair", "ranking_member", "member", "witness", "staff", "clerk", "other", "unknown"]},
        "confidence": {"type": "number"}, "start": {"type": "number"}, "end": {"type": "number"}, "text": {"type": "string"}},
        "required": ["speaker", "role", "confidence", "start", "text"]}},
        "events": RESOLVE_SCHEMA["properties"]["events"]},
    "required": ["turns", "events"],
}


def transcribe_video_window(youtube_id: str, start: float, end: float, roster: list[dict], meeting: dict, model: str = RESOLVER_MODEL) -> dict:
    """The other route: a general Gemini model watches a window of the YouTube video itself and
    returns named speaker turns directly (it can read name plates and hear introductions).
    Same output shape as the transcribe-then-resolve route, for comparison."""
    prompt = f"""Transcribe this segment of a U.S. congressional committee proceeding verbatim, as speaker turns.

Meeting: {json.dumps(meeting, ensure_ascii=False)}
Known participants (committee members and scheduled witnesses): {json.dumps(roster, ensure_ascii=False)}

For each turn give the speaker's name from the known participants when you can tell who is speaking (name plates on screen, the chair recognizing members by name and state, witnesses introduced by name, self-introductions), their role, a confidence from 0 to 1, the start time in seconds from the beginning of the whole video (this window starts at {int(start)} seconds), and the words spoken. Keep every word, including false starts, in the order spoken; do not summarize. Use "Unknown" with confidence 0 when you cannot tell. Also list any call to order, recess, vote or adjournment as events with the seconds and the words used."""
    contents = [types.Part(file_data=types.FileData(file_uri=f"https://www.youtube.com/watch?v={youtube_id}", mime_type="video/*"),
                           video_metadata=types.VideoMetadata(start_offset=f"{int(start)}s", end_offset=f"{int(end)}s")), prompt]
    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=VIDEO_TURNS_SCHEMA, media_resolution="MEDIA_RESOLUTION_LOW", temperature=0.2, max_output_tokens=65536)
    def halves():
        ## the window didn't come back whole: do it in two halves. A verbatim transcript longer than
        ##  about 25-30 minutes trips the model's recitation filter (finish reason RECITATION, no
        ##  text), and a very dense one can exceed the 65k output tokens.
        mid = (start + end) / 2
        a, b = transcribe_video_window(youtube_id, start, mid, roster, meeting, model), transcribe_video_window(youtube_id, mid, end, roster, meeting, model)
        return {"turns": a["turns"] + b["turns"], "events": a["events"] + b["events"], "usage": {k: a["usage"].get(k, 0) + b["usage"].get(k, 0) for k in ("in", "out")}}

    for attempt in range(2):
        try:
            r = client().models.generate_content(model=model, contents=contents, config=cfg)
            reason = str(r.candidates[0].finish_reason) if r.candidates else "no candidates"
            if (not r.text or "MAX_TOKENS" in reason or "RECITATION" in reason) and end - start > 600:
                logging.info(f"video window {start:.0f}-{end:.0f}: {reason}, splitting")
                return halves()
            d = json.loads(r.text)
            d["usage"] = {"in": r.usage_metadata.prompt_token_count, "out": r.usage_metadata.candidates_token_count}
            return d
        except Exception as e:
            logging.warning(f"video window {start:.0f}-{end:.0f}: {str(e)[:200]}; retrying")
            time.sleep(15 * (attempt + 1))
    return halves() if end - start > 600 else {"turns": [], "events": [], "usage": {}}

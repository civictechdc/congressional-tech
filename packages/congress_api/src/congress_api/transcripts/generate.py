"""
Transcribe a committee proceeding into the shared transcript schema, with members and
witnesses named.

    hearing-transcribe --event-id 116xxx --out-dir ~/hearing-text/transcripts          # picks the meeting's recording
    hearing-transcribe --video-id 8V3OGbZOLB0 --event-id 116xxx --out-dir ...          # a specific YouTube recording
    hearing-transcribe --senate-url "https://www.senate.gov/isvp/?comm=epw&filename=epw120623" --event-id ...
    hearing-transcribe --gpo-package CHRG-118hhrg54254 --out-dir ...                    # the print, parsed into the same schema

Gemini 3.8 Flash transcribes the recording in 25-minute windows into named speaker turns: the
YouTube video itself (it reads the name plates and hears the chair's recognitions), or
uploaded audio chunks for senate.gov and local recordings. Measured on a 2023 Judiciary
hearing against its print: word error rate 8.7%, speakers right on 85% of words. See
gemini.py for why the windows are 25 minutes and why the dedicated transcription model
was dropped.

Writes <id>.json (the schema) and <id>.gpo.txt (the print's layout). Needs GEMINI_API_KEY;
YOUTUBE_API_KEY lets the video's length come from the Data API instead of yt-dlp, and --proxy
is passed to yt-dlp when YouTube asks for a sign-in.
New GovInfo HTML and Gemini responses are retained under source/ before parsing.
"""

import csv
import datetime as dt
import logging
import re
from pathlib import Path

import requests
from congress_shared.globals import DEFAULT_GPO_HEARINGS_FILE

from congress_api.parsers import speaker_names as names
from congress_api.models.gpo import GpoEvidenceObservation
from congress_api.models.transcription import (
    Header,
    Person,
    Source,
    Transcript,
    Turn,
    YoutubeVideoResponse,
    YtdlpVideoInfo,
)
from congress_api.parsers.gpo import parse_transcript_html
from congress_api.parsers.witness_names import person_key
from congress_api.retention.gpo import write_observation
from congress_api.transcripts import context as metadata
from congress_api.transcripts.context import HearingContext, mods_people
from congress_api.transport import audio as A


def roster_json(participants: dict[str, Person]) -> list[dict]:
    return [{k: v for k, v in p.model_dump(mode='json').items() if v and k not in ("speaker_label", "confidence", "honorific")} for p in participants.values()]


def meeting_json(h: Header) -> dict:
    return {"title": h.title, "committee": h.committee, "subcommittee": h.subcommittee, "date": h.date, "chamber": h.chamber}


def from_gpo(package_id: str, gpo_path=DEFAULT_GPO_HEARINGS_FILE, *, source_dir: Path | None = None) -> Transcript:
    from congress_api.parsers.gpo_text import parse_gpo_text
    with open(gpo_path) as stream:
        row = {r["package_id"]: r for r in csv.DictReader(stream)}[package_id]
    people, facts = mods_people(package_id)
    header = Header(title=facts["title"], chamber=row["chamber"], congress=int(facts["congress"] or 0) or None, session=int(facts["session"] or 0) or None,
                    committee=facts["committee"], committee_code=facts["committee_code"], subcommittee=facts["subcommittee"], date=facts["held_date"],
                    serial=facts["serial"], package_id=package_id, event_id=row["event_id"])
    response = requests.get(row["html_url"], timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    source = parse_transcript_html(response.content, decoded_text=response.text)
    if source_dir is not None:
        write_observation(GpoEvidenceObservation(**source.source.source_dict(), url=row['html_url'],
            retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat(), acquisition='http'),
            source_dir / f'{package_id}.json')
    return parse_gpo_text(source, header, people, source_url=row["html_url"])


def place(participants: dict[str, Person], name: str, role: str, confidence) -> str:
    """The participant key for a name the model gave: a known participant by name (token suffix, so
    "Jeff Van Drew" finds "Jefferson Van Drew"), else a sitting member of that name from
    congress-legislators, else a new participant. A chair or ranking-member role from the model
    upgrades a roster "member"."""
    if name == "Unknown":
        participants.setdefault("unknown", Person(name="Unknown", role="unknown", confidence=0))
        return "unknown"
    k = names.match(participants, name)
    if k is None:
        k = person_key(name)
        p = Person(name=name, role=role or "unknown", surname=names.surname(name), confidence=confidence)
        if role not in ("witness", "staff", "clerk"):
            ref = names.tokens(name)
            hits = [(b, l) for b, l in metadata.legislators_current().items() if names.tokens(l["name"])[-len(names.tokens(l["last"])):] == ref[-len(names.tokens(l["last"])):]]
            if len(hits) == 1:
                b, l = hits[0]
                p.role = role if role in ("chair", "ranking_member") else "member"
                p.name, p.party, p.state, p.bioguide_id = l["name"], l["party"], l["state"], b
                p.honorific = "Senator" if l["chamber"] == "sen" else {"M": "Mr.", "F": "Ms."}.get(l["gender"], "")
        participants[k] = p
        return k
    p = participants[k]
    if role in ("chair", "ranking_member") and p.role in ("member", "unknown", "other"):
        p.role = role
    if p.confidence is None:
        p.confidence = confidence
    return k


def video_duration(video_id: str, proxy: str | None = None) -> float:
    """Seconds, from the YouTube Data API when YOUTUBE_API_KEY is set (no bot checks), else yt-dlp."""
    import os
    key = os.environ.get("YOUTUBE_API_KEY")
    if key:
        d = YoutubeVideoResponse.model_validate(requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "contentDetails", "id": video_id, "key": key}, timeout=30).json())
        if d.items:
            m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d.items[0].content_details.duration)
            if m:
                return sum(int(x or 0) * k for x, k in zip(m.groups(), (3600, 60, 1)))
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "logger": logging.getLogger("yt_dlp"), **({"proxy": proxy} if proxy else {})}) as ydl:
        source = YtdlpVideoInfo.model_validate(ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False))
        return source.duration or 4 * 3600


def merge_turns(turns: list[Turn]) -> list[Turn]:
    """Join consecutive turns by the same speaker: the models split long answers into several."""
    out: list[Turn] = []
    for t in turns:
        if out and out[-1].speaker == t.speaker and out[-1].kind == t.kind == "speech":
            out[-1].text = f"{out[-1].text.rstrip()} {t.text.lstrip()}"
            out[-1].end = t.end if t.end is not None else out[-1].end
        else:
            out.append(t)
    return out


def transcribe(ctx: HearingContext, out_dir: Path, video_id: str = "", senate_url: str = "", local: str = "", proxy: str | None = None) -> Transcript:
    """Named turns for the whole recording: the YouTube video in windows, or uploaded audio chunks
    for senate.gov and local recordings."""
    from congress_api.transport import gemini as G
    header, participants = ctx.header, dict(ctx.participants)
    roster, meeting = roster_json(participants), meeting_json(header)
    turns: list[Turn] = []
    events, usage = [], {"in": 0, "out": 0}
    if video_id:
        dur = video_duration(video_id, proxy)
        windows = [(None, start, min(start + G.WINDOW_SECONDS, dur)) for start in range(0, int(dur), G.WINDOW_SECONDS)]
    else:
        path = A.get_audio(out_dir / "audio", senate_url=senate_url, local=local)
        windows = [(piece, offset, offset + A.duration(piece)) for piece, offset in A.chunks(path, minutes=G.WINDOW_SECONDS / 60)]
    for piece, start, end in windows:
        d = G.transcribe_window(roster, meeting, start, end, youtube_id=video_id, audio=piece,
                                capture_dir=out_dir / 'source' / (video_id or (Path(local).stem if local else 'senate')))
        events += d.get("events", [])
        for k in usage:
            usage[k] += d.get("usage", {}).get(k, 0)
        for u in d.get("turns", []):
            k = place(participants, u["speaker"], u.get("role", "unknown"), u.get("confidence"))
            turns.append(Turn(speaker=k, text=u["text"], start=u.get("start"), end=u.get("end")))
        logging.info(f"window @{start:.0f}s: {len(d.get('turns', []))} turns")
    turns = merge_turns(turns)
    for e in events:
        turns.append(Turn(speaker="", text=f"{e['kind'].replace('_', ' ').capitalize()} at {int(e['seconds'] // 60)}:{int(e['seconds'] % 60):02d} into the recording: {e['text']}", start=e["seconds"], kind="direction"))
    turns.sort(key=lambda t: (t.start if t.start is not None else 0))
    if not header.time_convened and ctx.scheduled_time_et:
        header.time_convened = ctx.scheduled_time_et
    header.present = [k for k, p in participants.items() if p.role in ("chair", "ranking_member", "member") and any(t.speaker == k for t in turns)]
    header.presiding = header.presiding or next((k for k, p in participants.items() if p.role == "chair" and any(t.speaker == k for t in turns)), "")
    src = Source(kind="gemini_transcription", url=f"https://www.youtube.com/watch?v={video_id}" if video_id else senate_url or local, video_id=video_id,
                 model=G.MODEL + (" (video)" if video_id else " (audio)"), generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 notes=f"tokens in {usage['in']:,}, out {usage['out']:,}" + ("; time_convened is the scheduled time from Congress.gov" if header.time_convened and header.time_convened == ctx.scheduled_time_et else ""))
    return Transcript(header=header, participants=participants, turns=turns, source=src)

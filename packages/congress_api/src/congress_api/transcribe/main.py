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
--proxy is passed to yt-dlp for the audio download when YouTube asks for a sign-in.
"""
import argparse
import csv
import dataclasses
import datetime as dt
import html
import logging
import re
import sys
from pathlib import Path

import requests

from congress_shared.globals import DEFAULT_GPO_HEARINGS_FILE, DEFAULT_MEETINGS_FILE

from congress_api.transcribe import audio as A
from congress_api.transcribe import metadata, names
from congress_api.transcribe.metadata import HearingContext, context_for_event, mods_people
from congress_api.transcribe.schema import Header, Person, Source, Transcript, Turn, person_key, render_gpo



def roster_json(participants: dict[str, Person]) -> list[dict]:
    return [{k: v for k, v in dataclasses.asdict(p).items() if v and k not in ("speaker_label", "confidence", "honorific")} for p in participants.values()]


def meeting_json(h: Header) -> dict:
    return {"title": h.title, "committee": h.committee, "subcommittee": h.subcommittee, "date": h.date, "chamber": h.chamber}


def from_gpo(package_id: str, gpo_path=DEFAULT_GPO_HEARINGS_FILE) -> Transcript:
    from congress_api.transcribe.gpo_parse import parse_gpo_text
    row = {r["package_id"]: r for r in csv.DictReader(open(gpo_path))}[package_id]
    people, facts = mods_people(package_id)
    header = Header(title=facts["title"], chamber=row["chamber"], congress=int(facts["congress"] or 0) or None, session=int(facts["session"] or 0) or None,
                    committee=facts["committee"], committee_code=facts["committee_code"], subcommittee=facts["subcommittee"], date=facts["held_date"],
                    serial=facts["serial"], package_id=package_id, event_id=row["event_id"])
    text = html.unescape(re.sub(r"<[^>]+>", "", requests.get(row["html_url"], timeout=60, headers={"User-Agent": "Mozilla/5.0"}).text))
    return parse_gpo_text(text, header, people, source_url=row["html_url"])


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
    from congress_api.transcribe import gemini as G
    header, participants = ctx.header, dict(ctx.participants)
    roster, meeting = roster_json(participants), meeting_json(header)
    turns: list[Turn] = []
    events, usage = [], {"in": 0, "out": 0}
    if video_id:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "logger": logging.getLogger("yt_dlp"), **({"proxy": proxy, "nocheckcertificate": True} if proxy else {})}) as ydl:
            dur = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False).get("duration") or 4 * 3600
        windows = [(None, start, min(start + G.WINDOW_SECONDS, dur)) for start in range(0, int(dur), G.WINDOW_SECONDS)]
    else:
        path = A.get_audio(out_dir / "audio", senate_url=senate_url, local=local)
        windows = [(piece, offset, offset + A.duration(piece)) for piece, offset in A.chunks(path, minutes=G.WINDOW_SECONDS / 60)]
    for piece, start, end in windows:
        d = G.transcribe_window(roster, meeting, start, end, youtube_id=video_id, audio=piece)
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


def parse_args_and_run():
    p = argparse.ArgumentParser(description="Transcribe a committee proceeding into the shared transcript schema.")
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--event-id", help="Congress.gov meeting event ID (gives the participants and, by default, the recording).")
    p.add_argument("--gpo-package", help="Parse this GPO print instead of transcribing (or, with a recording, use its metadata too).")
    p.add_argument("--video-id"); p.add_argument("--senate-url"); p.add_argument("--audio", help="A local audio or video file.")
    p.add_argument("--proxy", help="Proxy for yt-dlp when YouTube asks for a sign-in.")
    p.add_argument("--gpo-path", type=Path, default=DEFAULT_GPO_HEARINGS_FILE, help="gpo_hearings.csv (see gpo-fetch).")
    p.add_argument("--meetings", type=Path, default=DEFAULT_MEETINGS_FILE, help="congress_meetings.jsonl.gz (see congress-meetings).")
    a = p.parse_args()
    metadata.set_paths(str(a.gpo_path), str(a.meetings))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(asctime)s : %(message)s")
    logging.getLogger("google_genai").setLevel(logging.WARNING); logging.getLogger("httpx").setLevel(logging.WARNING)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.gpo_package and not (a.video_id or a.senate_url or a.audio or a.event_id):
        t = from_gpo(a.gpo_package, a.gpo_path); stem = a.gpo_package
    else:
        if not (a.event_id or a.gpo_package):
            sys.exit("give --event-id or --gpo-package so the participants are known")
        row = {r["package_id"]: r for r in csv.DictReader(open(a.gpo_path))}.get(a.gpo_package or "", {})
        ctx = context_for_event(a.event_id or row.get("event_id", ""), package_id=a.gpo_package or "")
        video_id = a.video_id or (ctx.youtube_ids[0] if ctx.youtube_ids and not a.senate_url and not a.audio else "")
        senate_url = a.senate_url or ("" if video_id or a.audio else (ctx.senate_urls[0] if ctx.senate_urls else ""))
        if not (video_id or senate_url or a.audio):
            sys.exit("no recording known for this meeting; pass --video-id, --senate-url or --audio")
        t = transcribe(ctx, a.out_dir, video_id=video_id, senate_url=senate_url, local=a.audio or "", proxy=a.proxy)
        stem = video_id or (re.search(r"filename=([^&]+)", senate_url).group(1) if senate_url else Path(a.audio).stem)
    (a.out_dir / f"{stem}.json").write_text(t.to_json(), encoding="utf-8")
    (a.out_dir / f"{stem}.gpo.txt").write_text(render_gpo(t), encoding="utf-8")
    named = sum(1 for p in t.participants.values() if p.role != "unknown" and p.name != "Unknown")
    logging.info(f"wrote {a.out_dir / stem}.json: {len(t.turns)} turns, {named} named participants")


if __name__ == "__main__":
    parse_args_and_run()

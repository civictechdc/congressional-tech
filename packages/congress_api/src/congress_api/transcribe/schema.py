"""
One transcript schema for a committee proceeding, whatever produced it.

A GPO print (`gpo_parse.py`) and a machine transcription (`main.py`) both become a
`Transcript`: the header a printed hearing carries (committee, date, room, presiding
member, members present, witnesses), then speaker turns with the speaker resolved to a
person, then the record inserts. `render_gpo()` writes it back in the print's layout, so
the two can be read, diffed and searched the same way.

Serialized as JSON (`Transcript.to_json`); `TRANSCRIPT_JSON_SCHEMA` is the matching JSON
Schema for validation or for other tools.
"""
from __future__ import annotations

import dataclasses
import json
import textwrap
from dataclasses import dataclass, field
from typing import Optional

SCHEMA_VERSION = "1.0"


@dataclass
class Person:
    """A member, witness or other participant. `role` follows the print's conventions."""
    name: str                       # as printed / spoken: "Ben Cline", "Martha Williams"
    role: str                       # chair | ranking_member | member | witness | staff | clerk | other | unknown
    honorific: str = ""             # Mr. | Ms. | Mrs. | Dr. | Senator | The Chairman ...
    surname: str = ""               # the print attributes turns by surname: "Cline"
    party: str = ""                 # R | D | I, members only
    state: str = ""                 # members only
    bioguide_id: str = ""           # members only, when resolved
    organization: str = ""          # witnesses
    position: str = ""              # witnesses
    speaker_label: str = ""         # the diarization label this person was mapped from (machine transcripts)
    confidence: float | None = None  # how sure the mapping is, 0-1 (machine transcripts)


@dataclass
class Turn:
    """One speaker turn. Times are seconds into the recording (machine transcripts only)."""
    speaker: str                    # key into Transcript.participants, or a raw label ("spk:3") when unresolved
    text: str
    start: float | None = None
    end: float | None = None
    kind: str = "speech"            # speech | statement (a witness's opening statement) | direction (bracketed stage direction)


@dataclass
class Insert:
    """Material the print includes that wasn't spoken: prepared statements, letters, questions for the record."""
    kind: str                       # prepared_statement | submission | questions_for_the_record | graphic | other
    title: str
    text: str = ""
    for_person: str = ""            # key into participants when the insert belongs to someone


@dataclass
class Header:
    title: str
    chamber: str                    # house | senate | joint
    congress: int | None = None
    session: int | None = None
    committee: str = ""             # "Committee on the Judiciary"
    committee_code: str = ""        # hsju00
    subcommittee: str = ""
    date: str = ""                  # ISO date
    time_convened: str = ""         # "2:02 p.m."
    time_adjourned: str = ""
    location: str = ""              # "Room 2141, Rayburn House Office Building"
    presiding: str = ""             # key into participants
    present: list[str] = field(default_factory=list)   # keys into participants
    serial: str = ""                # print citation, when there is one
    package_id: str = ""            # GPO package, when there is one
    event_id: str = ""              # Congress.gov event ID


@dataclass
class Source:
    kind: str                       # gpo_print | gemini_transcription | youtube_captions | senate_captions
    url: str = ""
    video_id: str = ""
    model: str = ""
    generated_at: str = ""
    notes: str = ""


@dataclass
class Transcript:
    header: Header
    participants: dict[str, Person]  # key: a slug like "cline", "williams-martha"
    turns: list[Turn]
    inserts: list[Insert] = field(default_factory=list)
    source: Source = field(default_factory=lambda: Source(kind="unknown"))
    schema_version: str = SCHEMA_VERSION

    def to_json(self, **kw) -> str:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False, indent=kw.pop("indent", 1), **kw)

    @classmethod
    def from_json(cls, text: str) -> "Transcript":
        d = json.loads(text)
        return cls(header=Header(**d["header"]), participants={k: Person(**v) for k, v in d["participants"].items()},
                   turns=[Turn(**t) for t in d["turns"]], inserts=[Insert(**i) for i in d.get("inserts", [])],
                   source=Source(**d.get("source", {"kind": "unknown"})), schema_version=d.get("schema_version", SCHEMA_VERSION))


def person_key(name: str) -> str:
    """'Hon. Ben Cline' -> 'cline-ben'; 'Mr. Dunham' -> 'dunham'."""
    import re
    parts = [p for p in re.sub(r"[^\w\s-]", "", name).lower().split() if p not in ("hon", "the", "mr", "ms", "mrs", "dr", "senator", "representative", "chairman", "chairwoman", "chair", "jr", "sr", "ii", "iii")]
    if not parts:
        return "unknown"
    return parts[-1] if len(parts) == 1 else f"{parts[-1]}-{parts[0]}"


def attribution(p: Person) -> str:
    """How the print names a speaker at the start of a turn: 'Mr. Cline', 'Chairman Jordan', 'Ms. Williams'."""
    if p.surname:
        return f"{p.honorific or 'Mr.'} {p.surname}"
    return p.name


def render_gpo(t: Transcript, width: int = 70) -> str:
    """The transcript in the layout of a GPO print: title block, the convening sentence, 'Present:',
    speaker turns indented four spaces, witness statement headers, stage directions in brackets,
    the adjournment line, then the inserts."""
    h, P = t.header, t.participants
    out = []
    out.append(h.title.upper().center(width).rstrip())
    out.append("")
    out.append("=" * width)
    out.append("")
    for line in ("HEARING" if h.title.lower().find("markup") < 0 else "MARKUP", "BEFORE THE", (h.subcommittee or "").upper(), "OF THE" if h.subcommittee else "", h.committee.upper(), f"{'HOUSE OF REPRESENTATIVES' if h.chamber == 'house' else 'UNITED STATES SENATE' if h.chamber == 'senate' else 'CONGRESS OF THE UNITED STATES'}"):
        if line:
            out.append(line.center(width).rstrip())
    if h.congress:
        out.append(f"{ordinal(h.congress)} CONGRESS{', ' + ('FIRST' if h.session == 1 else 'SECOND') + ' SESSION' if h.session else ''}".center(width).rstrip())
    out.append("")
    out.append(h.date.center(width).rstrip())
    out.append("")
    if h.serial:
        out.append(h.serial.center(width).rstrip())
    out.append("")
    body = h.subcommittee and "Subcommittee" or "Committee"
    pres = P.get(h.presiding)
    convened = f"The {body} met, pursuant to notice," + (f" at {h.time_convened}," if h.time_convened else "") + (f" in {h.location}," if h.location else "") + (f" Hon. {pres.name} [{'Chair' if pres.role == 'chair' else pres.role.replace('_', ' ').title()} of the {body}] presiding." if pres else " presiding.")
    out += textwrap.wrap(convened, width, initial_indent="    ")
    present = [P[k] for k in h.present if k in P]
    if present:
        label = "Senators" if h.chamber == "senate" else "Representatives"
        out += textwrap.wrap(f"Present: {label} " + ", ".join(p.surname or p.name for p in present) + ".", width, initial_indent="    ")
    for turn in t.turns:
        out.append("")
        if turn.kind == "direction":
            out += textwrap.wrap(f"[{turn.text.strip('[]')}]", width, initial_indent="    ")
            continue
        p = P.get(turn.speaker)
        if turn.kind == "statement" and p:
            out.append(f"STATEMENT OF {('THE HON. ' if p.role in ('chair', 'ranking_member', 'member') else '')}{p.name.upper()}" + (f", {p.position.upper()}, {p.organization.upper()}" if p.organization else "").center(width).rstrip())
            out.append("")
        who = attribution(p) if p else turn.speaker
        out += textwrap.wrap(f"{who}. {turn.text}", width, initial_indent="    ")
    if h.time_adjourned:
        out.append("")
        out.append(f"    [Whereupon, at {h.time_adjourned}, the {body} was adjourned.]")
    if t.inserts:
        out += ["", "", "A P P E N D I X".center(width).rstrip(), ""]
        for ins in t.inserts:
            out += ["", ins.title.center(width).rstrip(), ""]
            out += [l for para in ins.text.split("\n") for l in (textwrap.wrap(para, width) or [""])]
    return "\n".join(out) + "\n"


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


TRANSCRIPT_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Committee proceeding transcript",
    "type": "object",
    "required": ["header", "participants", "turns", "source", "schema_version"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "header": {"type": "object", "required": ["title", "chamber"], "properties": {
            "title": {"type": "string"}, "chamber": {"enum": ["house", "senate", "joint"]},
            "congress": {"type": ["integer", "null"]}, "session": {"type": ["integer", "null"]},
            "committee": {"type": "string"}, "committee_code": {"type": "string"}, "subcommittee": {"type": "string"},
            "date": {"type": "string"}, "time_convened": {"type": "string"}, "time_adjourned": {"type": "string"},
            "location": {"type": "string"}, "presiding": {"type": "string"},
            "present": {"type": "array", "items": {"type": "string"}},
            "serial": {"type": "string"}, "package_id": {"type": "string"}, "event_id": {"type": "string"}}},
        "participants": {"type": "object", "additionalProperties": {"type": "object", "required": ["name", "role"], "properties": {
            "name": {"type": "string"}, "role": {"enum": ["chair", "ranking_member", "member", "witness", "staff", "clerk", "other", "unknown"]},
            "honorific": {"type": "string"}, "surname": {"type": "string"}, "party": {"type": "string"}, "state": {"type": "string"},
            "bioguide_id": {"type": "string"}, "organization": {"type": "string"}, "position": {"type": "string"},
            "speaker_label": {"type": "string"}, "confidence": {"type": ["number", "null"]}}}},
        "turns": {"type": "array", "items": {"type": "object", "required": ["speaker", "text"], "properties": {
            "speaker": {"type": "string"}, "text": {"type": "string"}, "start": {"type": ["number", "null"]}, "end": {"type": ["number", "null"]},
            "kind": {"enum": ["speech", "statement", "direction"]}}}},
        "inserts": {"type": "array", "items": {"type": "object", "required": ["kind", "title"], "properties": {
            "kind": {"enum": ["prepared_statement", "submission", "questions_for_the_record", "graphic", "other"]},
            "title": {"type": "string"}, "text": {"type": "string"}, "for_person": {"type": "string"}}}},
        "source": {"type": "object", "required": ["kind"], "properties": {
            "kind": {"enum": ["gpo_print", "gemini_transcription", "youtube_captions", "senate_captions", "unknown"]},
            "url": {"type": "string"}, "video_id": {"type": "string"}, "model": {"type": "string"}, "generated_at": {"type": "string"}, "notes": {"type": "string"}}},
    },
}

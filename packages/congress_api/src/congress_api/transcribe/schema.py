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

import textwrap

from congress_api.witnesses import person_key
from congress_api.models.transcription import Header, Insert, Person, Source, Transcript, Turn, SCHEMA_VERSION


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
    **Transcript.model_json_schema(),
    "title": "Committee proceeding transcript",
}

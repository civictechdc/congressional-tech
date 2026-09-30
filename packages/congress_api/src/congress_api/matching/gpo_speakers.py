"""Bind a GPO print's speaker labels to roster entries.

`parsers.gpo_text` leaves each turn's speaker as the print's attribution
("Mr. Cline", "The Chairman") and records how those labels were encountered.
This module chooses which participant that text names. Parsers cannot import
matching, so transcript generation and any check that needs keys call
`bind_gpo_transcript`.
"""

from __future__ import annotations

import re

from congress_api.matching import speaker_names as names
from congress_api.models.transcription import Person, Transcript
from congress_api.parsers.gpo_text import ROLE_WORDS, WITNESS_TITLES
from congress_api.parsers.witness_names import person_key


def bind_gpo_transcript(transcript: Transcript) -> Transcript:
    """Replace printed speaker labels with participant keys.

    A transcript that was not produced by `parse_gpo_text` is returned unchanged.
    Ambiguous surnames become a new unknown participant rather than the first roster hit.
    """
    binding = (transcript.__pydantic_extra__ or {}).get("speaker_binding")
    if not binding:
        return transcript
    data = transcript.model_dump()
    data.pop("speaker_binding", None)
    bound = Transcript.model_validate(data)
    header = bound.header
    participants = bound.participants
    titles = set(binding["titles"])
    header.present = list(binding["caller_present"])

    for row in binding["roster"]:
        key = names.match(participants, row["name"]) or row["key"]
        if key in participants:
            participants[key].state = participants[key].state or row["state"]
            if row["role"] != "member":
                participants[key].role = row["role"]
        else:
            participants[key] = Person(name=row["name"], role=row["role"], surname=names.surname(row["name"]), state=row["state"])
    subcommittee = set(binding["subcommittee_keys"])
    prefer = set(subcommittee) if (header.subcommittee or subcommittee) else set()

    def resolve(reference: str, role_hint: str = "") -> str:
        """The participant an attribution or name refers to, created when unknown.

        "The Chairman" and other role-only references are the presiding member.
        "Davis of Illinois" is the Davis from Illinois.
        """
        words = reference.split()
        if header.presiding and all(w.rstrip(".").lower() in set(ROLE_WORDS) | {"the", "vice", "acting"} for w in words):
            return header.presiding
        title = words[0].rstrip(".").lower() if len(words) > 1 and words[0].rstrip(".").lower() in titles | set(ROLE_WORDS) | WITNESS_TITLES else ""
        name = " ".join(words[1:]) if title else reference
        state = None
        found = re.fullmatch(r"(.+?) of ([A-Z][a-z]+(?: [A-Z][a-z]+)?)", name)
        if found:
            name, state = found.group(1), found.group(2)
        from_state = {key for key, person in participants.items() if state and person.state and (person.state == state or person.state.lower() == state.lower())}
        key = names.match(participants, name, prefer=(from_state or prefer | set(header.present)))
        if not key:
            # Ambiguous surnames return None; a fresh unknown key is better than the wrong member.
            key = person_key(name)
            if key not in participants:
                role = ROLE_WORDS.get(title) or ("witness" if title in WITNESS_TITLES else "unknown")
                participants[key] = Person(name=name, role=role_hint or role, surname=names.surname(name))
        person = participants[key]
        if title in ("mr", "ms", "mrs", "miss", "dr", "senator") and not person.honorific:
            person.honorific = title.capitalize() + ("." if title != "senator" else "")
        if ROLE_WORDS.get(title) in ("chair", "ranking_member") and person.role in ("member", "unknown"):
            person.role = ROLE_WORDS[title]
        return key

    tail = binding.get("convening_tail") or ""
    if tail:
        presiding = next((key for key, person in participants.items() if person.role in ("chair", "ranking_member", "member") and re.search(r"\b" + re.escape(person.name.split()[-1]) + r"\b", tail)), None)
        if not presiding:
            phrase = re.search(r"((?:[A-Z][\w'’\-]*\.? ){1,4})\s*[\[(]", tail) or re.search(r"((?:[A-Z][\w'’\-]*\.? ){1,4})$", tail.strip())
            if phrase:
                presiding = resolve(re.sub(r"^(Hon\.|Honorable|Senator|Representative) ", "", phrase.group(1).strip()), role_hint="chair")
        if presiding:
            header.presiding = presiding
            if participants[presiding].role in ("member", "unknown"):
                participants[presiding].role = "chair"

    for op in binding["ops"]:
        if op["op"] == "present":
            header.present = [resolve(name, role_hint="member") for name in op["names"]]
        elif op["op"] == "turn":
            key = resolve(op["reference"])
            bound.turns[op["index"]].speaker = key
            if op["statement"] and participants[key].role == "unknown":
                participants[key].role = "witness"
        elif op["op"] == "insert":
            bound.inserts[op["index"]].for_person = names.match(participants, op["reference"]) or ""
    return bound

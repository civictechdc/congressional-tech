"""
Parse a GPO printed hearing into the shared `Transcript` schema.

    from congress_api.transcribe.gpo_parse import parse_gpo_text
    t = parse_gpo_text(text, header_hint)   # text: the print as plain text (see gpo-transcripts)

The print is one fixed-width block: title page, committee roster, contents, then the body
("The Subcommittee met, pursuant to notice, at 2:02 p.m., in Room 2141 ..., Hon. Ben Cline
[Chair of the Subcommittee] presiding." / "Present: Representatives ..."), speaker turns
("    Mr. Cline. All right. ..."), "STATEMENT OF ..." headers, bracketed stage directions,
"[Whereupon, at 3:26 p.m., the Subcommittee was adjourned.]", and the appendix. This
parser reads those landmarks; the roster gives each member's state, the MODS record (see
`metadata.py`) gives party, bioguide IDs and witness affiliations when available.
"""
from __future__ import annotations

import re

from congress_api.transcribe.schema import Header, Insert, Person, Source, Transcript, person_key

TURN = re.compile(r"^    (Mr|Ms|Mrs|Miss|Dr|Chairman|Chairwoman|Chair|Senator|The Chairman|The Chairwoman|The Chair|General|Admiral|Secretary|Judge|Ambassador|Governor|Mayor)\.? ([A-Z][A-Za-z'’\-]+(?: [A-Z][a-z]+)?)\. (.*)$")
STATEMENT = re.compile(r"^\s*(?:OPENING )?STATEMENTS? OF (.+?)\s*$")
DIRECTION = re.compile(r"^\s*\[(.*)\]\s*$")
CONVENED = re.compile(r"The (Sub)?[Cc]ommittees? (?:met|convened|was called to order),? (?:pursuant to (?:call|notice),? )?at (\d{1,2}(?::\d{2})? ?[ap]\.m\.),?(?: in (?:the )?(.+?),)?.*?(?:Hon\.|Honorable|Senator|Representative) ([A-Z][^\[]+?)\s*\[(.*?)\]\s*presiding", re.S)
ADJOURNED = re.compile(r"\[Whereupon, at (\d{1,2}(?::\d{2})? ?[ap]\.m\.),? the (?:sub)?committee (?:was )?(?:adjourned|recessed)", re.I)
PRESENT = re.compile(r"^\s*Present: (?:Representatives|Senators|Members)? ?(.+?)\.\s*$", re.S)
PREPARED = re.compile(r"\[The (?:prepared |written )?(?:statement|testimony|information|letter|report|material|response)s? (?:of|from|submitted by) (.+?) follows?:?\]", re.I)
ROSTER_LINE = re.compile(r"^([A-Z][A-Z .'`\-]+?(?:, Jr\.|, Sr\.|, III|, II)?), ([A-Z][a-z]+(?: [A-Z][a-z]+)*)(?:, (Chair(?:man|woman)?|Ranking\s*Member|Vice Chair(?:man)?))?\s*$")
PARTICLES = {"van", "von", "de", "del", "della", "der", "di", "da", "la", "le", "st.", "mc"}
STOP_ROSTER = ("C O N T E N T S", "CONTENTS", "Staff Director", "STAFF DIRECTOR")


def roster(lines: list[str]) -> list[Person]:
    """Members from the two-column roster page: 'DARRELL ISSA, California    JERROLD NADLER, New York, Ranking'.
    Members listed again under a SUBCOMMITTEE heading get position="subcommittee", so an ambiguous
    surname in a subcommittee hearing ("Ms. Lee" with two Lees on the full committee) resolves to them."""
    people, seen, in_sub = [], set(), False
    for line in lines:
        if any(s in line for s in STOP_ROSTER):
            break
        if re.match(r"^\s*SUBCOMMITTEE ON\b", line):
            in_sub = True
        for col in re.split(r"\s{3,}", line.strip()):
            m = ROSTER_LINE.match(col.strip())
            if not m:
                continue
            name = " ".join(w.capitalize() if w.isupper() and len(w) > 2 else w for w in m.group(1).replace("``", '"').replace("''", '"').split())
            role = {"chair": "chair", "chairman": "chair", "chairwoman": "chair", "rankingmember": "ranking_member", "ranking member": "ranking_member"}.get((m.group(3) or "").lower().replace("\n", ""), "member")
            if m.group(1).lower() in seen:
                if in_sub:
                    for p in people:
                        if p.name == name:
                            p.position = "subcommittee"
                            if role != "member":
                                p.role = role  # subcommittee chair / ranking member
                continue
            people.append(Person(name=name, role=role if not in_sub or role == "member" else role, honorific="", surname=name.split()[-1] if not name.endswith(("Jr.", "Sr.", "II", "III")) else name.split()[-2].rstrip(","), state=m.group(2), position="subcommittee" if in_sub else ""))
            seen.add(m.group(1).lower())
    return people


def parse_gpo_text(text: str, header: Header, mods_people: dict[str, Person] | None = None, source_url: str = "") -> Transcript:
    lines = text.splitlines()
    participants: dict[str, Person] = dict(mods_people or {})
    body_start = next((i for i, l in enumerate(lines) if CONVENED.search(" ".join(lines[i:i + 6]))), None)
    ## roster: between the committee name on the title page and the contents
    roster_start = next((i for i, l in enumerate(lines[20:], 20) if re.match(r"^\s+(COMMITTEE|SELECT COMMITTEE|JOINT|PERMANENT SELECT|COMMISSION)\b", l)), 20)
    sub_members = set()
    for p in roster(lines[roster_start:body_start or len(lines)]):
        k = person_key(p.name)
        if p.position == "subcommittee":
            sub_members.add(k); p.position = ""
        if k not in participants:
            participants[k] = p
        else:
            participants[k].state = participants[k].state or p.state
            if p.role != "member":
                participants[k].role = p.role
    by_surname = {}
    ## subcommittee members first, so an ambiguous surname in a subcommittee hearing goes to the member who sits on it
    for k, p in sorted(participants.items(), key=lambda kv: (kv[0] not in sub_members) if header.subcommittee or sub_members else 0):
        words = p.name.replace(",", "").split()
        by_surname.setdefault((p.surname or words[-1]).lower(), k)
        if len(words) >= 3 and words[-2].lower() in PARTICLES:  # "Jeff Van Drew" is "Mr. Van Drew" in the print
            by_surname.setdefault(f"{words[-2]} {words[-1]}".lower(), k); p.surname = f"{words[-2]} {words[-1]}"

    def key_for(honorific: str, surname: str) -> str:
        s = surname.lower()
        k = by_surname.get(s)
        if not k:
            k = person_key(surname); participants[k] = Person(name=surname, role="witness" if honorific in ("Mr", "Ms", "Mrs", "Miss", "Dr", "General", "Admiral", "Secretary", "Judge", "Ambassador", "Governor", "Mayor") and s not in by_surname else "unknown", honorific=honorific.rstrip(".") + ".", surname=surname)
            by_surname[s] = k
        p = participants[k]
        if not p.honorific or honorific.startswith(("Chair", "The Chair")):
            p.honorific = p.honorific or honorific.rstrip(".") + "."
        if honorific.startswith(("Chair", "The Chair")) and p.role in ("member", "unknown"):
            p.role = "chair"
        return k

    if body_start is not None:
        m = CONVENED.search(" ".join(l.strip() for l in lines[body_start:body_start + 8]))
        header.time_convened = header.time_convened or m.group(2).replace(" ", "")
        header.location = header.location or (m.group(3) or "").strip()
        pres = re.sub(r"\s+", " ", m.group(4)).strip(" ,")
        pk = person_key(pres)
        if pk not in participants:
            participants[pk] = Person(name=pres, role="chair", honorific="Mr.", surname=pres.split()[-1])
        participants[pk].role = "chair" if "chair" in m.group(5).lower() else participants[pk].role
        header.presiding = pk
        by_surname.setdefault(participants[pk].surname.lower(), pk)
    turns, inserts, in_appendix, pending_statement = [], [], False, None
    i = body_start or 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*A P P E N D I X|^\s*APPENDIX\s*$", line) and turns:
            in_appendix = True
        if line.strip().startswith("Present:") and not header.present:
            block, j = line.strip(), i
            while not block.endswith(".") and j + 1 < len(lines):
                j += 1; block += " " + lines[j].strip()
            m = PRESENT.match(block)
            if m:
                names = [n.strip() for n in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1)) if n.strip()]
                header.present = [by_surname.get(n.lower()) or by_surname.get(n.lower().split()[-1]) or person_key(n) for n in names]
            i = j + 1
            continue
        sm = STATEMENT.match(line)
        if sm and not in_appendix:
            pending_statement = sm.group(1); i += 1; continue
        dm = DIRECTION.match(line) if line.strip().startswith("[") else None
        if dm or (line.strip().startswith("[") and "]" not in line):
            text = line.strip()
            while "]" not in text and i + 1 < len(lines):
                i += 1; text += " " + lines[i].strip()
            text = text.strip("[] ")
            am = ADJOURNED.search("[" + text)
            if am:
                header.time_adjourned = header.time_adjourned or am.group(1).replace(" ", "")
            pm = PREPARED.search("[" + text + "]")
            if pm:
                who = pm.group(1)
                inserts.append(Insert(kind="prepared_statement", title=f"Prepared statement of {who}", for_person=by_surname.get(who.split()[-1].lower(), "")))
            elif "GRAPHIC" in text.upper():
                inserts.append(Insert(kind="graphic", title=text))
            else:
                from congress_api.transcribe.schema import Turn
                turns.append(Turn(speaker="", text=text, kind="direction"))
            i += 1
            continue
        tm = TURN.match(line)
        if tm and not in_appendix:
            from congress_api.transcribe.schema import Turn
            honorific, surname, first = tm.group(1), tm.group(2), tm.group(3)
            k = key_for(honorific, surname)
            para = [first]
            while i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith("    ") and not lines[i + 1].strip().startswith("["):
                i += 1; para.append(lines[i].strip())
            turns.append(Turn(speaker=k, text=" ".join(para), kind="statement" if pending_statement else "speech"))
            if pending_statement and participants[k].role in ("unknown",):
                participants[k].role = "witness"
            pending_statement = None
        elif line.startswith("    ") and line.strip() and turns and not in_appendix and not (inserts and inserts[-1].kind == "prepared_statement" and not inserts[-1].text.endswith("\n\n") and turns[-1].kind == "direction"):
            ## a new paragraph of the same speaker: the print indents it but doesn't repeat the name
            para = [line.strip()]
            while i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith("    ") and not lines[i + 1].strip().startswith("["):
                i += 1; para.append(lines[i].strip())
            last = next((t for t in reversed(turns) if t.kind != "direction"), None)
            if last is not None:
                last.text += " " + " ".join(para)
        elif inserts and (in_appendix or (inserts[-1].kind == "prepared_statement" and not inserts[-1].text.endswith("\n\n"))) and line.strip():
            inserts[-1].text += line.strip() + "\n"
        i += 1
    return Transcript(header=header, participants=participants, turns=turns, inserts=inserts, source=Source(kind="gpo_print", url=source_url))

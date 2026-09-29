"""
Parse a GPO printed hearing into the shared `Transcript` schema.

    from congress_api.transcribe.gpo_parse import parse_gpo_text
    t = parse_gpo_text(text, header, mods_people)   # text: the print as plain text (see gpo-transcripts)

A print's structure is typographic, and this parser reads the document's own conventions
rather than a vocabulary of its own:

- Paragraphs start at the print's indent (the most common indent in the file) and run to the
  next indented, bracketed or blank line.
- A speaker turn is a paragraph opening with an attribution: a short capitalized phrase ending
  in a period that recurs in the document ("Mr. Cline.", "Chairman Jordan.", "Dr. Putnam
  [continuing]."). Which leading words are titles is learned from the document: a token that
  precedes several different names ("Mr.", "Senator", "The") is a title; one that precedes a
  single name ("Van" before "Drew") is part of the name.
- Attributions resolve to participants by token suffix (`names.match`), preferring members the
  "Present:" line or the subcommittee roster names when a surname is shared.
- Stage directions are parenthetical paragraphs in either bracket style; the adjournment and
  the prepared-statement inserts are read from them. The convening sentence ("met ... at 2:02
  p.m. ... presiding") gives the time, place and presiding member; the roster page gives the
  members and their states.
- Anything not recognised continues the previous turn (or insert), so the words are never lost.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from congress_api.transcribe import names
from congress_api.transcribe.schema import Header, Insert, Person, Source, Transcript, Turn, person_key
from congress_api.models.gpo import GpoTranscriptText

TIME_RE = r"(\d{1,2}(?::\d{2})?\s?[ap]\.?\s?m\.?)"
CONVENED = re.compile(rf"\b(?:met|convened|called to order|reconvened)\b.{{0,80}}?\bat {TIME_RE}(.{{0,500}}?)\bpresiding\b", re.I | re.S)
ADJOURNED = re.compile(rf"whereupon,?\s+at\s+{TIME_RE}.{{0,120}}?\b(adjourned|recessed|concluded|recess)\b", re.I | re.S)
PRESENT = re.compile(r"^\s*(?:[A-Za-z ]{0,20})?\bpresent:\s*(.+)$", re.I)
STATEMENT_HEAD = re.compile(r"^\s*(?:opening |prepared |written )?(?:statements?|testimony|remarks) (?:of|by|from) (.+)$", re.I)
PREPARED = re.compile(r"the (?:prepared |written )?(?:statement|testimony|information|letter|report|material|response|answer|question)s? (?:of|from|submitted by|referred to|for the record)\s+(.+?)\s+(?:follows?|appears?|is |are |can be found|was |were )", re.I | re.S)
ROSTER_LINE = re.compile(r"^([A-Z][A-Za-z .'`\"’\-]+?(?:, (?:Jr|Sr|II|III|IV)\.?)?), ([A-Z][a-z]+(?: [A-Z][a-z]+)*)(?:, ?([A-Za-z ]*(?:Chair|Ranking)[A-Za-z ]*))?\s*$")
TOKEN = r"(?:[A-Z][a-z]{0,3}\.|[A-Z]\.|[A-Z][\w'\u2019\-]*|of|the|and)"  # "Mr.", "J.", "Van", "Drew", "of": only an abbreviation or initial may end in a period mid-attribution
ATTRIBUTION = re.compile(rf"^({TOKEN}(?: {TOKEN}){{0,5}})(?: \[[^\]]{{1,30}}\]| \([^)]{{1,30}}\))?(?<!\b[A-Z])\. (?=\S)")
ROLE_WORDS = {"chair": "chair", "chairman": "chair", "chairwoman": "chair", "chairperson": "chair", "cochair": "chair", "cochairman": "chair", "ranking": "ranking_member", "senator": "member", "representative": "member", "congressman": "member", "congresswoman": "member", "delegate": "member"}
WITNESS_TITLES = {"mr", "ms", "mrs", "miss", "dr", "hon", "general", "admiral", "colonel", "captain", "secretary", "judge", "ambassador", "governor", "mayor", "sheriff", "chief", "commissioner", "director", "professor", "reverend"}


def paragraph_indent(lines: list[str]) -> int:
    """The indent paragraphs start at: the most common leading-space count among lines with 2-10
    spaces before a letter, digit or bracket."""
    counts = Counter(len(l) - len(l.lstrip(" ")) for l in lines if re.match(r"^ {2,10}[\[(A-Za-z0-9\"']", l))
    return counts.most_common(1)[0][0] if counts else 4


def paragraphs(lines: list[str], indent: int) -> list[tuple[int, str, str]]:
    """(line_no, kind, text) for the file's paragraphs, from the indent alone: a line at the print's
    indent starts a paragraph ('para', or 'aside' when it opens with a bracket or parenthesis), a
    deeper indent is a heading line ('head'; consecutive ones merge), and an unindented line
    continues whatever is open."""
    out: list[tuple[int, str, str]] = []
    cur: list[str] = []
    kind, start = None, 0

    def flush():
        if cur:
            out.append((start, kind, " ".join(x.strip() for x in cur)))

    for i, l in enumerate(lines):
        st = l.strip()
        if not st:
            flush(); cur, kind = [], None
            continue
        lead = len(l) - len(l.lstrip(" "))
        if lead == indent:
            flush(); cur, start = [l], i
            kind = "aside" if st[0] in "[(" else "para"
            if kind == "aside" and st[-1] in "])":
                flush(); cur, kind = [], None
        elif lead > indent:
            if kind != "head":
                flush(); cur, start, kind = [l], i, "head"
            else:
                cur.append(l)
        elif kind is None:
            cur, start, kind = [l], i, "head"
        else:
            cur.append(l)
            if kind == "aside" and st[-1] in "])":
                flush(); cur, kind = [], None
    flush()
    return out


def learn_attributions(paras: list[tuple[int, str, str]]) -> tuple[Counter, set[str]]:
    """Recurring attributions and the document's title words. An attribution is the capitalized
    phrase a paragraph opens with; a title word is a first token that precedes two or more
    different second tokens ('Mr.' before Cline, Dunham, ...)."""
    counts: Counter = Counter()
    followers: dict[str, set] = defaultdict(set)
    for _, kind, text in paras:
        if kind != "para":
            continue
        m = ATTRIBUTION.match(text)
        if m:
            phrase = m.group(1)
            counts[phrase] += 1
            w = phrase.split()
            if len(w) > 1:
                followers[w[0].rstrip(".").lower()].add(w[1].lower())
    titles = {t for t, f in followers.items() if len(f) >= 2} | {"mr", "ms", "mrs", "miss", "dr", "the"} | WITNESS_TITLES | set(ROLE_WORDS)
    return counts, titles


def is_attribution(phrase: str, recurring: set[str], titles: set[str]) -> bool:
    """A recurring phrase, or one opening with a title, that ends in a name rather than a title
    ("Mr. Cline" yes; "Mr" from "Mr. Chairman, I yield" no; "The Chairman" yes)."""
    words = phrase.split()
    last = words[-1].rstrip(".").lower()
    if last in (titles - {"chairman", "chairwoman", "chair"}) or last in WITNESS_TITLES or last in ("of", "the", "and"):
        return False
    if len(words) == 1 and (last in ROLE_WORDS or last in titles):
        return False
    if any(w in ("of", "and") for w in words[1:-1]) and words[0].rstrip(".").lower() not in titles:
        return False  # "Statement of Dr. Robert D. Putnam" is a heading, not a speaker
    return phrase in recurring or words[0].rstrip(".").lower() in titles


def roster(lines: list[str]) -> tuple[list[Person], set[str]]:
    """Members from the two-column roster page ('DARRELL ISSA, California   JERROLD NADLER, New York,
    Ranking Member'), and the keys of those listed again under a subcommittee heading."""
    people, seen, sub, in_sub = [], {}, set(), False
    for line in lines:
        if re.search(r"C O N T E N T S|CONTENTS|Staff Director|Chief Counsel|Chief of Staff", line):
            break
        if people and re.match(r"^\s*SUBCOMMITTEE\b", line):
            in_sub = True
        for col in re.split(r"\s{3,}", line.strip()):
            m = ROSTER_LINE.match(col.strip())
            if not m:
                continue
            raw = m.group(1).replace("``", '"').replace("''", '"')
            name = " ".join(w.capitalize() if w.isupper() and len(w) > 2 else w for w in raw.split())
            role = next((r for w, r in ROLE_WORDS.items() if w in re.sub(r"\s", "", (m.group(3) or "").lower())), "member")
            k = person_key(name)
            if k in seen:
                if in_sub:
                    sub.add(k)
                    if role != "member":
                        seen[k].role = role
                continue
            p = Person(name=name, role=role, surname=names.surname(name), state=m.group(2))
            people.append(p); seen[k] = p
            if in_sub:
                sub.add(k)
    return people, sub


def parse_gpo_text(text: str | GpoTranscriptText, header: Header, mods_people: dict[str, Person] | None = None, source_url: str = "") -> Transcript:
    """Normalize a typed source extraction; plain text remains a legacy input."""
    text = text.text if isinstance(text, GpoTranscriptText) else text
    lines = text.replace("\r", "").splitlines()
    indent = paragraph_indent(lines)
    offsets, parts, pos = [], [], 0
    for l in lines:
        offsets.append(pos); parts.append(l.strip()); pos += len(l.strip()) + 1
    joined = " ".join(parts)

    ## the body starts at the convening sentence, else at the first recurring attribution
    conv = CONVENED.search(joined)
    body_line = max(i for i, off in enumerate(offsets) if off <= conv.start()) if conv else None
    paras_all = paragraphs(lines, indent)
    counts, titles = learn_attributions(paras_all)
    recurring = {a for a, n in counts.items() if n >= 2}
    if body_line is None:
        body_line = next((ln for ln, kind, t in paras_all if kind == "para" and ATTRIBUTION.match(t) and ATTRIBUTION.match(t).group(1) in recurring), 0)

    ## participants: the MODS record, then the roster page
    participants: dict[str, Person] = dict(mods_people or {})
    roster_people, sub_members = roster(lines[:body_line])
    for p in roster_people:
        k = names.match(participants, p.name) or person_key(p.name)
        if k in participants:
            participants[k].state = participants[k].state or p.state
            if p.role != "member":
                participants[k].role = p.role
        else:
            participants[k] = p
    prefer = set(sub_members) if (header.subcommittee or sub_members) else set()

    def resolve(reference: str, role_hint: str = "") -> str:
        """The participant an attribution or name refers to, created when unknown. "The Chairman" and
        other role-only references are the presiding member; "Davis of Illinois" is the Davis from
        Illinois."""
        words = reference.split()
        if header.presiding and all(w.rstrip(".").lower() in set(ROLE_WORDS) | {"the", "vice", "acting"} for w in words):
            return header.presiding
        title = words[0].rstrip(".").lower() if len(words) > 1 and words[0].rstrip(".").lower() in titles | set(ROLE_WORDS) | WITNESS_TITLES else ""
        name = " ".join(words[1:]) if title else reference
        state = None
        m_state = re.fullmatch(r"(.+?) of ([A-Z][a-z]+(?: [A-Z][a-z]+)?)", name)
        if m_state:
            name, state = m_state.group(1), m_state.group(2)
        from_state = {k for k, p in participants.items() if state and p.state and (p.state == state or p.state.lower() == state.lower())}
        k = names.match(participants, name, prefer=(from_state or prefer | set(header.present)))
        if not k:
            k = person_key(name)
            role = ROLE_WORDS.get(title) or ("witness" if title in WITNESS_TITLES else "unknown")
            participants[k] = Person(name=name, role=role_hint or role, surname=names.surname(name))
        p = participants[k]
        if title in ("mr", "ms", "mrs", "miss", "dr", "senator") and not p.honorific:
            p.honorific = title.capitalize() + ("." if title != "senator" else "")
        if ROLE_WORDS.get(title) in ("chair", "ranking_member") and p.role in ("member", "unknown"):
            p.role = ROLE_WORDS[title]
        return k

    if conv:
        header.time_convened = header.time_convened or re.sub(r"\s+", "", conv.group(1).lower())
        tail = conv.group(2)
        loc = re.search(r"\bin (?:the )?([^,;]*(?:room|Rm\.|Hall|Building|Center|Capitol|Courthouse)[^,;]*(?:,\s*[^,;]*Building)?)", tail, re.I)
        header.location = header.location or (re.sub(r"\s+", " ", loc.group(1)).strip(" ,") if loc else "")
        ## the presiding member: whichever participant the sentence names; else the capitalized phrase before "presiding"
        pres = next((k for k, p in participants.items() if p.role in ("chair", "ranking_member", "member") and re.search(r"\b" + re.escape(p.name.split()[-1]) + r"\b", tail)), None)
        if not pres:
            m = re.search(r"((?:[A-Z][\w'’\-]*\.? ){1,4})\s*[\[(]", tail) or re.search(r"((?:[A-Z][\w'’\-]*\.? ){1,4})$", tail.strip())
            if m:
                pres = resolve(re.sub(r"^(Hon\.|Honorable|Senator|Representative) ", "", m.group(1).strip()), role_hint="chair")
        if pres:
            header.presiding = pres
            if participants[pres].role in ("member", "unknown"):
                participants[pres].role = "chair"

    turns: list[Turn] = []
    inserts: list[Insert] = []
    in_appendix, pending_statement, open_insert = False, None, False
    for ln, kind, text in paras_all:
        if ln < body_line:
            continue
        if re.fullmatch(r"(A P P E N D I X|APPENDIX|A P P E N D I X E S|APPENDIXES|SUBMISSIONS? FOR THE RECORD|MATERIAL SUBMITTED FOR THE RECORD)\s*", text) and turns:
            in_appendix = True
            continue
        pm = PRESENT.match(text)
        if pm and not header.present and not in_appendix:
            body = re.sub(r"^(Representatives?|Senators?|Members?|Delegates?)\s+", "", pm.group(1).rstrip(". "))
            body = re.sub(r"\s*[\[(][^\])]*[\])]", "", body)  # "[presiding]"
            header.present = [resolve(n.strip(), role_hint="member") for n in re.split(r",\s*(?:and\s+)?|\s+and\s+|;\s*", body) if 0 < len(n.strip()) < 40]
            continue
        if kind == "aside":
            inner = text.strip("[]() ")
            am = ADJOURNED.search(text)
            if am:
                header.time_adjourned = header.time_adjourned or re.sub(r"\s+", "", am.group(1).lower())
            pr = PREPARED.search(text)
            if pr:
                inserts.append(Insert(kind="prepared_statement" if re.search(r"statement|testimony", text, re.I) else "submission", title=inner, for_person=names.match(participants, pr.group(1)) or ""))
                open_insert = not in_appendix and bool(re.search(r"follows?:?\]?\)?$", inner))
            elif "GRAPHIC" in inner.upper():
                inserts.append(Insert(kind="graphic", title=inner)); open_insert = False
            else:
                turns.append(Turn(speaker="", text=inner, kind="direction"))
            continue
        sm = STATEMENT_HEAD.match(text)
        if sm and not in_appendix and len(text) < 250:
            pending_statement = sm.group(1); continue
        if in_appendix:
            if inserts:
                inserts[-1].text += text + "\n"
            continue
        if kind == "head" and (len(text) < 80 or text.upper() == text):
            continue  # a heading: a title, a date, a centered label
        m = ATTRIBUTION.match(text)
        if m and is_attribution(m.group(1), recurring, titles):
            k = resolve(m.group(1))
            turns.append(Turn(speaker=k, text=text[m.end():], kind="statement" if pending_statement else "speech"))
            if pending_statement and participants[k].role == "unknown":
                participants[k].role = "witness"
            pending_statement, open_insert = None, False
        elif open_insert and inserts:
            inserts[-1].text += text + "\n"
        elif turns:
            last = next((t for t in reversed(turns) if t.kind != "direction"), None)
            if last is not None:
                last.text += " " + text
    return Transcript(header=header, participants=participants, turns=turns, inserts=inserts, source=Source(kind="gpo_print", url=source_url))

"""Names and affiliations in GPO witness lines and committee pages.

Read civil, clerical and military titles, suffixes and credentials, including
surname-first GPO lines. Return plain fields for the inventory and transcriber;
contents headings and offices are not names. No transcription dependency.
"""

import re

## a title before a name: civil ("Mr.", "The Honorable", "Ambassador"), clerical, or a military rank, in full
##  ("Lieutenant General", "Master Chief Petty Officer") or abbreviated ("Lt. Gen.", "LTG"), with "(Ret.)" after it
TITLE_WORD = ("(?:" + "|".join("""Hon Honorable Mr Ms Mrs Mx Dr Prof Professor Rev Reverend Pastor Rabbi Sister Sir Senator Sen Representative Rep Ambassador Amb
    Governor Gov Mayor President Officer Detective Sheriff Chief Lieutenant Lt Major Maj Brigadier Brig Vice Rear General Gen Admiral Adm Colonel Col Commander
    Cmdr Captain Capt Sergeant Sgt Master Command Technical Staff Petty Specialist Spc GEN LTG MG BG ADM VADM RADM COL LTC MAJ CPT CDR""".split()) + r")\.?")


TITLE = re.compile(r"^(?:The )?(" + TITLE_WORD + ")(?: " + TITLE_WORD + r")*(?: [(\[](?:Dr|[Rr]et(?:ired)?)\.?[)\]])? ")


SUFFIX = re.compile(r"^(Jr|Sr|II|III|IV)\.?$")


DEGREE = re.compile(r"^(?:(?:Ph|Ed|Psy|Pharm|Sc|M|J)\.? ?D|Dr\.? ?P\.? ?H|Esq)\.?$")


## letters after a name: "Ph.D.", "F.A.A.P.", "MPA", "USN (Ret.)"
CREDENTIAL = re.compile(r"^(?:(?:[A-Z]\.?){2,6}|(?:Ph|Ed|Psy|Pharm|Sc)\.? ?D\.?|Dr\.? ?P\.? ?H\.?|Esq\.?)(?: \(Ret\.?\))?$|^\(Ret\.?\)$")


CONNECTIVE = {"and", "of", "for", "the", "to", "in", "on", "from", "by", "with", "at"}


## a post rather than a person ("State Director"), a name GPO ran together with the post ("Byrum, John Executive
##  Director"), or a document listed among the witnesses ("Printed Hearing Record") holds a noun of office or of paper
NOT_A_NAME = {"director", "manager", "officer", "president", "secretary", "administrator", "commissioner", "commissioners", "chairman", "chairwoman", "counsel",
              "attorney", "founder", "owner", "executive", "specialist", "professional", "coordinator", "advocate", "advocacy", "superintendent", "treasurer",
              "record", "testimony", "statement", "hearing", "panel", "witnesses"}


def is_name(text: str) -> bool:
    """Could this be a person's name? GPO's witness lines include contents lines ("Answers to questions from
    the following ...") and the broken-off end of a position ("Security Officer and Security Services
    Administrator"); neither is two to six capitalised words without a connective, a noun of office or paper, or a digit."""
    words = [w.strip(",.-/").lower() for w in text.split()]
    return 2 <= len(words) <= 6 and text[:1].isupper() and not any(c.isdigit() for c in text) and not (CONNECTIVE | NOT_A_NAME) & set(words)


## GPO's footnote marker, "\1\", set after the item it annotates (a contents label, a name, a position)
FOOTNOTE = re.compile(r"\s*\\\d+\\")


## a contents label GPO sets before a witness's name ("Prepared statement", "Submitted questions:", "Additional
##  information from"), ended by its footnote marker, a dot leader and page, or nothing at all; a page can carry
##  GPO's character-entity residue ("60<greek-l>", "00 deg.")
LABEL_WORDS = (r"(?:(?:supplement to |joint )?(?:opening |prepared |written )?statements?(?: and attachments)?(?: \d+)?(?: of)?"
               r"|answers? to (?:submitted |additional )?questions|submitted questions"
               r"|additional (?:information|materials?)(?: (?:submitted )?for the record)?"
               r"|responses? to (?:submitted |additional |written )?questions)")
LABEL_END = r"(?:\s*\\\d+\\)*(?:\s*\.{3,}\s*(?:[\d\-]+\S*(?: deg\.)?)?)?"
CONTENTS_LABEL = re.compile(r"^\s*" + LABEL_WORDS + r":?(?:(?:\s*\\\d+\\)+" + LABEL_END + r"|\s*\.{3,}\s*(?:[\d\-]+\S*(?: deg\.)?)?)\s*", re.I)
## the same label with no marker, before a name: "Prepared statement Erik D. Olson", "Submitted questions: Avalos, ..."
UNMARKED_LABEL = re.compile(r"^\s*" + LABEL_WORDS + LABEL_END + r"(?::|\s+from|\s+with)?\s+(?=[A-Z])", re.I)
## a name that is still a contents label once read: the line names an entry, not a person
LABEL_NAME = re.compile(r"^\W*" + LABEL_WORDS + r"\b", re.I)


## GPO's footnote text, which runs on into the next witness's line ("... is available at http://...pdf. \2\ Mr. Peress
##  did not answer ... by the time of publication. David Mallino, ..."): a line holding it names, at most, whoever
##  follows its last sentence; one holding nothing after it names no one
FOOTNOTE_TEXT = re.compile(r"(?:has|have|are|is) been retained in|retained in the files|(?:is|are) available (?:at|as part)"
                           r"|by the time of (?:publication|printing)|^\W*time of (?:publication|printing)", re.I)
FOOTNOTE_END = re.compile(r"(?:\.pdf|EventID=\d+|time of (?:publication|printing))\.\s+|retained in the files of the Committee\s+", re.I)


## a contents entry's dot leader and what follows it ("..., Nebraska \1\......... Prepared statement")
LEADER_TAIL = re.compile(r"\s*\.{4,}.*$")


def drop_footnote_text(text: str) -> str:
    """The line after GPO's footnote text, or "" when footnote text runs to its end."""
    if not FOOTNOTE_TEXT.search(text):
        return text
    ends = list(FOOTNOTE_END.finditer(text))
    rest = text[ends[-1].end():] if ends else ""
    return "" if FOOTNOTE_TEXT.search(rest) else rest


def strip_contents_markers(text: str) -> str:
    """A GPO line without footnote text, contents labels and footnote markers: "Prepared statement \\1\\ Answers to
    submitted questions\\2\\ John Bozzella, ..." is John Bozzella's line. A label with no marker is dropped only
    when a name follows it, so "Prepared statement on H.R. 841" stays as GPO wrote it."""
    text = drop_footnote_text(text)
    while (label := CONTENTS_LABEL.match(text)):
        text = text[label.end():]
    if (label := UNMARKED_LABEL.match(text)) and is_name(_name_of(text[label.end():])):
        text = text[label.end():]
    return LEADER_TAIL.sub("", FOOTNOTE.sub("", text)).strip()


def _name_of(text: str) -> str:
    return witness(text)["name"]


def witness(text: str) -> dict:
    """A witness from GPO's line for them. GPO writes the line three ways: "Mr. Nels Leader, Vice President,
    Bread Alone Bakery", "Richard J. Powell, Executive Director, ClearPath", and surname first, "Campbell, Jr.,
    J.H., President and CEO, Associated Grocers". A name written in order has at least two words before the
    first comma, so a single word there is a surname, alone or with its suffix ("Chodak III, Dr. Paul"). Some
    records carry the contents line instead ("Statement of Dr. Robert D. Putnam, ...", "Panel One Thomas J.
    Murphy, ...")."""
    text = strip_contents_markers(text)
    text = re.sub(r"^\s*(?:(?:opening |prepared |written )?(?:statements?|testimony|remarks) (?:of|by|from)|accompanied by:?|witness(?:es)?:?|panel \w+:?)\s+", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*\([^)]*\d[^)]*\)|\s*[(\[](?:\w+ )?(?:ret|retired|fmr|former)\.?[)\]]", "", text, flags=re.I)  # "Gary Kennedy (H.R. 1963)", "J. Roy Robinson (Ret.)"
    title = TITLE.match(text)
    parts = [s.strip() for s in text[title.end() if title else 0:].split(",") if s.strip()]
    name, rest = (parts[0] if parts else ""), parts[1:]
    if len(name.split()) == 2 and SUFFIX.match(name.split()[1]):
        name, rest = name.split()[0], [name.split()[1]] + rest
    if name and " " not in name and rest:
        suffix = rest.pop(0) if SUFFIX.match(rest[0]) else ""
        ## "Woodruff, Ph.D., MPH, Tracey": degrees stand before the given name; initials in their place ("J.H.") are the given name
        after = next((i for i, s in enumerate(rest) if not CREDENTIAL.match(s)), None)
        if rest and DEGREE.match(rest[0]) and after and is_name(f"{rest[after]} {name}"):
            rest = rest[after:]
        given = rest.pop(0) if rest else ""
        title = title or TITLE.match(given + " ")  # "Roe, Hon. David P., a Representative in Congress ..."
        given = TITLE.sub("", given + " ").split()
        if given and SUFFIX.match(given[-1]):
            suffix = given.pop()  # "Mehan, G. Tracy III"
        name = " ".join(filter(None, [*given, name, suffix]))
    elif rest and SUFFIX.match(rest[0]):
        name = f"{name} {rest.pop(0)}"
    name = re.sub(r"\s*[(\[][^)\]]*[)\]]?$", "", name)  # "Elton John (Via Videoconference)", "Tom Malinowski [D-NJ]", "Lorne W. Craner (former Assistant Secretary"
    words = name.split()
    while len(words) > 2 and CREDENTIAL.match(words[-1]) and not SUFFIX.match(words[-1]):
        words.pop()  # "Brian S. Eifler USA", "Puneet S. Arora MD MS"
    name = " ".join(words)
    # Degrees immediately follow the name. Later comma-separated abbreviations
    # can be an employer's suffix (LLC) or location (Washington, D.C.).
    while rest and CREDENTIAL.match(rest[0]):
        rest.pop(0)
    honorific = title.group(1) if title else ""
    return {"name": name, "honorific": honorific if honorific in ("Mr.", "Ms.", "Mrs.", "Dr.") else "",
            "position": rest[0] if rest else "", "organization": ", ".join(rest[1:])}


def person_key(name: str) -> str:
    """'Hon. Ben Cline' -> 'cline-ben'; 'Mr. Dunham' -> 'dunham'."""
    parts = [p for p in re.sub(r"[^\w\s-]", "", name).lower().split() if p not in ("hon", "the", "mr", "ms", "mrs", "dr", "senator", "representative", "chairman", "chairwoman", "chair", "jr", "sr", "ii", "iii")]
    if not parts:
        return "unknown"
    return parts[-1] if len(parts) == 1 else f"{parts[-1]}-{parts[0]}"

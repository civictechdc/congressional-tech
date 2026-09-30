"""
Matching the way a proceeding refers to people ("Mr. Van Drew", "Chairman Jordan", "Ms. Jackson
Lee", "Jeff Van Drew") to the participants known from the roster and witness list.

A reference matches a participant when its name tokens are a suffix of the participant's
name tokens, compared without punctuation or case: "Van Drew" ends "Jefferson Van Drew",
"Lee" ends both "Laurel M. Lee" and "Sheila Jackson Lee". Ties go to whoever `prefer`
names (the members listed as present, the subcommittee's members), then to the first.
No lists of surname particles or honorifics are needed: what isn't a title is a name.
"""

from __future__ import annotations

import re

from congress_api.models.transcription import Person

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def tokens(name: str) -> list[str]:
    """Lower-case name tokens without punctuation, initials and generational suffixes: 'Sheila Jackson Lee' -> ['sheila', 'jackson', 'lee']."""
    out = []
    for t in re.sub(r"[^\w\s'\-]", " ", name.replace("’", "'")).lower().split():
        t = t.strip("'-")
        if t and t not in SUFFIXES and (len(t) > 1 or not t.isalpha()):
            out.append(t)
    return out


def match(participants: dict[str, Person], reference: str, prefer: set[str] = frozenset()) -> str | None:
    """The key of the participant `reference` names, or None."""
    ref = tokens(reference)
    if not ref:
        return None
    names = {key: tokens(person.name) for key, person in participants.items()}
    hits = [key for key, full in names.items() if full[-len(ref):] == ref]
    if not hits:
        ## a single token may also be the reference's last word matching the participant's surname alone
        last = ref[-1]
        hits = [key for key, full in names.items() if full[-1:] == [last]]
    if not hits:
        return None
    return next((key for key in hits if key in prefer), hits[0])


def surname(name: str, titles: set[str] = frozenset()) -> str:
    """The part of a name a print attributes turns by: everything after the first name, so
    multi-word surnames survive ("Van Drew", "Jackson Lee"). With `titles`, a leading title is dropped."""
    words = [w for w in name.replace(",", "").split() if w.rstrip(".").lower() not in SUFFIXES]
    if words and words[0].rstrip(".").lower() in titles:
        words = words[1:]
    if len(words) <= 1:
        return " ".join(words)
    ## initials and first names come first; the surname is what follows the last initial/first name
    if len(words) == 2:
        return words[1]
    return " ".join(words[2:]) if re.fullmatch(r"[A-Z]\.?", words[1]) else " ".join(words[1:])

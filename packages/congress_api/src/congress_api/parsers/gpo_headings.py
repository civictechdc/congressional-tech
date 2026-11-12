"""A GPO printed hearing's own record of who came to the table: its testimony headings, the people they name, and
its committee roster page (ct-sfra; owner decision 2026-11-11, 'Transcripts decide in the rule').

    from congress_api.parsers.gpo import parse_transcript_html
    from congress_api.parsers.gpo_headings import transcript_entries
    entries = transcript_entries(parse_transcript_html(body).text)

Read from the print's typography only, never from the index or any other record:

- The proceedings run from each day's convening line (a weekday date: 'WEDNESDAY, APRIL 25, 2012') after the
  contents to the next '[Whereupon ... adjourned / recessed / concluded]' marker, and resume at the next convening
  line or a resumed session ('AFTERNOON SESSION', '... reconvened ...'). A print whose text stops mid-day runs to its
  end. Text after an adjournment (the appendix, material submitted for the record) is not read.
- A testimony heading is a capitals line in the proceedings opening '[OPENING|PREPARED|JOINT|ORAL|SUPPLEMENTAL]
  STATEMENT(S)|TESTIMONY|REMARKS OF|BY ...', with its capitals continuation lines. 'Capitals' allows a word with
  one or two lower-case letters ('McCASKILL', 'DeGETTE', 'Jr.'); the inserted 'Prepared Statement of ...' is not one.
  Each ';' piece names one person (a leading 'AND' dropped; ', AND HON. ...' starts another): the name is the
  piece up to its first comma, the style the rest. Names after 'ACCOMPANIED BY' were at the table too ('accompanying').
  A heading of a group ('STATEMENTS OF COMMITTEE MEMBERS') names no one.
- The proceedings' 'Also present: Senator Boxer and Representative Dreier.' names people at the hearing who are not
  on the committee (kind 'present'): a Member who introduces a nominee or sits in by consent is named there, often
  with no heading of their own. 'Members present' (the committee) and 'Staff present' are not read.
- The roster page is the committee list before the contents, read by gpo_text.roster ('NAME, State[, Role]') from its
  columns of a capitals name: every roster the front matter prints (a print can carry two, CHRG-107shrg78075 before and
  after the 2001 change of majority), columns two spaces apart when a long name leaves no more ('ERIC A. ``RICK''
  CRAWFORD, Arkansas  JOE COURTNEY, Connecticut'), and no staff line ('Dave Conover, Staff Director' is mixed case).

Each entry: kind ('statement', 'opening', 'prepared', 'accompanying', 'present' or 'roster'), name as printed, family and given
(name_key), style (the person's words after the name; for the roster, state and role) and line (1-based, in the text;
none for the roster). Cost: one pass over the text's lines, O(L).
"""
from __future__ import annotations

import re
import unicodedata

from congress_api.parsers.gpo_text import roster

KIND = re.compile(r"^\s*(?P<kind>(?:(?:OPENING|PREPARED|JOINT|ORAL|SUPPLEMENTAL)\s+)?(?:STATEMENTS?|TESTIMONY|REMARKS))"
                  r"\s+(?:OF|BY)(?:\s+(?P<rest>\S.*))?\s*$")
LOWER_RUN = re.compile(r"[a-z]{3,}")
CONTENTS = re.compile(r"^\s*(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|CONTENTS)\s*$")
CONVENING = re.compile(r"^\s*(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),\s+[A-Z]+\.?\s+\d{1,2},?\s+\d{4}\s*$",
                       re.I)
RESUMED = re.compile(r"^\s*(?:MORNING|AFTERNOON|EVENING)\s+SESSION\s*$"
                     r"|^\s+The\s+(?:Committee|Subcommittee|Commission|Caucus|Panel)\b[^.\[]{0,80}\breconvened\b", re.I)
ADJOURNED = re.compile(r"\[Whereupon\b[^\]]*?\b(?:adjourn|recess|conclu)", re.I)
STAFF = re.compile(r"Staff Director|Chief Counsel|Chief of Staff|Staff Member|Counsel\b|Clerk\b", re.I)
GROUP = re.compile(r"^(?:THE\s+)?(?:COMMITTEE\s+MEMBERS|MEMBERS|WITNESSES|SENATORS|REPRESENTATIVES|PANEL)\b")
ACCOMPANIED = re.compile(r"[;,]?\s*\bACCOMPANIED\s+BY:?\s*")
# 'Also present: ...' to the sentence's end: a period that closes its line or comes before another '... present:', and
# is not an initial's ('Hon. G.K.' at a line's end).
ALSO_PRESENT = re.compile(r"\bAlso\s+[Pp]resent:\s*(?P<names>.{0,600}?)(?<![\s.][A-Z])\.(?=[ \t]*(?:\n|$)|\s+[A-Z][a-z]+\s+[Pp]resent:)",
                          re.S)
PRESENT_TITLES = re.compile(r"\b(?:Senators?|Representatives?|Delegates?|Resident Commissioner|Congress(?:man|woman)|Hon\.|"
                            r"Honorable|Chairman|Chairwoman)\s+|\([^)]*\)|\[[^\]]*\]")
TITLE_START = (r"(?:THE\s+)?(?:HON\.?|HONORABLE|MR\.|MS\.|MRS\.|DR\.|SENATOR|REPRESENTATIVE|CONGRESSMAN|CONGRESSWOMAN|"
               r"GOVERNOR|MAYOR|GENERAL|GEN\.?|ADMIRAL|ADM\.?|SECRETARY|AMBASSADOR|JUDGE)\b")
TITLES = frozenset(
    'the hon honorable mr mrs ms miss mx dr senator sen representative rep congressman congresswoman delegate governor '
    'mayor gen general lt lieutenant col colonel maj major capt captain adm admiral vadm radm rear vice brigadier sgt '
    'sergeant rev reverend father sister rabbi judge secretary ambassador chief sheriff professor prof commissioner '
    'chairman chairwoman'.split())
SUFFIXES = frozenset('jr sr ii iii iv md phd esq ret'.split())


def name_key(name: str) -> tuple[str, str]:
    """(family, given) of a printed name: accents folded, lower case, nicknames in quotes or parentheses and
    apostrophes dropped, words split at anything not a letter ('ROYBAL-ALLARD' is two), leading titles and suffix words
    dropped; the family is the last word and the given the first letter of the first, '' when the name is one word.
    The model reads a MODS name the same way (model/sql/witness-transcript-rows.sql)."""
    text = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower()
    text = re.sub(r"``[^']*''|\"[^\"]*\"|\([^)]*\)", ' ', text).replace("'", '')
    words = [w for w in re.findall(r"[a-z]+", text) if w not in SUFFIXES]
    while len(words) > 1 and words[0] in TITLES:
        words = words[1:]
    if not words:
        return '', ''
    return words[-1], words[0][0] if len(words) > 1 else ''


def _capitals(line: str) -> bool:
    return bool(re.search(r"[A-Z]", line)) and not LOWER_RUN.search(line)


def _pieces(text: str, *, bare_and: bool) -> list[str]:
    """One piece per person: ';' separates people, and so does ', AND' before a title. With bare_and (a list after
    'ACCOMPANIED BY'), so does 'AND' in a piece with no comma ('JOHN DOE AND JANE ROE'); 'MINERALS AND REALTY' in a
    person's style is not split."""
    pieces = []
    for piece in re.split(r";\s*", text):
        piece = re.sub(r"^AND\s+", '', piece.strip(' ,.'))
        for part in re.split(rf",?\s+AND\s+(?={TITLE_START})", piece):
            pieces += re.split(r"\s+AND\s+", part) if bare_and and ',' not in part else [part]
    return [p.strip(' ,.') for p in pieces if p.strip(' ,.')]


def _people(rest: str):
    """(name, style) of each person a heading's text names, then of each named after 'ACCOMPANIED BY'."""
    main, *accompanied = ACCOMPANIED.split(rest, maxsplit=1)
    named = []
    for piece in _pieces(main, bare_and=False):
        if named and re.match(r"(?:ON BEHALF|REPRESENTING|FORMERLY)\b", piece):
            named[-1] = (named[-1][0], f"{named[-1][1]}; {piece}".strip('; '))
            continue
        name, _, style = piece.partition(',')
        named.append((name.strip(), style.strip()))
    with_table = [(name.strip(), style.strip()) for name, _, style in
                  (piece.partition(',') for piece in (_pieces(accompanied[0], bare_and=True) if accompanied else ()))]
    return named, with_table


def _present(lines: list[str], i: int) -> list[tuple[str, int]]:
    """(name, line) of each person an 'Also present:' sentence starting on line i names."""
    found = ALSO_PRESENT.search('\n'.join(lines[i:i + 8]))
    if not found:
        return []
    names = PRESENT_TITLES.sub(' ', re.sub(r"\s+", ' ', found.group('names')))
    return [(name, i + 1) for name in (n.strip(' ,.') for n in re.split(r",\s*(?:and\s+)?|\s+and\s+|;\s*", names))
            if name and len(name.split()) <= 4]


def _roster_columns(front: list[str]) -> list[str]:
    """The front matter's 'NAME, State[, Role]' columns whose name is printed in capitals, one per line."""
    columns = []
    for line in front:
        if STAFF.search(line):
            continue
        for column in re.split(r"\s{3,}|(?<=[a-z.])\s{2,}(?=[A-Z])", line.strip()):
            name, _, rest = column.partition(',')
            if rest and re.match(r"(?:\s(?:Jr|Sr|II|III|IV)\.?,)?\s[A-Z][a-z]", rest) and re.search(r"[A-Z]{2}", name) \
                    and not LOWER_RUN.search(name):
                columns.append(column)
    return columns


def _entry(kind, name, style, line):
    family, given = name_key(name)
    return dict(kind=kind, name=name, family=family, given=given, style=style or None, line=line)


def transcript_entries(text: str) -> list[dict]:
    lines = text.replace('\r', '').split('\n')
    contents = next((i for i, line in enumerate(lines) if CONTENTS.match(line)), None)
    start = contents + 1 if contents is not None else 0
    first = next((i for i in range(start, len(lines)) if CONVENING.match(lines[i])), None)
    front = lines[:contents if contents is not None else (first if first is not None else 0)]
    entries = [_entry('roster', person.name, ', '.join(filter(None, (person.state, None if person.role == 'member' else person.role))), None)
               for person in roster(_roster_columns(front))[0]]
    # A print with no convening line is read from its contents on.
    on, i = first is None, start
    while i < len(lines):
        line = lines[i]
        if CONVENING.match(line) or RESUMED.search(line):
            on = True
        if ADJOURNED.search(line):
            on = False
        if on and 'resent:' in line and re.search(r"\bAlso\s+[Pp]resent:", line):
            entries += [_entry('present', name, None, n) for name, n in _present(lines, i)]
        found = KIND.match(line) if on and _capitals(line) else None
        if not found:
            i += 1
            continue
        rest, j = found.group('rest') or '', i + 1
        while j < len(lines) and j - i < 6 and lines[j].strip() and _capitals(lines[j]) and not KIND.match(lines[j]):
            rest += ' ' + lines[j].strip()
            j += 1
        rest = re.sub(r"\s+", ' ', rest).strip()
        word = found.group('kind')
        kind = 'opening' if word.startswith('OPENING') else 'prepared' if word.startswith(('PREPARED', 'SUPPLEMENTAL')) \
            else 'statement'
        if not GROUP.match(rest):
            named, with_table = _people(rest)
            entries += [_entry(kind, name, style, i + 1) for name, style in named]
            entries += [_entry('accompanying', name, style, i + 1) for name, style in with_table]
        i = j
    return entries

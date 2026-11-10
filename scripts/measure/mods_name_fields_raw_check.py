"""Judge a MODS re-read of witness name fields against the raw lines and other publishers' names (ct-rg34).

    mods_name_fields_raw_check.py --before GEN.parquet --after GEN.parquet --raw-root BODIES
        --people WITNESSES.parquet --output OUT.json [--accept REVIEWED.json] [--plant KIND]

The re-read under test moves an organization out of a witness name ("American Legion" alone, or before
the person: "Vietnam Veterans of America, Richard F. Weidman, ...") and joins a surname written first to its
given name ("Torres Small, Hon. Xochitl, ..."); it also types record entries and names the Members who asked
questions for the record (ct-3aap, ct-zs48). ``--before`` and ``--after`` are appearance generations
(appearance_records rows); only ``mods`` rows are read. ``--raw-root`` holds the retained bodies as
``<sha[:2]>/<sha>.gz``; each body's ``<witness>`` lines and ``<congMember>`` names are read here with
ElementTree. ``--people`` is a published witnesses table: the first and last words of the names the *other*
sources state (Congress.gov, House XML, Senate pages, never MODS) are the given and family names this check
knows. The rule reads organization words, separators and titles; this check reads which words other publishers
use as people's given and family names, the print's own ``<congMember>`` names, and the raw line's words.

Asking lines and Members, read without the rule (``asking_lines``, ``member_groups``). A line is an *asking* line
when it holds the word "question(s)" or "request(s)" anywhere, in any case (the rule reads a heading's grammar:
which words come before "from", "by" or "of"); or when it prints names alone (no office, document or heading
word) and follows an asking line, starts a list with "Senators", names two Members or more, or names one by a
chamber or committee title with page numbers. The Members a line names are counted as sets of words, never by
splitting a list: each ``<congMember>`` family name the line prints (any case); every capitalised word after
"Senator(s)", "Representative(s)", "Delegate" or "Congressman" up to a lower-case word, a number or a mark that
ends a name (after a plural title a comma or "and" starts the next Member); and the capitalised words after
"Hon."/"Honorable" that the House style follows ("a Representative in Congress from", "of <a State>").

Both directions, per occurrence key (body, locator); every flag fails the check:

- an occurrence or a body on one side only (``added``, ``removed``, ``unpaired_bodies``), except a line the
  before side read no occurrence for at all, now kept at its own locator with a supported type and, if named, a
  person's name its raw line holds in order: one opening with a known given name or made of the print's
  ``<congMember>`` words (listed under ``restored``); and except an asker (below). Every further part of a line
  (``/part[3]`` on) is ``added`` unless it is an asker;
- ``asker`` (listed, not failing): a row the before side lacks, typed ``record_material`` on an asking line, whose
  name's words the line prints in that order and whose family word is a Member's of that line;
- ``person_moved``: a changed name that opens with a known given name and whose words the new name lacks;
- ``name_not_in_line``: a new or added name with a word its raw line lacks;
- ``words_lost``: a changed occurrence that loses a word across name, position, organization and
  on_behalf_of (credentials such as "M.D." and titles such as "Hon." may go, as for every witness line; on an
  asking line, so may its heading's words);
- ``words_gained``: a changed occurrence that gains a word its raw line lacks;
- ``person_left_in_organization``: a changed occurrence left without a name whose raw line still has a
  later segment opening with a known given name;
- ``reorder_unsupported``: a new or restored name whose words are not in the raw line in that order (a surname
  joined to its given name) and that does not open with a known given name and end with a known family name;
- ``order_unsupported``: on a line with two named rows or more, rows whose display order does not follow where
  their family names stand in the raw line (any row, changed or not);
- ``name_not_person``: a new name that is a place (a U.S. state, or a segment the raw line follows with a
  state), or that opens with no known given name, is not made of the print's ``<congMember>`` words, and either
  a later segment of its raw line opens with a known given name (a committee title such as "Chairman" before it
  aside) or the line names a document and no person;
- ``split_unsupported``: an added ``<locator>/part[2]`` (a joined line read as two people, ct-zs48) unless it is
  an asker, or its parent occurrence is on both sides with the same name, the words the parent loses are exactly
  the words the new occurrence holds, and the new name is in the raw line in order, opening with a known given
  name and ending with a known family name. A passing split is listed under ``split`` and its parent's moved
  words are not counted as lost;
- ``type_unsupported``: a changed ``witness_type`` unless it goes from none to ``statement_for_record`` on an
  occurrence with no name, an organization, and a raw line that names a document anywhere (any of
  ``DOCUMENTS``) and no person (no segment opening with a known given name, no civil title) (ct-3aap); or it
  is ``record_material`` on an asking line for a row with no name, a Member's family word, or on a line of names
  alone;
- ``question_asker_as_witness``: any after occurrence, changed or not, left a witness (no type) on an asking line,
  unless it names a person who is not one of the line's Members: two name words or more the line prints, none a
  heading, document or office word, its family word not a Member's;
- ``member_unnamed``: an asking line, or one holding a ``record_material`` occurrence, with a Member's word (any
  of the counts above) that no occurrence of that line names. Reported at the line's locator with the words left
  unnamed;
- ``record_as_witness``: any after occurrence, changed or not, typed a witness (no type) that names no one, on a
  raw line that names no person and names a document (``DOCUMENTS``), quotes a title or prints a date: a
  document's title or an organization's own statement left a witness. The rule types titles by a reviewed list and
  statements by a document word ending the line; it reads no quotation or date.

``--accept`` names flagged occurrences a person has read and accepted, each as ``{"body", "locator", "flag",
"after", "line_sha256", "reason", "reviewed_by"}``: ``after`` holds the new values the person read,
``line_sha256`` the sha256 of the stripped raw line they read, ``reason`` what the line is, in their words, and
``reviewed_by`` who read it. Only a signed entry (all three set) counts; the others are listed under
``unsigned_accept`` and cover nothing. An accept covers only that line and the occurrence's name, position,
organization, on_behalf_of, honorific, witness_type, bioguide_id and display_order (``KEYED``): any other new
value under the same flag fails, and a signed entry the run no longer flags fails as ``stale_accept``. Accepts are
written per row by the person who read it, never generated from the parser's reviewed lists, so a pass on a
reviewed row is a person agreeing with the raw line, not the list agreeing with itself. Listed for a person to
read, without failing: ``unconfirmed`` new names that open with no known given name; ``residual`` unchanged
names that open with no known given name on a raw line with a later segment that does. Bodies that are missing or
do not parse are listed in ``not_read`` and still compared without a line.

What it cannot see: it cannot tell an organization from a person whose given name other publishers do not
state twice. Such new names land in ``unconfirmed`` (132 on the 2026-11-08 run), which never fails; a swap of
an organization for a rare-named person ("Nancy-Ann DeParle", "Ikeita Cantu Hinojosa", "Yasmina S. Vinci")
passes unseen. Its "segment the raw line follows with a state" test for ``name_not_person`` restates the rule's
own place heuristic, more strictly (the rule exempts MD, MA, MS and PA as credentials; this check does not), so
it is not an independent measure of places. It reads a document word anywhere in the line, where the typing rule
reads one ending the line, so a line naming a document inside an organization's name and ending in one passes on
either reading. It does not judge honorific or bioguide_id changes, nor a split whose second person has a given
name other publishers do not state twice (that split fails, for a person to accept). Its Members and the rule's
share two facts, the print's ``<congMember>`` list and the chamber titles; a Member printed with "Hon." alone whom
that list omits is not counted (the rule also declines such lines, and reviewed entries name them), so a dropped
asker of that kind is not seen. A line of names alone under an asking line counts as asking, so a Member who
testified and is printed alone right under a question heading counts as an asker (the rule's known limit, ct-gfo7
item 5). An asking line's word "question" can stand in footnote text; a ``<congMember>`` family name there that is
also a witness's ("Perry") counts as a Member. ``question_asker_as_witness`` takes any two-word name the line prints
as a person, so a document's title of two plain words left a witness on an asking line passes; ``record_as_witness``
misses a title that prints no document word, quotation or date ("Our Projects, DOE, Loan Programs Office", 1 of the
16 reviewed titles).

``--plant`` writes one wrong value the rule could produce on the after side, and the check must flag it,
accepted or not: ``person-moved`` moves an unchanged person's name into the organization
(``person_moved``); ``reversed-name`` writes a joined name surname first (``reorder_unsupported``);
``previous-segment`` replaces a person read after an organization with the raw segment before them
(``name_not_person``); ``split-untrimmed`` leaves a split's parent holding the second person's words
(``split_unsupported``); ``typed-organization`` types an organization alone whose line names no document
(``type_unsupported``); ``asker-as-witness`` leaves a Member listed under a question heading as a witness
(``question_asker_as_witness``); ``asker-dropped`` drops one of several Members a record line names as askers
(``member_unnamed``); ``title-as-witness`` and ``statement-as-witness`` type a nameless record row holding an
organization (a document's title, an organization's statement) as a witness (``record_as_witness``);
``heading-as-name`` names a restored question heading for its own text before the colon (``added``);
``name-emptied`` empties a restored heading's asker (``member_unnamed``); ``committee-segment`` replaces a Member
read after a committee title ("...from: Chairman Michael B. Enzi") with the segment before it
(``name_not_person``); ``reversed-asker`` writes a new asker's name surname first ("Tester Jon",
``reorder_unsupported``); ``askers-swapped`` exchanges the names of two askers of one line (``order_unsupported``);
``witness-as-asker`` types an unchanged witness on a line that asks nothing as record material
(``type_unsupported``); ``heading-reverted`` puts back one witness named for the heading where a line's askers
stand (``question_asker_as_witness``); ``given-added`` gives an asker named by surname alone a first name the
line lacks ("Bill Boxer", ``name_not_in_line``).
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

FIELDS = ('name', 'position', 'organization', 'on_behalf_of')
TITLES = set('the hon honorable mr mrs ms miss dr prof professor rev reverend senator sen representative rep ambassador '
             'general gen admiral adm colonel col lieutenant lt major maj captain capt sergeant sgt commander brigadier vice rear '
             'master rabbi sister pastor esq'.split())
# A committee title before a Member's name ("Chairman Michael B. Enzi", "Ranking Member Bernard Sanders") is not part of
# the name. Read only in names, never as a credential a field may shed.
COMMITTEE = {'chairman', 'chairwoman', 'ranking', 'member'}
SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv'}
KEYED = (*FIELDS, 'honorific', 'witness_type', 'bioguide_id', 'display_order')
FLAGS = ('added', 'removed', 'person_moved', 'name_not_in_line', 'words_lost', 'words_gained',
         'person_left_in_organization', 'reorder_unsupported', 'order_unsupported', 'name_not_person',
         'split_unsupported', 'type_unsupported', 'question_asker_as_witness', 'member_unnamed', 'record_as_witness')
PLANTS = {'person-moved': 'person_moved', 'reversed-name': 'reorder_unsupported', 'previous-segment': 'name_not_person',
          'split-untrimmed': 'split_unsupported', 'typed-organization': 'type_unsupported',
          'asker-as-witness': 'question_asker_as_witness', 'asker-dropped': 'member_unnamed',
          'title-as-witness': 'record_as_witness', 'statement-as-witness': 'record_as_witness', 'heading-as-name': 'added',
          'name-emptied': 'member_unnamed', 'committee-segment': 'name_not_person',
          'reversed-asker': 'reorder_unsupported', 'askers-swapped': 'order_unsupported',
          'witness-as-asker': 'type_unsupported', 'heading-reverted': 'question_asker_as_witness',
          'given-added': 'name_not_in_line'}
# Words that make a line ask: what was asked or requested, read anywhere in the line, in any case.
ASKING = {'question', 'questions', 'request', 'requests'}
# The words of an asking line's heading, which are no person's.
HEADING = ASKING | set('response responses answer answers submitted record hearing arising during written additional '
                       'posthearing supplemental'.split())
CHAMBER = {'senator', 'senators', 'sen', 'representative', 'representatives', 'rep', 'congressman', 'congresswoman',
           'delegate'}
MEMBER_TITLES = CHAMBER | {'hon', 'honorable', 'chairman', 'chairwoman', 'ranking'}
# Words a line of names alone may print besides names: a Member's style and list words.
LIST_WORDS = set('the of and a in from congress state commonwealth district columbia resident commissioner '
                 'member'.split())
# What a document's title prints and an organization's name does not: a quotation, or a date.
QUOTED = re.compile(r"\"|''|``")
DATED = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?:\d{1,2},\s*)?\d{4}\b")
# Words that name a document submitted for the record, read anywhere in a line.
DOCUMENTS = set('statement statements letter letters memorandum memo article articles paper papers report reports '
                'attachment attachments testimony comments submission summary excerpt study analysis editorial '
                'resolution petition exhibit packet'.split())
CIVIL = {'hon', 'honorable', 'mr', 'mrs', 'ms', 'dr'}
# Words of an office, which a witness's entry has and a Member's style in a question list does not.
OFFICES = set('director president secretary administrator chief officer counsel manager deputy assistant executive '
              'professor commissioner governor mayor attorney judge inspector general association department office '
              'university institute agency bureau council board foundation company inc commission former'.split())
# Words no person's name is made of, read for a witness row on an asking line.
NOT_PERSON = HEADING | DOCUMENTS | OFFICES | {'press', 'release', 'accompanied', 'appendix', 'prepared'}
SPLIT = re.compile(r"(mods:witness\[\d+\])/part\[2\]")
# U.S. states and the District, by name and postal code, as places a name can never be.
STATES = {s.lower() for s in (
    'Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho Illinois '
    'Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota Mississippi Missouri '
    'Montana Nebraska Nevada Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah Vermont Virginia Washington '
    'Wisconsin Wyoming').split()} | {
    'new hampshire', 'new jersey', 'new mexico', 'new york', 'north carolina', 'north dakota', 'rhode island',
    'south carolina', 'south dakota', 'west virginia', 'district of columbia', 'puerto rico', 'dc', 'd.c.'} | {
    c.lower() for c in ('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM '
                        'NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY').split()}
STATE_WORDS = {word for state in STATES for word in state.replace('.', '').split()}
STATE_NAMES = [tuple(state.split()) for state in STATES if len(state) > 2 and '.' not in state]


def words(text):
    """A text's words; a dot leader ("Inhofe.........73,") separates words like a space."""
    return [w for w in re.split(r"[\s,;:()\[\]]+|\.{2,}", text or '') if w.strip('.-\'"')]


def plain(word):
    return re.sub(r"[^a-z0-9]", '', word.lower())


def name_words(text):
    """A name's words without titles, suffixes and initials ("Hon. J. Robert Hunter Jr." -> robert hunter)."""
    return [w for w in map(plain, words(text))
            if w and w not in TITLES and w not in COMMITTEE and w not in SUFFIXES and len(w) > 1]


def opening(text):
    found = name_words(text)
    return found[0] if found else None


def family_word(name):
    """The last word of a name, without a suffix or an initial ("Joe Manchin III" -> manchin)."""
    found = name_words(name)
    return found[-1] if found else None


def known_names(people_path):
    """Given and family names other publishers state; two letters ("us" of "U.S.") are too short to judge."""
    table = pq.read_table(people_path, columns=['source', 'name']).to_pylist()
    names = [name_words(r['name']) for r in table if r['source'] != 'mods' and r['name']]
    given = Counter(n[0] for n in names if len(n) > 1)
    family = Counter(n[-1] for n in names if len(n) > 1)
    keep = lambda counts: {word for word, n in counts.items() if len(word) > 2 and n >= 2}  # noqa: E731
    return keep(given), keep(family)


def credential(word):
    """A credential or a title, which every GPO witness line may shed from its fields."""
    bare = word.strip('.,')
    if plain(bare) in TITLES:
        return True
    return bool(re.fullmatch(r"(?:[A-Za-z]\.?){1,6}", bare)) and (bare.isupper() or '.' in bare)


def generation(path):
    rows = {}
    for row in pq.read_table(path, columns=['source', 'record_sha', 'package_id', 'appearances']).to_pylist():
        if row['source'] == 'mods':
            digest = row['record_sha'].hex() if isinstance(row['record_sha'], bytes) else row['record_sha']
            rows[digest] = (row['package_id'], {a['source_locator']: a for a in row['appearances'] or ()})
    return rows


def raw_print(raw_root, digest):
    """A body's <witness> lines; the words of the Members its <congMember> entries name; and each such Member's
    family name, as words (from the "Surname, Given" authority name, else the last word of "Given Surname")."""
    path = Path(raw_root) / digest[:2] / f'{digest}.gz'
    root = ET.fromstring(gzip.decompress(path.read_bytes()))
    lines = [''.join(el.itertext()) for el in root.iter() if el.tag.rsplit('}', 1)[-1] == 'witness']
    members, families = set(), set()
    for el in root.iter():
        if el.tag.rsplit('}', 1)[-1] != 'congMember':
            continue
        names = {name.get('type'): name.text or '' for name in el.iter() if name.tag.rsplit('}', 1)[-1] == 'name'}
        members |= {plain(w) for text in names.values() for w in words(text) if len(plain(w)) > 2}
        lnf, fnf = names.get('authority-lnf', ''), names.get('authority-fnf', '')
        family = lnf.split(',')[0] if ',' in lnf else ' '.join(fnf.split()[-1:])
        family = tuple(plain(w) for w in family.split() if plain(w) and plain(w) not in SUFFIXES)
        if family and len(family[-1]) > 2:
            families.add(family)
    return lines, members, families


def raw_lines(raw_root, digest):
    return raw_print(raw_root, digest)[0]


def tokens(line):
    """A line's words and the marks between them, in order: ("word", text) or ("mark", text). A word keeps a single
    period ("K.", "U.S.", "Hon."), never a dot leader ("Reed.........")."""
    return [('word', m.group()) if m.group()[0].isalpha() else ('mark', m.group())
            for m in re.finditer(r"[A-Za-z](?:[A-Za-z'’-]|\.(?!\.))*|\.{2,}|\d[\d,-]*|[,;:()]", line)]


def capital(text):
    return text[:1].isupper()


def name_word(kind, text):
    """Can this token be part of a printed name: an initial ("A."), or a capitalised word that is no title and no
    style word?"""
    return kind == 'word' and capital(text) and (len(plain(text)) == 1 and text != 'A' or plain(text) not in MEMBER_TITLES
                                                 and plain(text) not in LIST_WORDS)


def member_groups(line, families, *, near_title=False):
    """The Members a line names, each as the set of its name words (initials and suffixes aside), counted three ways,
    none of which splits a list by its separators. (1) Each <congMember> family name the line prints capitalised, with
    the capitalised words printed around it (with `near_title`, only when a Member title stands up to four words before
    it, or ", Hon." right after it: on a heading line other names are a witness's or a footnote's). (2) After a chamber
    title, the capitalised words up to a lower-case or style word, a number or a mark, and no further than a
    <congMember> family name among them ("Senator Inhofe Larson, Amy W." names Inhofe); after a plural title a comma
    or "and" begins the next Member. A title after "of", "State" or another capitalised word names a body or an office
    ("House of Representatives", "Wyoming State Senator", "Sales Representatives", "U.S. Senator from") and counts for
    none. (3) The name after "Hon."/"Honorable" (and a surname printed before it, "Donnelly, Hon. Joe") that "a
    Representative/Delegate ... in Congress from" follows, or "of" a State that ends the entry ("Hon. Sam Graves, of
    Missouri"; not "a Member of the Minnesota House"). Groups that share a word are one Member."""
    marks = tokens(line)
    lowered = [plain(text) if kind == 'word' else None for kind, text in marks]
    last_words = {family[-1] for family in families}

    def around(i, j):
        """The name words printed before marks[i:j] and through it: a given name comes first, a suffix after."""
        while i > 0 and name_word(*marks[i - 1]):
            i -= 1
        while j < len(marks) and lowered[j] in SUFFIXES:
            j += 1
        return {lowered[k] for k in range(i, j) if lowered[k] and len(lowered[k]) > 1 and lowered[k] not in SUFFIXES}

    groups = []
    for family in families:
        size = len(family)
        for i in range(len(lowered) - size + 1):
            if tuple(lowered[i:i + size]) != family or not capital(marks[i][1]):
                continue
            titled = (any(lowered[t] in MEMBER_TITLES for t in range(max(i - 4, 0), i) if lowered[t])
                      or i + size + 1 < len(marks) and marks[i + size][1] == ','
                      and lowered[i + size + 1] in ('hon', 'honorable'))
            if not near_title or titled:
                groups.append(around(i, i + size))
    taken = set()  # positions of words a chamber title's run read as a Member's name
    for i, word in enumerate(lowered):
        kind_before, text_before = marks[i - 1] if i else ('mark', '')
        if word not in CHAMBER or kind_before == 'word' and (
                plain(text_before) in ('of', 'the', 'state') or capital(text_before) and i - 1 not in taken):
            continue
        plural, current = word in ('senators', 'representatives'), set()
        for k in range(i + 1, len(marks)):
            kind, text = marks[k]
            low = plain(text)
            if name_word(kind, text):
                taken.add(k)
                if len(low) > 1 and low not in SUFFIXES:
                    current.add(low)
                if low in last_words and not (k + 1 < len(marks) and lowered[k + 1] in last_words):
                    break  # the print's own Member ends the name
            elif plural and (text == ',' or low == 'and'):
                groups.append(current)
                current = set()
            else:
                break
        groups.append(current)
    for i, word in enumerate(lowered):
        house = (lowered[i:i + 3] == ['in', 'congress', 'from'] and i > 0
                 and lowered[i - 1] in ('representative', 'delegate', 'commissioner'))
        state = word == 'of' and next((len(s) for s in STATE_NAMES if tuple(
            w for w in lowered[i + 1:i + 1 + len(s) + 2] if w not in ('the', 'state'))[:len(s)] == s), 0)
        if state:
            # The State ends the entry ("of Indiana", "of New Jersey, submitted ...", "of the District of Columbia..").
            rest = [k for k in range(i + 1, len(marks)) if lowered[k] not in ('the', 'state')]
            after = rest[state] if len(rest) > state else None
            state = after is None or marks[after][0] == 'mark' or lowered[after] == 'and'
        if not (house or state):
            continue
        at, current = (i - 2 if house else i) - 1, set()
        if house and at >= 0 and lowered[at + 1] != 'a':
            at += 1  # "Hon. X, Representative in Congress from" (no "a")
        while at >= 0 and (name_word(*marks[at]) or marks[at][1] == ','):
            if lowered[at] and len(lowered[at]) > 1 and lowered[at] not in SUFFIXES:
                current.add(lowered[at])
            at -= 1
        if at >= 0 and lowered[at] in ('hon', 'honorable'):
            if at >= 2 and marks[at - 1][1] == ',':
                current |= around(at - 2, at - 1)  # the surname printed first
            groups.append(current)
    merged = []
    for group in filter(None, groups):
        for other in [m for m in merged if m & group]:
            merged.remove(other)
            group = group | other
        merged.append(group)
    return merged


def names_alone(line):
    """Does the line print names only: capitalised words, a Member's style and page numbers, no office, document or
    heading word?"""
    found = [(text, plain(text)) for kind, text in tokens(line) if kind == 'word']
    # "U.S. Senator from North Carolina" is a Member's own entry, which a list of askers never prints.
    own = re.search(r"\b(?:U\.\s?S\.|United States)\s+(?:Senator|Representative)\b", line, re.I)
    return bool(found) and not own and all((capital(text) or low in LIST_WORDS) and low not in NOT_PERSON
                                           for text, low in found)


def asking_lines(lines, families):
    """Lines that ask, read without the rule: {position: 'heading' | 'list'} (see the module docstring)."""
    found = {}
    for n, line in enumerate(lines, start=1):
        said = {plain(w) for w in words(line)}
        if said & ASKING:
            found[n] = 'heading'
        elif names_alone(line):
            # With no asking line before it, a list must show its Members by title: a witness's surname can be a
            # Member's ("Mrs. Sherry Keller, Conyers, GA").
            groups = member_groups(line, families, near_title=True)
            paged = bool(plain((words(line) or [''])[0]) in CHAMBER | {'chairman', 'chairwoman', 'ranking'}
                         and re.search(r"\.{2,}\s*\d", line))
            plural = re.match(r"\W*(?:Senators|Representatives)\s", line)
            if found.get(n - 1) or groups and (plural or len(groups) > 1 or paged):
                found[n] = 'list'
    return found


def line_members(line, families, kind):
    """The words of the Members a line names (member_groups), read near their titles on a heading line."""
    return set().union(*member_groups(line, families, near_title=kind == 'heading') or [set()])


def in_order(name, line):
    """Are the name's words in the line, in the name's order and next to each other?"""
    sequence, text = [plain(w) for w in words(name) if plain(w)], [plain(w) for w in words(line) if plain(w)]
    return any(text[i:i + len(sequence)] == sequence for i in range(len(text) - len(sequence) + 1))


def line_segments(line):
    return [part.strip() for part in re.split(r'[,;:]', line) if part.strip()]


def bag(occurrence):
    """The words of an occurrence's four fields, without credentials and titles."""
    return Counter(plain(w) for f in FIELDS for w in words((occurrence or {}).get(f)) if not credential(w))


def judge(before, after, raw_root, given, family):
    def person(text):
        return opening(text) in given

    def member_name(name, members):
        """A name whose words of three letters or more are all words of the print's own <congMember> names ("Boxer",
        "Al Franken"; the members' words are kept from three letters, as two-letter words judge nothing)."""
        found = [w for w in name_words(name) if len(w) > 2]
        return bool(found) and set(found) <= members

    def names_document_only(line):
        found = {plain(w) for w in words(line)}
        return bool(DOCUMENTS & found) and not CIVIL & found and not any(person(s) for s in line_segments(line))

    def reads_as_document(line):
        """A line that names no person and names a document, quotes a title or prints a date."""
        found = {plain(w) for w in words(line)}
        return (bool(DOCUMENTS & found or QUOTED.search(line) or DATED.search(line)) and not CIVIL & found
                and not any(person(s) for s in line_segments(line)))

    def not_person(name, line, members):
        parts = line_segments(line)
        key = name.strip().lower()
        if key in STATES:
            return True
        for i, part in enumerate(parts[:-1]):
            if part.lower() == key and parts[i + 1].lower() in STATES:
                return True
        # A name made of the print's own <congMember> names is a Member's ("Al Franken"); a line that names a
        # document and no person names no one ("Summary of Selected Counter-Terrorism Initiatives, by the National
        # Academies").
        return (not person(name) and not member_name(name, members)
                and (any(person(part) for part in parts[1:]) or names_document_only(line)))

    def reorder_supported(name):
        return person(name) and family_word(name) in family

    out = {key: [] for key in (*FLAGS, 'unconfirmed', 'residual', 'split', 'restored', 'asker', 'not_read',
                               'bodies_only_before', 'bodies_only_after')}
    counts = Counter()
    out['bodies_only_before'] = sorted(before.keys() - after.keys())
    out['bodies_only_after'] = sorted(after.keys() - before.keys())
    for digest in sorted(before.keys() & after.keys()):
        package, old = before[digest]
        new = after[digest][1]
        try:
            lines, members, member_families = raw_print(raw_root, digest)
        except (OSError, ET.ParseError, EOFError) as error:
            # Named, and still compared: with no raw line, any changed name is reported as not in its line.
            out['not_read'].append(dict(body=digest, package=package, error=type(error).__name__))
            lines, members, member_families = [], set(), set()
        counts['bodies'] += 1
        asking = asking_lines(lines, member_families)

        def position(locator):
            index = re.match(r"mods:witness\[(\d+)\]", locator)
            return int(index.group(1)) if index else 0

        recorded = {position(k) for k, v in new.items() if v.get('witness_type') == 'record_material'}
        members_of = {n: line_members(lines[n - 1], member_families, asking.get(n))
                      for n in range(1, len(lines) + 1) if n in asking or n in recorded}

        def line_of(locator):
            n = position(locator)
            return lines[n - 1] if 0 < n <= len(lines) else ''

        def a_member(name, locator):
            return family_word(name) in members_of.get(position(locator), set())

        def asker(b, locator):
            """A row the before side lacks that is a Member the asking line prints, in order."""
            name, line = b.get('name'), line_of(locator)
            return (b.get('witness_type') == 'record_material' and position(locator) in asking and bool(name)
                    and set(map(plain, words(name))) <= set(map(plain, words(line))) and in_order(name, line)
                    and a_member(name, locator))

        # Witness rows on an asking line, documents left a witness, and the order rows are shown in.
        by_line = {}
        for locator, b in sorted(new.items()):
            by_line.setdefault(position(locator), []).append(b)
            line = line_of(locator)
            item = dict(package=package, body=digest, locator=locator, line=line,
                        after={f: b.get(f) for f in KEYED})
            if position(locator) in asking and b.get('witness_type') is None:
                said = [w for w in name_words(b.get('name')) if w not in ('by', 'to', 'for', 'from', 'of', 'and')]
                someone = (len(said) > 1 and set(said) <= {plain(w) for w in words(line)}
                           and not set(said) & NOT_PERSON and not a_member(b.get('name'), locator))
                if not someone:
                    out['question_asker_as_witness'].append(item)
            if b.get('witness_type') is None and not b.get('name') and reads_as_document(line):
                out['record_as_witness'].append(item)
        for n, rows in sorted(by_line.items()):
            line = lines[n - 1].lower() if 0 < n <= len(lines) else ''
            placed = []
            for r in sorted(rows, key=lambda r: r.get('display_order') or 0):
                word = family_word(r.get('name'))
                at = re.search(rf"\b{re.escape(word)}\b", line) if word else None
                if at:
                    placed.append((at.start(), r))
            for (at, r), (prior, _) in zip(placed[1:], placed):
                if at < prior:
                    out['order_unsupported'].append(dict(package=package, body=digest, locator=r['source_locator'],
                                                         line=lines[n - 1], after={f: r.get(f) for f in KEYED}))
        # Every Member an asking or record line names has a row naming them on that line.
        for n in sorted(members_of):
            line = lines[n - 1]
            named = {plain(w) for r in by_line.get(n, []) for w in words(r.get('name'))}
            if missing := members_of[n] - named:
                rows = by_line.get(n, [])
                out['member_unnamed'].append(dict(package=package, body=digest, locator=f'mods:witness[{n}]', line=line,
                                                  words=sorted(missing),
                                                  after={f: [r.get(f) for r in rows] for f in ('name', 'witness_type')}))

        def type_supported(a, b, line, locator):
            if b.get('witness_type') == 'record_material':
                return position(locator) in asking and (not b.get('name') or a_member(b['name'], locator)
                                                        or asking[position(locator)] == 'list')
            return (a.get('witness_type') is None and b.get('witness_type') == 'statement_for_record'
                    and not b.get('name') and b.get('organization') and names_document_only(line))

        def new_name_checks(item, name, line):
            if not set(map(plain, words(name))) <= set(map(plain, words(line))):
                out['name_not_in_line'].append(item)
            if not in_order(name, line) and not reorder_supported(name):
                out['reorder_unsupported'].append(item)

        moved = {}  # a split parent's locator -> the words its second person took
        for locator in sorted(new.keys() - old.keys()):
            item = dict(package=package, body=digest, locator=locator)
            b, line = new[locator], line_of(locator)
            item.update(line=line, after={f: b.get(f) for f in KEYED})
            if asker(b, locator):
                out['asker'].append(item)
                continue
            if b.get('name'):
                new_name_checks(item, b['name'], line)
            parent = SPLIT.fullmatch(locator)
            if not parent:
                # A line the old reading dropped, now kept at its own locator: its raw line must exist and hold the
                # new name in order, the name must be a person's (not heading text that happens to be in the line),
                # and its type must be supported like any other. Any further part of a line (/part[3] on) is added.
                if ('/part[' not in locator and line and not any(position(k) == position(locator) for k in old)
                        and (not b.get('name') or (set(map(plain, words(b['name']))) <= set(map(plain, words(line)))
                                                   and (in_order(b['name'], line) or reorder_supported(b['name']))
                                                   and (person(b['name']) or member_name(b['name'], members))))
                        and type_supported({}, b, line, locator)):
                    out['restored'].append(item)
                else:
                    out['added'].append(item)
                continue
            parent = parent.group(1)
            took = bag(b)
            if (parent in old and parent in new and old[parent].get('name') == new[parent].get('name')
                    and b.get('name') and in_order(b['name'], line) and person(b['name'])
                    and name_words(b['name'])[-1] in family and took and took == bag(old[parent]) - bag(new[parent])):
                moved[parent] = took
                out['split'].append(item)
            else:
                out['split_unsupported'].append(item)
        for locator in sorted(old.keys() | new.keys()):
            item = dict(package=package, body=digest, locator=locator)
            if locator not in new:
                out['removed'].append(item)
                continue
            if locator not in old:
                continue
            counts['occurrences'] += 1
            line = line_of(locator)
            a, b = old[locator], new[locator]
            item.update(line=line, before={f: a.get(f) for f in KEYED}, after={f: b.get(f) for f in KEYED})
            if a.get('witness_type') != b.get('witness_type'):
                counts['typed'] += 1
                if not type_supported(a, b, line, locator):
                    out['type_unsupported'].append(item)
            if all(a.get(f) == b.get(f) for f in FIELDS):
                segments = [s for s in line.split(',')[1:] if s.strip()]
                if a.get('name') and not person(a['name']) and any(person(s) for s in segments):
                    out['residual'].append(item)
                continue
            counts['changed'] += 1
            old_name, new_name = a.get('name'), b.get('name')
            reordered = bool(new_name) and not in_order(new_name, line)
            counts['no_name' if not new_name else 'reordered' if reordered else 'name_read'] += 1
            if old_name and person(old_name) and not set(name_words(old_name)) <= set(name_words(new_name)):
                out['person_moved'].append(item)
            if new_name and not set(map(plain, words(new_name))) <= set(map(plain, words(line))):
                out['name_not_in_line'].append(item)
            if reordered and not reorder_supported(new_name):
                out['reorder_unsupported'].append(item)
            if new_name and not_person(new_name, line, members):
                out['name_not_person'].append(item)
            if new_name and not person(new_name):
                out['unconfirmed'].append(item)
            old_words, new_words = bag(a), bag(b) + moved.get(locator, Counter())
            # On an asking line the heading's words are no one's: a row that was named for the heading may shed them.
            shed = HEADING | MEMBER_TITLES | {'the', 'to', 'by', 'from', 'of', 'for', 'and', 'arising', 'following'} \
                if position(locator) in asking else set()
            lost = Counter({w: k for w, k in (old_words - new_words).items() if w not in shed})
            if lost:
                out['words_lost'].append(dict(item, words=sorted(lost.elements())))
            # A gained word must come from the raw line; a re-read may restore line text the old one dropped.
            gained = Counter(w for w in (new_words - old_words).elements() if w not in {plain(x) for x in words(line)})
            if gained:
                out['words_gained'].append(dict(item, words=sorted(gained.elements())))
            if not new_name and any(person(s) for s in re.split(r'[,;:]', line)[1:]):
                out['person_left_in_organization'].append(item)
    return dict(counts), out


def plant(kind, before, after, given, family, raw_root):
    """Write one wrong value the rule could produce on the after side."""
    def lines(digest, locator):
        index = re.match(r"mods:witness\[(\d+)\]", locator)
        try:
            found = raw_lines(raw_root, digest)
        except (OSError, ET.ParseError, EOFError):
            return ''
        return found[int(index.group(1)) - 1] if index and int(index.group(1)) <= len(found) else ''

    def base(locator):
        return re.match(r"mods:witness\[\d+\]", locator).group()

    for digest in sorted(before.keys() & after.keys()):
        old, new = before[digest][1], after[digest][1]
        if kind == 'asker-dropped':
            # One of several Members a line names as askers dropped: the last further part of a record line.
            for locator in sorted(new, key=lambda k: (len(k), k), reverse=True):
                base_match = re.fullmatch(r"(mods:witness\[\d+\])/part\[\d+\]", locator)
                if (base_match and new[locator].get('name') and new[locator].get('witness_type') == 'record_material'
                        and (new.get(base_match.group(1)) or {}).get('witness_type') == 'record_material'):
                    gone = new.pop(locator)
                    return dict(kind=kind, body=digest, locator=base_match.group(1), name=gone['name'],
                                planted=f'{locator} dropped')
            continue
        if kind in ('title-as-witness', 'statement-as-witness'):
            # A nameless record row typed a witness: a document title (record material holding its organization text)
            # or an organization's own statement.
            want = 'record_material' if kind == 'title-as-witness' else 'statement_for_record'
            for locator, b in sorted(new.items()):
                if b.get('witness_type') == want and not b.get('name') and b.get('organization'):
                    new[locator] = dict(b, witness_type=None)
                    return dict(kind=kind, body=digest, locator=locator, name=b['organization'], planted=None)
            continue
        if kind in ('heading-as-name', 'name-emptied'):
            # A line the before side read no row for, now kept as a named record (a restored question heading): its
            # name replaced by the heading's own words, or emptied.
            for locator, b in sorted(new.items()):
                line = lines(digest, locator)
                if ('/part[' in locator or not b.get('name') or b.get('witness_type') != 'record_material' or ':' not in line
                        or any(k.split('/')[0] == locator for k in old)):
                    continue
                new[locator] = dict(b, name=line.rpartition(':')[0].strip() if kind == 'heading-as-name' else None)
                return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=new[locator]['name'])
            continue
        if kind == 'committee-segment':
            # A Member read after a committee title ("...from: Chairman Michael B. Enzi") replaced by the segment
            # before that title.
            for locator, a in sorted(old.items()):
                b = new.get(locator)
                parts = line_segments(lines(digest, locator)) if b and b.get('name') else []
                at = next((k for k, part in enumerate(parts) if k and re.match(r"(?:Chairman|Chairwoman|Ranking Member)\s", part)
                           and set(name_words(b['name'])) <= {plain(w) for w in words(part)}), None)
                if at and parts[at - 1] != a.get('name'):
                    new[locator] = dict(b, name=parts[at - 1])
                    return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=parts[at - 1])
            continue
        if kind == 'asker-as-witness':
            # A Member listed under a question heading (not the heading itself) left as a witness.
            for locator, b in sorted(new.items()):
                prior = new.get(f'mods:witness[{int(re.match(r"mods:witness\[(\d+)\]", locator).group(1)) - 1}]')
                if (b.get('witness_type') == 'record_material' and b.get('name') and prior
                        and prior.get('witness_type') == 'record_material' and 'question' not in lines(digest, locator).lower()):
                    new[locator] = dict(b, witness_type=None)
                    return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=None)
            continue
        if kind in ('reversed-asker', 'given-added'):
            # A Member the after side adds as an asker (a row the before side lacks), written surname first, or, when
            # named by surname alone, given a first name the line does not print.
            for locator, b in sorted(new.items()):
                said = name_words(b.get('name'))
                if b.get('witness_type') != 'record_material' or locator in old or not said:
                    continue
                if kind == 'reversed-asker' and len(said) > 1 and len((b['name']).split()) == 2:
                    given_part, surname = b['name'].split()
                    new[locator] = dict(b, name=f'{surname} {given_part}')
                elif kind == 'given-added' and len(b['name'].split()) == 1:
                    first = next(w for w in ('Bill', 'Mary', 'John') if plain(w) not in {plain(x) for x in words(lines(digest, locator))})
                    new[locator] = dict(b, name=f"{first} {b['name']}")
                else:
                    continue
                return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=new[locator]['name'])
            continue
        if kind == 'askers-swapped':
            # Two askers of one line exchange their names.
            for locator, b in sorted(new.items()):
                second = f'{base(locator)}/part[2]'
                c = new.get(second)
                if (locator == base(locator) and c and b.get('witness_type') == c.get('witness_type') == 'record_material'
                        and b.get('name') and c.get('name') and family_word(b['name']) != family_word(c['name'])):
                    new[locator], new[second] = dict(b, name=c['name']), dict(c, name=b['name'])
                    return dict(kind=kind, body=digest, locator=second, name=c['name'], planted=b['name'])
            continue
        if kind == 'witness-as-asker':
            # An unchanged witness on a line that asks nothing typed record material ("Dodaro, Hon. Gene L., ...").
            for locator, b in sorted(new.items()):
                line = lines(digest, locator)
                unchanged = locator in old and all(old[locator].get(f) == b.get(f) for f in (*FIELDS, 'witness_type'))
                if (unchanged and b.get('witness_type') is None and b.get('name') and 'hon' in
                        {plain(w) for w in words(line)} and not {plain(w) for w in words(line)} & ASKING):
                    new[locator] = dict(b, witness_type='record_material')
                    return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted='record_material')
            continue
        if kind == 'heading-reverted':
            # A line whose askers the after side shows put back as one witness named for the line up to its first asker.
            for locator, b in sorted(new.items()):
                line = lines(digest, locator)
                parts = sorted(k for k in new if base(k) == locator)
                if (locator != base(locator) or len(parts) < 2 or b.get('witness_type') != 'record_material'
                        or not b.get('name') or not {plain(w) for w in words(line)} & ASKING):
                    continue
                for k in parts:
                    new.pop(k)
                at = line.find(b['name'].split()[-1])
                new[locator] = dict(b, name=re.split(r"\.{2,}", line[:at + len(b['name'].split()[-1])])[0].strip(),
                                    witness_type=None)
                return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=new[locator]['name'])
            continue
        if kind == 'split-untrimmed':
            for locator in sorted(new.keys() - old.keys()):
                parent = SPLIT.fullmatch(locator)
                if parent and parent.group(1) in old and new.get(locator, {}).get('witness_type') != 'record_material':
                    wrong = dict(old[parent.group(1)])
                    new[parent.group(1)] = wrong
                    return dict(kind=kind, body=digest, locator=locator, name=new[locator]['name'],
                                planted=wrong.get('position'))
            continue
        for locator, a in sorted(old.items()):
            b = new.get(locator)
            if kind == 'typed-organization':
                if (b == a and not b.get('name') and b.get('organization') and not b.get('witness_type')
                        and not DOCUMENTS & {plain(w) for w in words(lines(digest, locator))}):
                    new[locator] = dict(b, witness_type='statement_for_record')
                    return dict(kind=kind, body=digest, locator=locator, name=b['organization'],
                                planted='statement_for_record')
                continue
            parts = name_words(b.get('name') if b else None)
            line_parts = line_segments(lines(digest, locator)) if kind == 'previous-segment' and b and b != a and b.get('name') else []
            at = next((k for k, part in enumerate(line_parts) if k and plain(part) and b['name'] in part), None)
            if kind == 'person-moved' and b == a and parts and parts[0] in given:
                wrong = dict(b, name=None, organization=', '.join(filter(None, (b['name'], b.get('organization')))))
            elif kind == 'previous-segment' and at and opening(line_parts[at - 1]) not in given and parts and parts[0] in given:
                wrong = dict(b, name=line_parts[at - 1])
            elif (kind == 'reversed-name' and b and b != a and len(parts) > 1 and parts[0] in given
                  and parts[-1] in family and parts[-1] not in given):
                given_part, surname = b['name'].rsplit(' ', 1)
                wrong = dict(b, name=f'{surname} {given_part}')
            else:
                continue
            new[locator] = wrong
            return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=wrong['name'])
    raise SystemExit(f'no occurrence to plant {kind} on')


def accept_key(body, locator, flag, after, line_sha256):
    """An accept is bound to the occurrence, the flag, every new field the reviewer read (``KEYED``) and the raw
    line they read (its sha256)."""
    return (body, locator, flag, json.dumps([(after or {}).get(f) for f in KEYED], default=str), line_sha256)


def line_digest(line):
    return hashlib.sha256((line or '').strip().encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--after', required=True, type=Path)
    parser.add_argument('--raw-root', required=True, type=Path)
    parser.add_argument('--people', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--accept', type=Path)
    parser.add_argument('--plant', choices=sorted(PLANTS))
    args = parser.parse_args(argv)
    given, family = known_names(args.people)
    before, after = generation(args.before), generation(args.after)
    planted = plant(args.plant, before, after, given, family, args.raw_root) if args.plant else None
    counts, out = judge(before, after, args.raw_root, given, family)
    accepts = json.loads(args.accept.read_text()) if args.accept else []
    # An accept counts only once a reviewer has signed it (reviewed_by) with a reason, on the raw line they read.
    signed = [a for a in accepts if a.get('reviewed_by') and a.get('reason') and a.get('line_sha256')]
    out['unsigned_accept'] = [a for a in accepts if a not in signed]
    reviewed = {accept_key(a['body'], a['locator'], a['flag'], a['after'], a['line_sha256']): a for a in signed}
    out['accepted'], seen = [], set()
    for flag in FLAGS:
        kept = []
        for item in out[flag]:
            item['line_sha256'] = line_digest(item.get('line'))
            key = accept_key(item['body'], item['locator'], flag, item.get('after') or {}, item['line_sha256'])
            if key in reviewed and not (planted and (item['body'], item['locator']) == (planted['body'], planted['locator'])):
                seen.add(key)
                out['accepted'].append(dict(item, flag=flag, reason=reviewed[key]['reason'],
                                            reviewed_by=reviewed[key]['reviewed_by']))
            else:
                kept.append(item)
        out[flag] = kept
    out['stale_accept'] = [a for key, a in reviewed.items() if key not in seen]
    failed = {flag: len(out[flag]) for flag in (*FLAGS, 'stale_accept') if out[flag]}
    if out['bodies_only_before'] or out['bodies_only_after']:
        failed['unpaired_bodies'] = len(out['bodies_only_before']) + len(out['bodies_only_after'])
    if planted:
        planted['flagged'] = any(i['body'] == planted['body'] and i['locator'] == planted['locator']
                                 for i in out[PLANTS[planted['kind']]])
    result = dict(status='failed' if failed else 'passed', failed=failed, counts=counts, known_given_names=len(given),
                  known_family_names=len(family), sizes={k: len(v) for k, v in out.items()}, planted=planted, **out)
    args.output.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps(dict(status=result['status'], failed=failed, counts=counts, sizes=result['sizes'], planted=planted)))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())

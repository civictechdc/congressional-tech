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

Both directions, per occurrence key (body, locator); every flag fails the check:

- an occurrence or a body on one side only (``added``, ``removed``, ``unpaired_bodies``), except a line the
  before side read no occurrence for at all, now kept at its own locator with a supported type and, if named, a
  person's name its raw line holds: one opening with a known given name or made of the print's ``<congMember>``
  words (listed under ``restored``). Every further part of a line (``/part[3]`` on) is ``added``;
- ``person_moved``: a changed name that opens with a known given name and whose words the new name lacks;
- ``name_not_in_line``: a new name with a word its raw line lacks;
- ``words_lost``: a changed occurrence that loses a word across name, position, organization and
  on_behalf_of (credentials such as "M.D." and titles such as "Hon." may go, as for every witness line);
- ``words_gained``: a changed occurrence that gains a word its raw line lacks;
- ``person_left_in_organization``: a changed occurrence left without a name whose raw line still has a
  later segment opening with a known given name;
- ``reorder_unsupported``: a new name whose words are not in the raw line in that order (a surname joined to
  its given name) and that does not open with a known given name and end with a known family name;
- ``name_not_person``: a new name that is a place (a U.S. state, or a segment the raw line follows with a
  state), or that opens with no known given name, is not made of the print's ``<congMember>`` words, and either
  a later segment of its raw line opens with a known given name (a committee title such as "Chairman" before it
  aside) or the line names a document and no person;
- ``split_unsupported``: an added ``<locator>/part[2]`` (a joined line read as two people, ct-zs48) unless its
  parent occurrence is on both sides with the same name, the words the parent loses are exactly the words the
  new occurrence holds, and the new name is in the raw line in order, opening with a known given name and ending
  with a known family name. A passing split is listed under ``split`` and its parent's moved words are not
  counted as lost;
- ``type_unsupported``: a changed ``witness_type`` unless it goes from none to ``statement_for_record`` on an
  occurrence with no name, an organization, and a raw line that names a document anywhere (any of
  ``DOCUMENTS``) and no person (no segment opening with a known given name, no civil title) (ct-3aap); or it
  is ``record_material`` on a line a question-for-the-record list covers (``question_context``);
- ``question_asker_as_witness``: any after occurrence, changed or not, left a witness (no type) on a line a
  question-for-the-record list covers: a heading naming who asked, or a Member listed under it;
- ``member_unnamed``: a line a question list covers, or one holding a ``record_material`` occurrence, that names
  a Member no occurrence of that line names, by a count the rule does not make: the family names of the print's
  own ``<congMember>`` entries found in the line, and the last capitalised word after each Member title or of
  each item of a "Senators A, B and C" list (``titled_members``). Reported at the line's locator with the
  family words left unnamed;
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
either reading. It does not judge honorific, bioguide_id or display_order changes, nor a split whose second person
has a given name other publishers do not state twice (that split fails, for a person to accept). Its question
reading shares the rule's idea of a list (a heading, then Member-only lines), though not its patterns; a Member
named by title alone in a list ("Hon. Sam Graves, of Missouri") counts as an asker on the title, so it cannot
tell an asker from a Member who testified in a list that follows a question heading without a break. A titled,
paged line ("Senator Graham.......23,") is read in the rule's own shape and counts only on known names.
``member_unnamed`` reads Member titles as the rule does; its ``<congMember>`` half is the independent one, and
a Member printed without a title who is not a ``<congMember>`` of the print is not counted. It does not read
lines with no record occurrence outside a question list, so an asker run into a witness's entry ("Commissioner
Responses to additional questions from Senator Boxer") is not counted; a family name that is also a common word
("Long Island") counts on a record line. A named row typed a witness on a title line passes unless the name fails
``name_not_person``. ``record_as_witness`` misses a title that prints no document word, quotation or date ("Our
Projects, DOE, Loan Programs Office", 1 of the 16 reviewed titles).

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
(``name_not_person``).
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
         'person_left_in_organization', 'reorder_unsupported', 'name_not_person', 'split_unsupported',
         'type_unsupported', 'question_asker_as_witness', 'member_unnamed', 'record_as_witness')
PLANTS = {'person-moved': 'person_moved', 'reversed-name': 'reorder_unsupported', 'previous-segment': 'name_not_person',
          'split-untrimmed': 'split_unsupported', 'typed-organization': 'type_unsupported',
          'asker-as-witness': 'question_asker_as_witness', 'asker-dropped': 'member_unnamed',
          'title-as-witness': 'record_as_witness', 'statement-as-witness': 'record_as_witness', 'heading-as-name': 'added',
          'name-emptied': 'member_unnamed', 'committee-segment': 'name_not_person'}
# A Member title before a name, as a contents line prints it ("Hon. Jon Tester", "SENATOR X", "Senators Boxer and
# Carper", "Ranking Member Bernard Sanders"); a plural title opens a list of surnames.
MEMBER_MENTION = re.compile(r"(?<![\w.])(hon\.|honorable|senators?|representatives?|delegate|chairman|chairwoman"
                            r"|ranking member)\s+", re.I)
# Words that end a Member's name in a contents line, besides punctuation, page numbers and lowercase words.
NAME_STOP = {'questions', 'question', 'responses', 'response', 'answers', 'submitted', 'from', 'to', 'by', 'of', 'and'}
# What a document's title prints and an organization's name does not: a quotation, or a date.
QUOTED = re.compile(r"\"|''|``")
DATED = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?:\d{1,2},\s*)?\d{4}\b")
# Words that name a document submitted for the record, read anywhere in a line.
DOCUMENTS = set('statement statements letter letters memorandum memo article articles paper papers report reports '
                'attachment attachments testimony comments submission summary excerpt study analysis editorial '
                'resolution petition exhibit packet'.split())
CIVIL = {'hon', 'honorable', 'mr', 'mrs', 'ms', 'dr'}
# The words of a Member's style in a contents list, which are not names.
STYLE = set('hon honorable the of and a in from state senator senators representative representatives delegate resident '
            'commissioner congress chairman chairwoman ranking member district columbia jr sr ii iii iv'.split())
MEMBER_TITLES = {'hon', 'honorable', 'senator', 'senators', 'representative', 'chairman', 'chairwoman'}
# Words of an office, which a witness's entry has and a Member's style in a question list does not.
OFFICES = set('director president secretary administrator chief officer counsel manager deputy assistant executive '
              'professor commissioner governor mayor attorney judge inspector general association department office '
              'university institute agency bureau council board foundation company inc commission former'.split())
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
        family = tuple(plain(w) for w in family.split() if plain(w))
        if family and len(family[-1]) > 2:
            families.add(family)
    return lines, members, families


def raw_lines(raw_root, digest):
    return raw_print(raw_root, digest)[0]


def titled_members(line):
    """The family word of each Member a line names after a Member title, read without the rule: the last capitalised
    word after the title, before punctuation, a dot leader, a page number, a lowercase or stop word or the next title;
    after a plural title ("Senators Boxer and Carper"), the last word of each item of the list."""
    found = set()
    mentions = list(MEMBER_MENTION.finditer(line))
    for k, mention in enumerate(mentions):
        rest = line[mention.end():mentions[k + 1].start() if k + 1 < len(mentions) else len(line)]
        rest = re.split(r"[;:()]|\.{2,}|\d", rest, maxsplit=1)[0]
        plural = mention.group(1).lower() in ('senators', 'representatives')
        items = re.split(r",\s*(?:and\s+)?|\s+and\s+", rest) if plural else rest.split(',')[:1]
        for item in items:
            run = []
            for word in item.split():
                if not word[0].isupper() or plain(word) in NAME_STOP:
                    break
                run.append(plain(word))
            run = [w for w in run if len(w) > 1 and w not in SUFFIXES]
            if run:
                found.add(run[-1])
    return found


def question_context(lines, known):
    """Lines a question-for-the-record list covers, read without the rule: {position: 'heading' | 'asker'}.

    A heading is a line whose text before its last colon says "question(s)" with "from", "by" or "of" (who asked;
    "Submitted questions: Taylor, Alexis" names who answered), with no page-number run before it (a run means an
    earlier entry runs into it), and whose text after the colon (page numbers aside) is empty or only Members'
    names; each following line that holds only Members' names is an asker, until one does not. A Member's name
    here is what is left once places, page numbers and the words of a Member's style ("a Representative in
    Congress from") go: words other publishers or the print's own <congMember> entries use as names, or any words
    in a text that marks a Member by title ("Hon.", "Senator") with at most three such words per title, and no
    word of an office or a document in either case. A heading that names a document ("Report, ... Responses to
    additional questions from: ...") is an earlier entry run into it, and covers nothing.

    A line that is only a titled Member's name and page numbers ("Senator Graham..........23,") is the contents
    entry of someone who asked ('paged'), with no heading needed (GPO prints the heading in the witness's entry).
    That reading is the rule's own shape, so it counts only when every name word is known from other publishers
    or the print's <congMember> entries; any other such line fails for a person to read."""
    def askers(text, marked_suffices=True):
        titles = [w for w in map(plain, words(text)) if w in MEMBER_TITLES]
        found = [w for w in map(plain, words(re.sub(r"\.{2,}[\d,\s-]*", ' ', text))) if w and not w.isdigit()]
        found = [w for w in found if w not in STYLE and w not in STATE_WORDS and len(w) > 1]
        # A title marks a Member's name, of at most three words, not a description after it.
        marked = marked_suffices and titles and len(found) <= 3 * len(titles)
        return bool(found) and not set(found) & (OFFICES | DOCUMENTS) and (bool(marked) or set(found) <= known)

    covered = {}
    for n, line in enumerate(lines, start=1):
        opening, _, tail = line.rpartition(':')
        asked = {plain(w) for w in words(opening)}
        if (asked & {'question', 'questions'} and asked & {'from', 'by', 'of'} and not asked & DOCUMENTS
                and not re.search(r"\.{3,}.*\bquestions?\b", opening, re.I)):
            tail = re.sub(r"\.{2,}[\d,\s-]*", ' ', tail).strip()
            if not tail or askers(tail):
                covered[n] = 'heading'
        elif covered.get(n - 1) in ('heading', 'asker') and askers(line):
            covered[n] = 'asker'
        elif (re.fullmatch(r"\W*(?:Senators?|Chairman|Ranking Member)\s[^.]+(?:\.{3,}\s*\d[\d,\s-]*)+", line.strip())
              and askers(line, marked_suffices=False)):
            covered[n] = 'paged'
    return covered


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

    out = {key: [] for key in (*FLAGS, 'unconfirmed', 'residual', 'split', 'restored', 'not_read',
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
        covered = question_context(lines, given | family | members)

        def position(locator):
            index = re.match(r"mods:witness\[(\d+)\]", locator)
            return int(index.group(1)) if index else 0

        def line_of(locator):
            n = position(locator)
            return lines[n - 1] if 0 < n <= len(lines) else ''

        # Both directions of the question-list reading: a listed asker or heading left as a witness, and a line
        # typed record material by the question rule outside any list this check reads. A row typed a witness that
        # names no one on a line that reads as a document (record_as_witness) is a title or a statement, not an
        # organization that testified ("American Legion" stays a witness).
        by_line = {}
        for locator, b in sorted(new.items()):
            by_line.setdefault(position(locator), []).append(b)
            item = dict(package=package, body=digest, locator=locator, line=line_of(locator),
                        after={f: b.get(f) for f in KEYED})
            if covered.get(position(locator)) and b.get('witness_type') is None:
                out['question_asker_as_witness'].append(item)
            if b.get('witness_type') is None and not b.get('name') and reads_as_document(line_of(locator)):
                out['record_as_witness'].append(item)
        # Every Member a question or record line names has a row naming them on that line, counted without the rule:
        # by the line's own Member titles and by the print's <congMember> family names (member_unnamed).
        for n in sorted(by_line.keys() | covered.keys()):
            rows, line = by_line.get(n, []), lines[n - 1] if 0 < n <= len(lines) else ''
            if not line or not (covered.get(n) or any(r.get('witness_type') == 'record_material' for r in rows)):
                continue
            named = {plain(w) for r in rows for w in words(r.get('name'))}
            text = [plain(w) for w in words(line) if plain(w)]
            required = titled_members(line) | {f[-1] for f in member_families
                                               if any(text[i:i + len(f)] == list(f) for i in range(len(text)))}
            if required - named:
                out['member_unnamed'].append(dict(package=package, body=digest, locator=f'mods:witness[{n}]', line=line,
                                                  words=sorted(required - named),
                                                  after={f: [r.get(f) for r in rows] for f in ('name', 'witness_type')}))

        def type_supported(a, b, line, locator):
            if b.get('witness_type') == 'record_material':
                return bool(covered.get(position(locator)))
            return (a.get('witness_type') is None and b.get('witness_type') == 'statement_for_record'
                    and not b.get('name') and b.get('organization') and names_document_only(line))

        moved = {}  # a split parent's locator -> the words its second person took
        for locator in sorted(new.keys() - old.keys()):
            item = dict(package=package, body=digest, locator=locator)
            parent = SPLIT.fullmatch(locator)
            if not parent:
                # A line the old reading dropped, now kept at its own locator: its raw line must exist and hold the
                # new name, the name must be a person's (not heading text that happens to be in the line), and its
                # type must be supported like any other. Any further part of a line (/part[3] on) is added.
                b, line = new[locator], line_of(locator)
                item.update(line=line, after={f: b.get(f) for f in KEYED})
                if ('/part[' not in locator and line and not any(position(k) == position(locator) for k in old)
                        and (not b.get('name') or (set(map(plain, words(b['name']))) <= set(map(plain, words(line)))
                                                   and (person(b['name']) or member_name(b['name'], members))))
                        and type_supported({}, b, line, locator)):
                    out['restored'].append(item)
                else:
                    out['added'].append(item)
                continue
            parent, b, line = parent.group(1), new[locator], line_of(locator)
            item.update(line=line, after={f: b.get(f) for f in KEYED})
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
            if reordered and not (person(new_name) and name_words(new_name)[-1] in family):
                out['reorder_unsupported'].append(item)
            if new_name and not_person(new_name, line, members):
                out['name_not_person'].append(item)
            if new_name and not person(new_name):
                out['unconfirmed'].append(item)
            old_words, new_words = bag(a), bag(b) + moved.get(locator, Counter())
            if old_words - new_words:
                out['words_lost'].append(dict(item, words=sorted((old_words - new_words).elements())))
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

    for digest in sorted(before.keys() & after.keys()):
        old, new = before[digest][1], after[digest][1]
        if kind == 'asker-dropped':
            # One of several Members a line names as askers dropped: the last further part of a record line.
            for locator in sorted(new, key=lambda k: (len(k), k), reverse=True):
                base = re.fullmatch(r"(mods:witness\[\d+\])/part\[\d+\]", locator)
                if (base and new[locator].get('name') and new[locator].get('witness_type') == 'record_material'
                        and (new.get(base.group(1)) or {}).get('witness_type') == 'record_material'):
                    gone = new.pop(locator)
                    return dict(kind=kind, body=digest, locator=base.group(1), name=gone['name'], planted=f'{locator} dropped')
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
            for locator, b in sorted(after[digest][1].items()):
                prior = after[digest][1].get(f'mods:witness[{int(re.match(r"mods:witness\[(\d+)\]", locator).group(1)) - 1}]')
                if (b.get('witness_type') == 'record_material' and b.get('name') and prior
                        and prior.get('witness_type') == 'record_material' and 'question' not in lines(digest, locator).lower()):
                    after[digest][1][locator] = dict(b, witness_type=None)
                    return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=None)
            continue
        if kind == 'split-untrimmed':
            for locator in sorted(after[digest][1].keys() - before[digest][1].keys()):
                parent = SPLIT.fullmatch(locator)
                if parent and parent.group(1) in before[digest][1]:
                    wrong = dict(before[digest][1][parent.group(1)])
                    after[digest][1][parent.group(1)] = wrong
                    return dict(kind=kind, body=digest, locator=locator, name=after[digest][1][locator]['name'],
                                planted=wrong.get('position'))
            continue
        for locator, a in sorted(before[digest][1].items()):
            b = after[digest][1].get(locator)
            if kind == 'typed-organization':
                if (b == a and not b.get('name') and b.get('organization') and not b.get('witness_type')
                        and not DOCUMENTS & {plain(w) for w in words(lines(digest, locator))}):
                    after[digest][1][locator] = dict(b, witness_type='statement_for_record')
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
            after[digest][1][locator] = wrong
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

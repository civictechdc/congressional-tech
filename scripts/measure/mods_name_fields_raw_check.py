"""Judge a MODS re-read of witness name fields against the raw lines and other publishers' names (ct-rg34).

    mods_name_fields_raw_check.py --before GEN.parquet --after GEN.parquet --raw-root BODIES
        --people WITNESSES.parquet --members MEMBERS.parquet --output OUT.json [--accept REVIEWED.json]
        [--plant KIND ...]

The re-read under test moves an organization out of a witness name ("American Legion" alone, or before
the person: "Vietnam Veterans of America, Richard F. Weidman, ...") and joins a surname written first to its
given name ("Torres Small, Hon. Xochitl, ..."); it also types record entries and names the Members who asked
questions for the record (ct-3aap, ct-zs48). ``--before`` and ``--after`` are appearance generations
(appearance_records rows); only ``mods`` rows are read. ``--raw-root`` holds the retained bodies as
``<sha[:2]>/<sha>.gz``; each body's ``<witness>`` lines and ``<congMember>`` names are read here with
ElementTree. ``--people`` is a published witnesses table: the first and last words of the names the *other*
sources state (Congress.gov, House XML, Senate pages, never MODS) are the given and family names this check
knows. ``--members`` is a published members table (``name`` "Given Family", ``terms`` with dates): who served in the
print's Congress (its ``<congress>``, else its ``<congMember>`` entries', else its ``<heldDate>``). The rule reads
organization words, separators, titles and the print's ``<congMember>`` list; this check reads which words other
publishers use as people's given and family names, the members table, the print's own ``<congMember>`` names, and
the raw line's words.

Asking lines and Members, read without the rule (``asking_lines``, ``member_groups``). A line is an *asking* line
when it holds the word "question(s)" or "request(s)" anywhere, in any case (the rule reads a heading's grammar:
which words come before "from", "by" or "of"); or when it prints names alone (no office, document or heading
word) and follows an asking line, starts a list with "Senators", names two Members or more, or names one by a
chamber or committee title with page numbers. The Members a line names are counted as sets of words, never by
splitting a list: each ``<congMember>`` family name the line prints (any case); every capitalised word after
"Senator(s)", "Representative(s)", "Delegate" or "Congressman" up to a lower-case word, a number or a mark that
ends a name (after a plural title a comma or "and" starts the next Member); and the capitalised words after
"Hon."/"Honorable" that the House style follows ("a Representative in Congress from", "of <a State>"). They are
counted a second time from a fact the rule never reads, the members table: each run of capitalised name words that
ends in the family name of a Member serving in the print's Congress and prints a given name agreeing with theirs, in
the run or after a surname printed first ("Rockefeller IV, Hon. John D" in the 109th). Groups of either count that share a word are one Member.

Both directions, per occurrence key (body, locator); every flag fails the check:

- an occurrence or a body on one side only (``added``, ``removed``, ``unpaired_bodies``), except a line the
  before side read no occurrence for at all, now kept at its own locator with a supported type and, if named, a
  person's name its raw line holds in order: one opening with a known given name or made of the print's
  ``<congMember>`` words (listed under ``restored``); and except an asker (below). Every further part of a line
  (``/part[3]`` on) is ``added`` unless it is an asker;
- ``asker`` (listed, not failing): a row the before side lacks, typed ``record_material`` on an asking line, whose
  name's words the line prints in that order and whose family word is a Member's of that line;
- ``answerer`` (listed, not failing): a row the before side lacks, typed a witness or a statement on an asking line,
  naming in the line's order a person who is not one of its Members (as ``question_asker_as_witness`` reads one);
- ``person_moved``: a changed name that opens with a known given name and whose words the new name lacks;
- ``name_not_in_line``: a new or added name with a word its raw line lacks;
- ``words_lost``: a changed occurrence that loses a word across name, position, organization and
  on_behalf_of (credentials such as "M.D." and titles such as "Hon." may go, as for every witness line, and the
  label "Accompanied by"; on an asking line, so may its heading's words and a contents column's "Page"; a word
  another row of the line now shows is not lost, nor page numbers fused to a kept word, "EPA173-198"; a row whose
  name opened in lower case, a fragment of prose, loses nothing when it comes to name no one);
- ``words_gained``: a changed occurrence that gains a word its raw line lacks;
- ``person_left_in_organization``: a changed occurrence left without a name whose raw line still has a
  later segment opening with a known given name;
- ``reorder_unsupported``: a new or restored name whose words are not in the raw line in that order (a surname
  joined to its given name) and that does not open with a known given name and end with a known family name or a
  family name of the print's ``<congMember>`` entries;
- ``order_unsupported``: on a line with two named rows or more, rows whose display order does not follow where
  their family names stand in the raw line (any row, changed or not);
- ``order_across_lines``: a row shown before a row of a line printed above it (display order against line order,
  across the whole print);
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
  ``DOCUMENTS``) and no person (no segment opening with a known given name, no civil title) (ct-3aap); or to
  ``member_statement`` for a row naming one of its line's Members on a line that names a paper (``PAPERS``, a
  Member's submission); or it is ``record_material`` on an asking line for a row with no name, a Member's family
  word, on a line of names alone, or on a line naming a paper, or with no name where the before row held prose (a
  name opening in lower case). Every ``record_material`` row on an asking line is
  held to that, its type changed or not; and an added row typed a statement on an asking line for a person who
  testified on a line that asks nothing fails (an answerer who testified answers as a witness);
- ``question_asker_as_witness``: any after occurrence, changed or not, left a witness (no type) or a member's
  statement on an asking line,
  unless it names a person who is not one of the line's Members: two name words or more the line prints, none a
  heading, document or office word; or a name the line prints after "Mr.", "Ms.", "Mrs." or "Dr."; or the family
  name of a witness on a line of the print that asks nothing; and in each case a family word that is no Member's
  of that line by either count;
- ``member_unnamed``: an asking line, or one holding a ``record_material`` occurrence, with a Member's word (either
  count) that no occurrence of that line names. Reported at the line's locator with the words left unnamed;
- ``members_merged``: a row of such a line whose name names two of its Members or more ("Boxer and Carper"),
  reported with the line's Member count and its rows naming exactly one Member;
- ``position_not_in_line``: a new or changed position whose words the raw line does not print in that order, next
  to each other ("a Senator in Congress from ..." on a Representative's line), or prints only before its row's name
  or after another row's name ("Commissioner" given to the Senator who asked the Commissioner);
- ``text_cut``: a new or changed nameless row whose text stops inside the segment of the raw line it starts in, a
  word following it before a dot leader, page numbers, a question heading or the line's end ("Report, Arsenic and
  Old Laws" on "Report, Arsenic and Old Laws, NRDC.......267-285 Responses ...");
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
do not parse are listed in ``not_read`` and still compared without a line; prints with no Congress to read are
listed in ``no_congress``, where the members table counts no one.

What it cannot see: it cannot tell an organization from a person whose given name other publishers do not
state twice. Such new names land in ``unconfirmed`` (132 on the 2026-11-08 run), which never fails; a swap of
an organization for a rare-named person ("Nancy-Ann DeParle", "Ikeita Cantu Hinojosa", "Yasmina S. Vinci")
passes unseen. Its "segment the raw line follows with a state" test for ``name_not_person`` restates the rule's
own place heuristic, more strictly (the rule exempts MD, MA, MS and PA as credentials; this check does not), so
it is not an independent measure of places. It reads a document word anywhere in the line, where the typing rule
reads one ending the line, so a line naming a document inside an organization's name and ending in one passes on
either reading. It does not judge honorific or bioguide_id changes, nor a split whose second person has a given
name other publishers do not state twice (that split fails, for a person to accept). The members table sees a
Member the print's ``<congMember>`` list omits, but not one printed by a nickname ("Tom Coburn" for Thomas), by
family name alone ("Senator Boxer", which the title count sees), nor from another Congress; and it counts as a Member
a witness whose name agrees with a serving Member's ("Peter Welch" of the auto dealers in the 114th, "Jess
Stonestreet Jackson" for Jesse Jackson). ``text_cut`` reads a nameless row's text only, and stops at numbers, so a
date dropped from a document's text passes; a position copied from another row passes when the line prints it after
the row's own name too. ``position_not_in_line`` reads contiguity only: a position copied
from another segment of the same line passes. Display order is judged against printed order, never against the
before side. A line of names alone under an asking line counts as asking, so a Member who
testified and is printed alone right under a question heading counts as an asker (the rule's known limit, ct-gfo7
item 5). An asking line's word "question" can stand in footnote text; a ``<congMember>`` family name there that is
also a witness's ("Perry") counts as a Member. ``question_asker_as_witness`` takes any two-word name the line prints
as a person, so a document's title of two plain words left a witness on an asking line passes; ``record_as_witness``
misses a title that prints no document word, quotation or date ("Our Projects, DOE, Loan Programs Office", 1 of the
16 reviewed titles).

``--plant`` writes one wrong value the rule could produce on the after side for each kind named, each on a body no
other plant of the run took (a kind with no occurrence to plant on is listed, unflagged), and the check must flag
each, accepted or not: ``person-moved`` moves an unchanged person's name into the organization
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
line lacks ("Bill Boxer", ``name_not_in_line``); ``members-merged`` reads two askers of a line as one row and drops
the second (``members_merged``); ``wrong-chamber`` gives a Representative's position the other chamber
(``position_not_in_line``); ``rotate-across-lines`` rotates the display order of three one-row lines
(``order_across_lines``); ``roster-gap-reverted`` types back as a witness an asker the print's ``<congMember>`` list
omits and the members table counts (``question_asker_as_witness``), and ``roster-gap-dropped`` drops one that is a
further part of its line (``member_unnamed``); ``answerer-to-record`` types as record material a named witness on an
asking line whose before row there was nameless record material, and ``answerer-mistyped`` types an added answerer
who testified as a statement (both ``type_unsupported``); ``document-cut`` cuts a document's text at its last comma
(``text_cut``); ``position-from-other-row`` gives an asker another row's position (``position_not_in_line``).
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, timedelta
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
         'person_left_in_organization', 'reorder_unsupported', 'order_unsupported', 'order_across_lines',
         'name_not_person', 'split_unsupported', 'type_unsupported', 'question_asker_as_witness', 'member_unnamed',
         'members_merged', 'position_not_in_line', 'text_cut', 'record_as_witness')
PLANTS = {'person-moved': 'person_moved', 'reversed-name': 'reorder_unsupported', 'previous-segment': 'name_not_person',
          'split-untrimmed': 'split_unsupported', 'typed-organization': 'type_unsupported',
          'asker-as-witness': 'question_asker_as_witness', 'asker-dropped': 'member_unnamed',
          'title-as-witness': 'record_as_witness', 'statement-as-witness': 'record_as_witness', 'heading-as-name': 'added',
          'name-emptied': 'member_unnamed', 'committee-segment': 'name_not_person',
          'reversed-asker': 'reorder_unsupported', 'askers-swapped': 'order_unsupported',
          'witness-as-asker': 'type_unsupported', 'heading-reverted': 'question_asker_as_witness',
          'given-added': 'name_not_in_line', 'members-merged': 'members_merged', 'wrong-chamber': 'position_not_in_line',
          'rotate-across-lines': 'order_across_lines', 'roster-gap-reverted': 'question_asker_as_witness',
          'roster-gap-dropped': 'member_unnamed', 'answerer-to-record': 'type_unsupported',
          'answerer-mistyped': 'type_unsupported', 'document-cut': 'text_cut',
          'position-from-other-row': 'position_not_in_line'}
# Words that make a line ask: what was asked or requested, read anywhere in the line, in any case.
ASKING = {'question', 'questions', 'request', 'requests'}
# The words of an asking line's heading, which are no person's.
HEADING = ASKING | set('response responses answer answers submitted record hearing arising during written additional '
                       'posthearing supplemental information'.split())
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
                'resolution petition exhibit packet biography biographies'.split())
# A person's own paper in the record, which their testimony words are not.
PAPERS = DOCUMENTS - {'statement', 'statements', 'testimony', 'comments'}
# Words a heading that follows a document's text opens with.
HEADING_OPENING = {'response', 'responses', 'answer', 'answers', 'question', 'questions'}
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


def congress_on(day):
    """The Congress sitting on a day: the nth runs from January 3 of 1789 + 2(n - 1) for two years."""
    n = (day.year - 1789) // 2 + 1
    return n - 1 if (day.year - 1789) % 2 == 0 and (day.month, day.day) < (1, 3) else n


def serving_members(members_path):
    """Members by the Congress they served in, from a published members table (``name`` "Given Family", ``terms`` with
    ``start`` and ``end`` dates): {congress: {family words: given names}}, the family being the name's last word and
    its last two ("Van Hollen"), suffixes aside. A fact the rule never reads."""
    serving = defaultdict(lambda: defaultdict(set))
    for row in pq.read_table(members_path, columns=['name', 'terms']).to_pylist():
        said = [w for w in map(plain, words(row['name'])) if w and w not in SUFFIXES]
        if len(said) < 2 or len(said[-1]) < 2:
            continue
        for term in row['terms'] or ():
            if not (term.get('start') and term.get('end')):
                continue
            for n in range(congress_on(term['start']), congress_on(term['end'] - timedelta(days=1)) + 1):
                for size in (1, 2):
                    serving[n][tuple(said[-size:])].add(said[0])
    return serving


def name_runs(text):
    """The runs of name words a text prints (capitalised words and initials; a title, a style word or a mark ends a
    run), each as (plain words without suffixes, the given name printed after it when the run is a surname printed
    first: "Rockefeller IV, Hon. John D" -> john)."""
    marks, runs, current = tokens(text) + [('mark', '')], [], []
    for i, (kind, word) in enumerate(marks):
        if name_word(kind, word):
            current.append(plain(word))
            continue
        run = [w for w in current if w and w not in SUFFIXES]
        current = []
        if not run:
            continue
        k = i + 1 if word == ',' else len(marks)
        k += k < len(marks) and plain(marks[k][1]) in ('hon', 'honorable')
        given = plain(marks[k][1]) if len(run) == 1 and k < len(marks) and name_word(*marks[k]) else None
        runs.append((run, given))
    return runs


def table_member(run, serving, given=None):
    """Does a run of name words name a Member serving in the print's Congress: its last word (or two) their family
    name, and its first word (or the given name printed after a surname printed first) agreeing with their given name
    (one initial, and one a prefix of the other or three letters shared: "Bernie" for Bernard; not "Tom" for Thomas)?
    A family name printed with no given name names no one here."""
    def agrees(printed, official):
        return printed[0] == official[0] and (len(printed) == 1 or printed.startswith(official)
                                              or official.startswith(printed) or printed[:3] == official[:3])
    for size in (2, 1):
        names = serving.get(tuple(run[-size:])) if len(run) >= size and len(run[-1]) > 1 else None
        printed = run[0] if len(run) > size else given
        if names and printed and any(agrees(printed, official) for official in names):
            return True
    return False


def table_groups(line, serving):
    """The Members a line names by the members table, each as the set of its name's words (initials aside)."""
    return [{w for w in run if len(w) > 1} | ({given} if given and len(given) > 1 else set())
            for run, given in name_runs(line) if table_member(run, serving, given)] if serving else []


def merge(groups):
    """Groups that share a word are one Member."""
    merged = []
    for group in filter(None, groups):
        for other in [m for m in merged if m & group]:
            merged.remove(other)
            group = group | other
        merged.append(group)
    return merged


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
    """A body's <witness> lines; the words of the Members its <congMember> entries name; each such Member's family
    name, as words (from the "Surname, Given" authority name, else the last word of "Given Surname"); and the print's
    Congress (its <congress>, else its <congMember> entries', else the Congress of its <heldDate>; None if none)."""
    path = Path(raw_root) / digest[:2] / f'{digest}.gz'
    root = ET.fromstring(gzip.decompress(path.read_bytes()))
    tags = [(el.tag.rsplit('}', 1)[-1], el) for el in root.iter()]
    said = Counter((el.text or '').strip() for tag, el in tags
                   if tag == 'congress' and (el.text or '').strip().isdigit())
    said = said or Counter(el.get('congress') for tag, el in tags
                           if tag == 'congMember' and (el.get('congress') or '').isdigit())
    held = next((el.text.strip() for tag, el in tags
                 if tag == 'heldDate' and re.fullmatch(r"\d{4}-\d\d-\d\d", (el.text or '').strip())), None)
    congress = int(said.most_common(1)[0][0]) if said else congress_on(date.fromisoformat(held)) if held else None
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
    return lines, members, families, congress


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
            first = (i + size + 1 < len(marks) and marks[i + size][1] == ','
                     and lowered[i + size + 1] in ('hon', 'honorable'))  # "Akaka, Hon. Daniel K"
            titled = first or any(lowered[t] in MEMBER_TITLES for t in range(max(i - 4, 0), i) if lowered[t])
            if not near_title or titled:
                groups.append(set(family) if first else around(i, i + size))
    taken = set()  # positions of words a chamber title's run read as a Member's name
    for i, word in enumerate(lowered):
        kind_before, text_before = marks[i - 1] if i else ('mark', '')
        if word not in CHAMBER or kind_before == 'word' and (
                plain(text_before) in ('of', 'the', 'state') or capital(text_before) and i - 1 not in taken):
            continue
        plural, current, ended = word in ('senators', 'representatives'), set(), False
        for k in range(i + 1, len(marks)):
            kind, text = marks[k]
            low = plain(text)
            if name_word(kind, text) and not ended:
                taken.add(k)
                if len(low) > 1 and low not in SUFFIXES:
                    current.add(low)
                # The print's own Member ends the name: the list's item, or a titled name.
                ended = low in last_words and not (k + 1 < len(marks) and lowered[k + 1] in last_words)
            elif plural and (text == ',' or low == 'and'):
                groups.append(current)
                current, ended = set(), False
            elif not (ended and plural and name_word(kind, text)):
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
    return merge(groups)


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
    """The words of the Members a line names (member_groups); a <congMember> family name counts anywhere only on a
    line of names alone, elsewhere near a Member title (a document or a witness can print a Member's surname)."""
    return set().union(*member_groups(line, families, near_title=kind != 'list') or [set()])


def in_order(name, line):
    """Are the name's words in the line, in the name's order and next to each other?"""
    sequence, text = [plain(w) for w in words(name) if plain(w)], [plain(w) for w in words(line) if plain(w)]
    return any(text[i:i + len(sequence)] == sequence for i in range(len(text) - len(sequence) + 1))


def line_segments(line):
    return [part.strip() for part in re.split(r'[,;:]', line) if part.strip()]


def bag(occurrence):
    """The words of an occurrence's four fields, without credentials and titles."""
    return Counter(plain(w) for f in FIELDS for w in words((occurrence or {}).get(f)) if not credential(w))


def judge(before, after, raw_root, given, family, serving=None):
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
        # Ends in a family name: one other publishers state, or a <congMember>'s of the print ("Daniel K Akaka").
        return person(name) and (family_word(name) in family or family_word(name) in {f[-1] for f in member_families})

    out = {key: [] for key in (*FLAGS, 'unconfirmed', 'residual', 'split', 'restored', 'asker', 'answerer', 'not_read',
                               'no_congress', 'bodies_only_before', 'bodies_only_after')}
    counts = Counter()
    out['bodies_only_before'] = sorted(before.keys() - after.keys())
    out['bodies_only_after'] = sorted(after.keys() - before.keys())
    for digest in sorted(before.keys() & after.keys()):
        package, old = before[digest]
        new = after[digest][1]
        try:
            lines, members, member_families, congress = raw_print(raw_root, digest)
        except (OSError, ET.ParseError, EOFError) as error:
            # Named, and still compared: with no raw line, any changed name is reported as not in its line.
            out['not_read'].append(dict(body=digest, package=package, error=type(error).__name__))
            lines, members, member_families, congress = [], set(), set(), 0
        if congress is None:
            out['no_congress'].append(dict(body=digest, package=package))  # the members table reads nothing here
        serving_now = (serving or {}).get(congress) or {}
        counts['bodies'] += 1
        asking = asking_lines(lines, member_families)

        def position(locator):
            index = re.match(r"mods:witness\[(\d+)\]", locator)
            return int(index.group(1)) if index else 0

        recorded = {position(k) for k, v in new.items() if v.get('witness_type') == 'record_material'}
        # The Members an asking or record line names, counted twice over: by the print's own record (member_groups)
        # and by the members table (who served in the print's Congress); groups sharing a word are one Member.
        groups_of = {n: merge(member_groups(lines[n - 1], member_families, near_title=asking.get(n) != 'list')
                              + table_groups(lines[n - 1], serving_now))
                     for n in range(1, len(lines) + 1) if n in asking or n in recorded}
        members_of = {n: set().union(*groups) if groups else set() for n, groups in groups_of.items()}

        def members_at(n):
            """The Members line n names by either count, read for any line a type is judged on."""
            if n not in members_of and 0 < n <= len(lines):
                members_of[n] = set().union(*merge(member_groups(lines[n - 1], member_families, near_title=True)
                                                   + table_groups(lines[n - 1], serving_now)) or [set()])
            return members_of.get(n, set())
        judged = set(members_of)  # the lines member_unnamed reads: asking or holding record material

        def line_of(locator):
            n = position(locator)
            return lines[n - 1] if 0 < n <= len(lines) else ''

        def a_member(name, locator):
            return family_word(name) in members_at(position(locator))

        # Family words of the print's witnesses on lines that ask nothing ("Penny Rue" for "Dr. Rue" on an asking line).
        testified = {family_word(r.get('name')) for k, r in new.items()
                     if r.get('name') and r.get('witness_type') is None and position(k) not in asking}

        def someone(name, locator):
            """A person who is not one of the line's Members: two name words or more the line prints, none a heading,
            document or office word; or a name after a civil title ("Ms. Jeffrey"); or a witness's family name from a
            line that asks nothing. Never a family word of the line's Members, by either count."""
            if not name or not family_word(name):
                return False
            line = line_of(locator)
            said = [w for w in name_words(name) if w not in ('by', 'to', 'for', 'from', 'of', 'and')]
            printed = (len(said) > 1 and set(said) <= {plain(w) for w in words(line)} and not set(said) & NOT_PERSON)
            last = (name or '').split()[-1:] or ['']
            titled = bool(re.search(rf"\b(?:Mr|Ms|Mrs|Dr)\.\s+{re.escape(last[0])}\b", line))
            return (printed or titled or family_word(name) in testified) and not a_member(name, locator)

        def answerer(b, locator):
            """A row the before side lacks, typed a witness or a statement, on an asking line, naming in the line's
            order a person who is not one of its Members."""
            name = b.get('name')
            return (b.get('witness_type') in (None, 'statement_for_record') and position(locator) in asking
                    and bool(name) and in_order(name, line_of(locator)) and someone(name, locator))

        def record_supported(b, locator):
            """record_material on an asking line: nameless, a Member's, on a line of names alone, or a person's own
            paper the line names ("... Biography")."""
            n, name = position(locator), b.get('name')
            return n in asking and (not name or a_member(name, locator) or asking[n] == 'list'
                                    or bool(PAPERS & {plain(w) for w in words(line_of(locator))}))

        def beside_name(b, locator):
            """Is a row's position printed after its own name, with no other row's name between them?"""
            if not b.get('name') or not b.get('position'):
                return True
            said = [plain(w) for w in words(line_of(locator)) if plain(w)]
            phrase = [plain(w) for w in words(b['position']) if plain(w)]
            starts = [i for i in range(len(said) - len(phrase) + 1) if said[i:i + len(phrase)] == phrase]
            own = [i for i, w in enumerate(said) if w == family_word(b['name'])]
            others = {family_word(r.get('name')) for r in new.values() if r is not b and r.get('name')
                      and position(r['source_locator']) == position(locator)} - {family_word(b['name']), None}
            between = [i for i, w in enumerate(said) if w in others]
            return not own or any(f < s and not any(f < o < s for o in between) for f in own for s in starts)

        def cut_short(b, line):
            """Does a nameless row's text stop inside the segment of the raw line it starts in (a word follows it before
            a dot leader, page numbers, a question heading or the line's end)?"""
            text = b.get('organization')
            if b.get('name') or not text:
                return False
            marks = tokens(line)
            said = [(i, plain(t)) for i, (kind, t) in enumerate(marks) if kind == 'word' and plain(t)]
            phrase = [w for w in map(plain, words(text)) if w and w[0].isalpha()]
            for s in range(len(said) - len(phrase) + 1) if phrase else ():
                if [w for _, w in said[s:s + len(phrase)]] == phrase:
                    for kind, token in marks[said[s + len(phrase) - 1][0] + 1:]:
                        if kind == 'word':
                            return plain(token) not in HEADING_OPENING
                        if token not in ',;:()':
                            return False
                    return False
            return False

        def asker(b, locator):
            """A row the before side lacks that is a Member the asking line prints, in order."""
            name, line = b.get('name'), line_of(locator)
            return (b.get('witness_type') == 'record_material' and position(locator) in asking and bool(name)
                    and set(map(plain, words(name))) <= set(map(plain, words(line)))
                    and (in_order(name, line) or reorder_supported(name)) and a_member(name, locator))

        # Witness rows on an asking line, record material on one (whether its type changed or not), documents left a
        # witness, and the order rows are shown in.
        by_line = {}
        for locator, b in sorted(new.items()):
            by_line.setdefault(position(locator), []).append(b)
            line = line_of(locator)
            item = dict(package=package, body=digest, locator=locator, line=line,
                        after={f: b.get(f) for f in KEYED})
            if (b.get('witness_type') == 'record_material' and position(locator) in asking
                    and (old.get(locator) or {}).get('witness_type') == 'record_material'
                    and not record_supported(b, locator)):
                out['type_unsupported'].append(item)
            if (position(locator) in asking and b.get('witness_type') in (None, 'member_statement')
                    and not someone(b.get('name'), locator)):
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
        # Across lines: every row of a line is shown after every row of the lines printed before it.
        shown_before = 0
        for n, rows in sorted(by_line.items()):
            for r in rows:
                if r.get('display_order') is not None and r['display_order'] < shown_before:
                    out['order_across_lines'].append(dict(package=package, body=digest, locator=r['source_locator'],
                                                          line=line_of(r['source_locator']),
                                                          after={f: r.get(f) for f in KEYED}, shown_before=shown_before))
            shown_before = max([shown_before, *(r['display_order'] for r in rows if r.get('display_order') is not None)])
        # Members against rows: a row names one Member at most (each run of its name's words naming one of the line's
        # Members counts once), and a line naming k Members has k rows naming one each.
        for n, groups in sorted(groups_of.items()):
            rows = [(r, sum(1 for run, _ in name_runs(r.get('name') or '') if any(set(run) & g for g in groups)))
                    for r in by_line.get(n, [])]
            for r, named in rows:
                if named > 1:
                    out['members_merged'].append(dict(package=package, body=digest, locator=r['source_locator'],
                                                      line=lines[n - 1], after={f: r.get(f) for f in KEYED},
                                                      members=len(groups), rows_naming_one=sum(k == 1 for _, k in rows)))
        # Every Member an asking or record line names has a row naming them on that line.
        for n in sorted(judged):
            line = lines[n - 1]
            named = {plain(w) for r in by_line.get(n, []) for w in words(r.get('name'))}
            if missing := members_of[n] - named:
                rows = by_line.get(n, [])
                out['member_unnamed'].append(dict(package=package, body=digest, locator=f'mods:witness[{n}]', line=line,
                                                  words=sorted(missing),
                                                  after={f: [r.get(f) for r in rows] for f in ('name', 'witness_type')}))

        def type_supported(a, b, line, locator):
            if b.get('witness_type') == 'record_material':
                # ... or a row that held a fragment of prose (a name opening in lower case) and now names no one.
                prose = bool(re.match(r"[a-z]", (a.get('name') or '').strip()))
                return record_supported(b, locator) or (not b.get('name') and prose)
            if b.get('witness_type') == 'member_statement':
                # A Member's own submission: the row names one of the line's Members and the line names a paper.
                return (a.get('witness_type') is None and bool(b.get('name')) and a_member(b['name'], locator)
                        and bool(PAPERS & {plain(w) for w in words(line)}))
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
            if b.get('position') and not (in_order(b['position'], line) and beside_name(b, locator)):
                out['position_not_in_line'].append(item)
            if cut_short(b, line):
                out['text_cut'].append(item)
            if (b.get('witness_type') == 'statement_for_record' and position(locator) in asking
                    and family_word(b.get('name')) in testified):
                out['type_unsupported'].append(item)  # an answerer who testified answers as a witness
                continue
            if asker(b, locator):
                out['asker'].append(item)
                continue
            if answerer(b, locator):
                out['answerer'].append(item)
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
            if (b.get('position') and a.get('position') != b['position']
                    and not (in_order(b['position'], line) and beside_name(b, locator))):
                out['position_not_in_line'].append(item)
            if a.get('organization') != b.get('organization') and cut_short(b, line):
                out['text_cut'].append(item)
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
            # On an asking line the heading's words are no one's: a row that was named for the heading may shed them,
            # and a contents column's "Page". "Accompanied by:" is a label any line may shed.
            shed = HEADING | MEMBER_TITLES | {'member', 'the', 'to', 'by', 'from', 'of', 'for', 'and', 'following',
                                              'page'} if position(locator) in asking else set()
            shed |= {'accompanied'}
            # A word another row of the same line now shows (an asker appended at /part[2]) is not lost to a reader,
            # nor page numbers fused to a kept word ("EPA173-198" for "EPA").
            shown = {w for r in by_line.get(position(locator), []) if r is not b for w in bag(r)}
            lost = Counter({w: k for w, k in (old_words - new_words).items() if w not in shed and w not in shown
                            and re.sub(r"\d+$", "", w) not in new_words})
            # A name that opens in lower case is a fragment of prose, no one's: a row that held one and now names no
            # one loses no person or affiliation.
            if not new_name and re.match(r"[a-z]", (old_name or '').strip()):
                lost = Counter()
            if lost:
                out['words_lost'].append(dict(item, words=sorted(lost.elements())))
            # A gained word must come from the raw line; a re-read may restore line text the old one dropped.
            gained = Counter(w for w in (new_words - old_words).elements() if w not in {plain(x) for x in words(line)})
            if gained:
                out['words_gained'].append(dict(item, words=sorted(gained.elements())))
            if not new_name and any(person(s) for s in re.split(r'[,;:]', line)[1:]):
                out['person_left_in_organization'].append(item)
    return dict(counts), out


def plant(kind, before, after, given, family, raw_root, serving=None, taken=()):
    """Write one wrong value the rule could produce on the after side, on a body no other plant of the run took;
    None when no occurrence fits."""
    printed = {}

    def read(digest):
        """A body's raw print, read once per run."""
        if digest not in printed:
            try:
                printed[digest] = raw_print(raw_root, digest)
            except (OSError, ET.ParseError, EOFError):
                printed[digest] = None
        return printed[digest]

    def lines(digest, locator):
        index = re.match(r"mods:witness\[(\d+)\]", locator)
        found = (read(digest) or [[]])[0]
        return found[int(index.group(1)) - 1] if index and int(index.group(1)) <= len(found) else ''

    def base(locator):
        return re.match(r"mods:witness\[\d+\]", locator).group()

    def roster_gap(digest, locator, b):
        """A record_material row naming a Member the members table counts in the print's Congress whom the print's
        own <congMember> list omits."""
        if b.get('witness_type') != 'record_material' or not b.get('name') or not read(digest):
            return False
        _, _, families, congress = read(digest)
        runs = name_runs(b['name'])
        return (bool(runs) and family_word(b['name']) not in {f[-1] for f in families}
                and table_member(runs[-1][0], (serving or {}).get(congress) or {}, runs[-1][1]))

    for digest in sorted(before.keys() & after.keys()):
        if digest in taken:
            continue
        old, new = before[digest][1], after[digest][1]
        asks = lambda locator: bool(ASKING & {plain(w) for w in words(lines(digest, locator))})  # noqa: E731
        if kind == 'answerer-to-record':
            # A named witness row on an asking line typed record material where the before side's row was nameless
            # record material, so the type does not change (the fourth review's Kulick case).
            for locator, b in sorted(new.items()):
                a = old.get(locator) or {}
                if (b.get('witness_type') is None and b.get('name') and a.get('witness_type') == 'record_material'
                        and not a.get('name') and asks(locator)):
                    new[locator] = dict(b, witness_type='record_material')
                    return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted='record_material')
            continue
        if kind == 'answerer-mistyped':
            # An added answerer who testified on a line of the print that asks nothing, typed a statement.
            witnesses = {family_word(r.get('name')) for k, r in old.items()
                         if r.get('name') and r.get('witness_type') is None and not asks(k)}
            for locator, b in sorted(new.items()):
                if (locator not in old and b.get('witness_type') is None and b.get('name') and asks(locator)
                        and family_word(b['name']) in witnesses):
                    new[locator] = dict(b, witness_type='statement_for_record')
                    return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted='statement_for_record')
            continue
        if kind == 'document-cut':
            # A document's printed text cut at its last comma ("Report, Arsenic and Old Laws, NRDC" -> "..., Old Laws").
            for locator, b in sorted(new.items()):
                text = b.get('organization') or ''
                if (not b.get('name') and b.get('witness_type') == 'record_material' and ', ' in text
                        and in_order(text, lines(digest, locator)) and text.rsplit(', ', 1)[1][:1].isalpha()):
                    new[locator] = dict(b, organization=text.rsplit(', ', 1)[0])
                    return dict(kind=kind, body=digest, locator=locator, name=text,
                                planted=new[locator]['organization'])
            continue
        if kind == 'position-from-other-row':
            # An asker given the position another row of its line prints (the fourth review's Boxer/Svinicki case).
            for locator, b in sorted(new.items()):
                if b.get('witness_type') != 'record_material' or not b.get('name') or b.get('position'):
                    continue
                other = next((r for k, r in sorted(new.items()) if r is not b and base(k) == base(locator)
                              and r.get('position') and r.get('name')), None)
                if other and in_order(other['position'], lines(digest, locator)):
                    new[locator] = dict(b, position=other['position'])
                    return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=other['position'])
            continue
        if kind == 'members-merged':
            # Two askers of one line read as one row ("Boxer and Carper"), the second row dropped.
            for locator, b in sorted(new.items()):
                second = f'{base(locator)}/part[2]'
                c = new.get(second)
                if (locator == base(locator) and c and b.get('witness_type') == c.get('witness_type') == 'record_material'
                        and b.get('name') and c.get('name') and family_word(b['name']) != family_word(c['name'])):
                    new[locator] = dict(b, name=f"{b['name']} and {c['name']}")
                    new.pop(second)
                    return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=new[locator]['name'])
            continue
        if kind == 'wrong-chamber':
            # A Representative's position given the other chamber ("a Senator in Congress from ...").
            for locator, b in sorted(new.items()):
                position = b.get('position') or ''
                if 'a Representative in Congress' in position and old.get(locator) == b:
                    new[locator] = dict(b, position=position.replace('Representative', 'Senator'))
                    return dict(kind=kind, body=digest, locator=locator, name=b.get('name'),
                                planted=new[locator]['position'])
            continue
        if kind == 'rotate-across-lines':
            # Three lines in a row, one named row each, shown in a rotated order (2, 3, 4 -> 4, 2, 3).
            singles = {}
            for locator, b in new.items():
                singles.setdefault(base(locator), []).append(b)
            index = {int(re.search(r"\d+", k).group()): rows[0] for k, rows in singles.items() if len(rows) == 1}
            for n in sorted(index):
                rows = [index.get(n + k) for k in range(3)]
                if all(r and r.get('name') and r.get('display_order') is not None for r in rows):
                    orders = [r['display_order'] for r in rows]
                    if orders == sorted(orders):
                        for r, order in zip(rows, orders[-1:] + orders[:-1]):
                            new[r['source_locator']] = dict(r, display_order=order)
                        return dict(kind=kind, body=digest, locator=rows[1]['source_locator'], name=rows[1]['name'],
                                    planted=orders[-1:] + orders[:-1])
            continue
        if kind in ('roster-gap-reverted', 'roster-gap-dropped'):
            # An asker the print's <congMember> list omits (printed with "Hon." alone) typed back as a witness, or,
            # when it is a further part of its line, dropped.
            for locator, b in sorted(new.items()):
                further = locator != base(locator)
                if (kind == 'roster-gap-dropped') != further or not roster_gap(digest, locator, b):
                    continue
                if kind == 'roster-gap-dropped':
                    new.pop(locator)
                    return dict(kind=kind, body=digest, locator=base(locator), name=b['name'], planted=f'{locator} dropped')
                new[locator] = dict(b, witness_type=None)
                return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=None)
            continue
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
                if (kind == 'reversed-asker' and len(said) > 1 and len(b['name'].split()) == 2
                        and not in_order(' '.join(reversed(b['name'].split())), lines(digest, locator))):
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
            # A joined line read as two people: the second person's words are the ones the parent lost.
            for locator in sorted(new.keys() - old.keys()):
                parent = SPLIT.fullmatch(locator)
                if (parent and parent.group(1) in old and parent.group(1) in new
                        and new[locator].get('witness_type') != 'record_material'
                        and bag(new[locator]) and bag(new[locator]) == bag(old[parent.group(1)]) - bag(new[parent.group(1)])):
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
            elif (kind == 'reversed-name' and b and any(a.get(f) != b.get(f) for f in FIELDS) and len(parts) > 1
                  and parts[0] in given and parts[-1] in family and parts[-1] not in given
                  and not in_order(' '.join(b['name'].rsplit(' ', 1)[::-1]), lines(digest, locator))):
                given_part, surname = b['name'].rsplit(' ', 1)
                wrong = dict(b, name=f'{surname} {given_part}')
            else:
                continue
            new[locator] = wrong
            return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=wrong['name'])
    return None


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
    parser.add_argument('--members', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--accept', type=Path)
    parser.add_argument('--plant', nargs='+', choices=sorted(PLANTS), default=[])
    args = parser.parse_args(argv)
    given, family = known_names(args.people)
    serving = serving_members(args.members)
    before, after = generation(args.before), generation(args.after)
    # Each plant on its own body, all judged in one run; a kind with no occurrence to plant on is listed, unflagged.
    planted = []
    for kind in args.plant:
        found = plant(kind, before, after, given, family, args.raw_root, serving, {p['body'] for p in planted if p.get('body')})
        planted.append(found or dict(kind=kind, body=None, locator=None, name=None, planted=None))
    counts, out = judge(before, after, args.raw_root, given, family, serving)
    planted_at = {(p['body'], p['locator']) for p in planted if p['body']}
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
            if key in reviewed and (item['body'], item['locator']) not in planted_at:
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
    for p in planted:
        p['flagged'] = any(i['body'] == p['body'] and i['locator'] == p['locator']
                           for i in out[PLANTS[p['kind']]]) if p['body'] else None
    result = dict(status='failed' if failed else 'passed', failed=failed, counts=counts, known_given_names=len(given),
                  known_family_names=len(family), sizes={k: len(v) for k, v in out.items()}, planted=planted, **out)
    args.output.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps(dict(status=result['status'], failed=failed, counts=counts, sizes=result['sizes'], planted=planted)))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())

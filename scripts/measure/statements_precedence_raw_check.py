"""Judge every GovInfo statement label and every superseded witness row against raw records (red-f3).

    statements_precedence_raw_check.py --after DIR --records PARQUET --appearances PARQUET --captures PARQUET
        --mirror R2 --output OUT.json

Statements: each mods row labelled statement_for_record or member_statement is found in its print's raw
<witness> lines (ElementTree, by family name), and judged from two raw facts the producer does not read
together: whether the meeting's own Congress.gov or House list names the same person (then they
testified: contradicted), and whether the raw line names a document (letter, statement, record,
questions, submission, report, article, memorandum: supported). Neither: ambiguous. Unlabelled mods rows
whose raw line says "for the record" or opens with "Letter" are counted as possible missed statements.

Superseded: each row with superseded_by is compared with its target row by a different name measure from
the model's: family names by `family()` here, then given names agree when equal, one is an initial or
prefix of the other, difflib ratio >= 0.8, or a nickname pair below (both directions listed explicitly).
A row on a different occasion from its target, or with a different family, is contradicted; one without
a given name on either side is ambiguous.
"""
import argparse
from collections import Counter, defaultdict
import difflib
import html
import json
from pathlib import Path
import re
import sys
import unicodedata

import duckdb

sys.path.insert(0, str(Path(__file__).parent))
from meeting_semantics_raw_check import Family, Lists, Prints, family, raw_meetings, records  # noqa: E402

DOCUMENT = re.compile(r"\b(?:letters?|statements?|for the record|questions?|responses?|submissions?|submitted|reports?|"
                      r"articles?|memorand(?:um|a)|comments|testimony of .* submitted|editorial|op-ed|press release)\b", re.I)
NICKNAMES = {frozenset(p) for p in [('robert', 'bob'), ('robert', 'rob'), ('robert', 'bobby'), ('william', 'bill'), ('william', 'will'),
             ('william', 'billy'), ('james', 'jim'), ('james', 'jimmy'), ('richard', 'dick'), ('richard', 'rick'), ('michael', 'mike'),
             ('thomas', 'tom'), ('joseph', 'joe'), ('charles', 'chuck'), ('charles', 'charlie'), ('edward', 'ed'), ('edward', 'ted'),
             ('elizabeth', 'liz'), ('elizabeth', 'beth'), ('katherine', 'kate'), ('katherine', 'kathy'), ('christopher', 'chris'),
             ('daniel', 'dan'), ('david', 'dave'), ('anthony', 'tony'), ('stephen', 'steve'), ('steven', 'steve'), ('gregory', 'greg'),
             ('jennifer', 'jen'), ('patricia', 'pat'), ('patrick', 'pat'), ('margaret', 'peggy'), ('margaret', 'maggie'),
             ('deborah', 'debbie'), ('timothy', 'tim'), ('kenneth', 'ken'), ('ronald', 'ron'), ('donald', 'don'), ('gerald', 'jerry'),
             ('lawrence', 'larry'), ('samuel', 'sam'), ('benjamin', 'ben'), ('nicholas', 'nick'), ('jonathan', 'jon'), ('andrew', 'andy'),
             ('alexander', 'alex'), ('matthew', 'matt'), ('peter', 'pete'), ('frederick', 'fred'), ('susan', 'sue'), ('rebecca', 'becky')]}
DROP = set("mr mrs ms miss dr hon honorable the rev sen senator rep representative gen general lt col maj adm admiral capt "
           "sgt jr sr ii iii iv phd md mph esq ret usa usn usaf usmc chairman chairwoman ambassador governor mayor judge lieutenant "
           "major vice rear brigadier colonel commander sergeant chief master command private specialist secretary deputy "
           "assistant undersecretary under general's professor captain mg bg lg vadm radm cdr cpt ltg gen. dean bishop "
           "father sister pastor reverend president".split())


def words(name):
    text = html.unescape(name or '').replace('\u2019', '').replace("'", '')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    text = re.sub(r'\([^)]*\)', ' ', text)
    if ',' in text and len(re.findall(r'[a-z]+', text.split(',')[0])) == 1:
        # "Last, First ..." as GovInfo writes it
        last, rest = text.split(',', 1)
        text = rest.split(',')[0] + ' ' + last
    else:
        text = text.split(',')[0]
    return [w for w in re.findall(r"[a-z][a-z'\-]*", text.replace('`', ' ').replace('"', ' ')) if w not in DROP]


def given_agree(a, b):
    if not a or not b:
        return None
    x, y = a[0], b[0]
    if x == y or frozenset((x, y)) in NICKNAMES:
        return True
    if len(x) == 1 or len(y) == 1:
        return x[0] == y[0]
    if min(len(x), len(y)) >= 2 and (x.startswith(y) or y.startswith(x)):
        return True
    return difflib.SequenceMatcher(None, x, y).ratio() >= 0.8


PARTICLES = {'st', 'van', 'von', 'de', 'del', 'della', 'la', 'le', 'da', 'di', 'du', 'mac', 'den', 'der', 'ter'}
TRAILING = {'ph', 'd', 'phd', 'md', 'm', 'jd', 'mba', 'mph', 'rn', 'cpa', 'esq', 'jr', 'sr', 'ii', 'iii', 'iv', 'ret'}


def split_name(name):
    """(given words, family) by this judge's own reading: trailing credentials dropped, particles kept with the family."""
    w = words(name)
    while w and w[-1] in TRAILING:
        w.pop()
    if not w:
        return [], None
    i = len(w) - 1
    while i > 0 and w[i - 1] in PARTICLES:
        i -= 1
    return w[:i], ' '.join(w[i:])


def same_person(a, b):
    """'same', 'different_family', 'different_given', 'middle_only' (given names differ, middle initials
    agree: a nickname or a typo the table lacks) or None (no given name to compare)."""
    (ga, fa), (gb, fb) = split_name(a), split_name(b)
    if not fa or not fb:
        return 'different_family'
    a_key, b_key = re.sub('[^a-z]', '', fa), re.sub('[^a-z]', '', fb)
    if a_key != b_key:
        # A one-letter slip either side (Yocom/Yocum, Hotlz-Eakin) is a spelling, not another person;
        # a hyphenated family may be listed by its last part alone (Barrett-Glasgow / Glasgow).
        near = difflib.SequenceMatcher(None, a_key, b_key).ratio() >= 0.85
        part = any(p and p == b_key for p in re.split('[- ]', fa)) or any(p and p == a_key for p in re.split('[- ]', fb))
        if not (near or part):
            return 'different_family'
    agree = given_agree(ga, gb)
    if agree is None:
        return None
    if agree:
        return 'same'
    if len(ga) > 1 and len(gb) > 1 and ga[1][0] == gb[1][0]:
        return 'middle_only'
    return 'different_given'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('after', 'records', 'appearances', 'captures', 'mirror', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    db = duckdb.connect(config=dict(memory_limit='3GB', threads=4))
    congress, _house, _read, _unread = raw_meetings(args)
    prints, lists = Prints(args, db), Lists(args, db, congress)
    rows = records(db.execute(f"SELECT * EXCLUDE(record_sha) FROM read_parquet('{Path(args.after) / 'witnesses.parquet'}')"))
    by_key = {r['witness_key']: r for r in rows}
    by_occasion = defaultdict(list)
    for r in rows:
        by_occasion[r['occasion']].append(r)

    statements, missed = Family('statements'), Counter()
    for r in rows:
        if r['source'] != 'mods':
            continue
        facts = prints(r['package_id'])
        if facts is None:
            if r['witness_type'] in ('statement_for_record', 'member_statement'):
                statements.add(r['witness_key'], 'unread')
            continue
        fam = family(r['name'])
        lines = [l for l in facts['witness_lines'] if fam and fam in re.findall(r'[a-z]+', unicodedata.normalize('NFKD', l).encode('ascii', 'ignore').decode().lower())]
        line = lines[0] if lines else None
        if r['witness_type'] not in ('statement_for_record', 'member_statement'):
            if line and re.search(r'for the record|^\W*letters?\b', line, re.I):
                missed['unlabelled_line_names_a_document'] += 1
            continue
        event = int(r['occasion'].split(':')[1]) if (r['occasion'] or '').startswith('meeting:') else None
        own = lists.lists.get(event, set()) if event else set()
        on_list = bool(fam and fam in own)
        # Someone on the meeting's own list testified; their prepared statement is still a document, and the
        # check is whether they are shown as a witness on the occasion by another row.
        shown = any(o['occasion'] == r['occasion'] and o['witness_type'] not in ('statement_for_record', 'member_statement')
                    and not o['superseded_by'] and same_person(o['name'], r['name']) == 'same' for o in by_occasion[r['occasion']])
        verdict = ('raw_supports_testified_and_shown' if on_list and shown else
                   'raw_contradicts' if on_list and not (line and re.search(r'for the record', line, re.I)) else
                   'raw_supports' if line and DOCUMENT.search(line) else
                   'raw_supports_member' if r['witness_type'] == 'member_statement' and line and re.search(r'representative in congress|delegate|resident commissioner', line, re.I) and DOCUMENT.search(line) else
                   'line_not_found' if line is None else 'ambiguous')
        statements.add(r['witness_key'], verdict, type=r['witness_type'], name=r['name'], line=line, occasion=r['occasion'], own_list_has_family=on_list)

    superseded = Family('superseded')
    for r in rows:
        if not r['superseded_by']:
            continue
        t = by_key.get(r['superseded_by'])
        if t is None:
            superseded.add(r['witness_key'], 'target_missing', name=r['name'])
            continue
        if t['occasion'] != r['occasion']:
            superseded.add(r['witness_key'], 'raw_contradicts', name=r['name'], target=t['name'], why='occasion')
            continue
        same = same_person(r['name'], t['name'])
        verdict = {'same': 'raw_supports', 'middle_only': 'ambiguous_middle_agrees', None: 'ambiguous_no_given'}.get(same, 'raw_contradicts')
        superseded.add(r['witness_key'], verdict, why=same, name=r['name'], target=t['name'], source=r['source'], target_source=t['source'], occasion=r['occasion'])

    report = dict(statements=statements.report(), superseded=superseded.report(), possible_missed_statements=dict(missed),
                  witness_rows=dict(rows=len(rows), shown=sum(1 for r in rows if not r['superseded_by']),
                                    superseded=sum(1 for r in rows if r['superseded_by']),
                                    statements=Counter(r['witness_type'] for r in rows if r['witness_type'] in ('statement_for_record', 'member_statement'))))
    Path(args.output).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(dict(statements=(statements.rows, dict(statements.verdicts)), superseded=(superseded.rows, dict(superseded.verdicts)),
                          missed=dict(missed), rows=report['witness_rows']), default=str))


if __name__ == '__main__':
    main()

"""Judge which witness rows are sitting Members of Congress acting officially (ct-kw85) with a reading of its own.

    member_appearances_raw_check.py --witnesses witnesses.parquet [--decisions witness_members.parquet]
        --members members.parquet --terms member_terms.parquet --meetings meetings.parquet
        [--prints prints.parquet] [--plant] --output OUT.json

The rows under test are a release's witnesses (witness_type member_appearance, matched_bioguide_id, match_basis), or a
release's witnesses with an engine run's decisions laid over them (--decisions: witness_members).
Members come from the spicy-regs members table itself (name_first, name_last, name_nickname and other_names, which
the rule does not read) and its member_terms; hearing dates and titles from the release's meetings and, for prints
without a meeting, a prints table (package_id, held_dates, title) read from the raw MODS.

Everything here is this check's own reading: names are folded with Unicode NFKD and split on anything not a letter;
offices, seats, states and outside words are its own short lists. A row names a sitting Member three ways: by name
(family name, and a first name where one word starts with the other, three letters at least, or spells out an
abbreviated one: 'William' for 'Wm.'), by seat (it states a House seat, a district of a state, a state at large or a
territory's Delegate, and a word of its name or first field is the holder's family name), or by initial (one side of
the first name is a bare initial and the Member is the only one sitting in the stated state and chamber with that
family name and initial). It judges in both directions:
 - cross-publisher (the core measure): an appearance whose house_xml row carries the Bioguide ID of a Member sitting
   on the date is labelled by that publisher; every other publisher's row of the same appearance is graded on what
   the rule decided from its own words ('same Member', 'different Member', 'silent' when only the appearance matched
   it). The rule never reads a name when the publisher's ID is there, so the publisher's own rows grade nothing;
 - publisher: those rows must still be Member appearances exactly when a term covers the date (and not at the
   person's own nomination), matched to that ID;
 - retyped: each other Member appearance must name, by one of the readings, the Member it is matched to, who must
   hold a term on the date that agrees with a state or chamber the row states, be the only sitting Member it names,
   not be the hearing's own nominee, and the row must state a congressional office, role or seat, or be at a Member
   Day hearing, with no former, state-legislature or outside employer words; a flag names the Member(s) named.
   A name alone at a Member Day hearing that also hears outside witnesses is flagged for reading: nothing in the
   row tells a Member from an outside witness who shares the name, and this check cannot either;
 - left: each shown row that is not one, has a date, states a congressional office or seat in a field or is a name
   alone at a Member Day hearing that hears no outside witness, has no such words, and names exactly one sitting
   Member, is flagged as left a witness.
Rows not read are counted by reason (no name, record entries, no hearing date, superseded rows for the 'left' side).
With --plant the ten planted wrong values below are laid over the decisions (one also renames its row) and each must
raise a flag the baseline does not have (tests/test_member_appearances_raw_check.py plants the same kinds on hand rows).
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import unicodedata

import duckdb

HONORIFICS = set('mr mrs ms miss dr hon honorable the rev sen senator rep representative congressman congresswoman '
                 'chairman chairwoman jr sr ii iii iv md phd esq page delegate resident commissioner'.split())
STATE_CODES = {'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA', 'colorado': 'CO',
               'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID',
               'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA',
               'maine': 'ME', 'maryland': 'MD', 'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN',
               'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
               'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC',
               'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA',
               'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX',
               'utah': 'UT', 'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV',
               'wisconsin': 'WI', 'wyoming': 'WY', 'guam': 'GU', 'puerto rico': 'PR', 'district of columbia': 'DC',
               'american samoa': 'AS', 'virgin islands': 'VI', 'northern mariana islands': 'MP'}
OFFICE = re.compile(r'\bsenator\b|representative in congress|\bu\.?\s?s\.? (house|representative)|member of congress'
                    r'|congress(wo)?man|\bdelegate (from|to|in|of)\b|resident commissioner|house of representatives\b'
                    r'|united states senate|\(\w\w-(\d+|at large|al)\)|^rep\.?$|^representative$')
ROLE = re.compile(r'\b(chair\w*|ranking member|co-chair\w*|vice chair\w*)\b.*\b(committee|subcommittee|caucus|conference)\b'
                  r'|\b(majority|minority|democratic|republican) (leader|whip)\b|\bspeaker of the house\b')
# A field that opens with the person's own nomination; a Senator 'presenting ... a Nominee' is not one.
OWN_NOMINEE = re.compile(r'(^|\|)\s*(nominee\b|nominated\b|to be\b|of [a-z .]+, to be\b)')
OUTSIDE = re.compile(r'\b(former|retired|designate|state (senator|representative|senate|house|legislature)'
                     r'|legislature|general assembly|association|inc|llc|university|college|corporation|company|foundation'
                     r'|institute|council|county|city of|clerk|parliamentarian|staff\w*|counsel|of the senate)\b'
                     r'|\b(19|20)\d\d\s*[-–]\s*(19|20)\d\d\b|representative (of|for|to) ')
SENATE_WORDS = re.compile(r'\bsenator\b|\bsenate\b')
HOUSE_WORDS = re.compile(r'representative|congress(wo)?man|\bdelegate\b|resident commissioner|\bhouse\b|\(\w\w-(\d+|al|at large)\)|^rep\.?$')
STATE_PHRASE = re.compile(r'\b(?:from|of)\s+(?:the\s+)?(?:(?:state|commonwealth|territory)\s+of\s+)?('
                          + '|'.join(sorted(STATE_CODES, key=len, reverse=True)) + r')\b')
CODE_PHRASE = re.compile(r'\(([A-Z]{2})-(?:\d+|AL|At[- ]Large)\)|\b[DRI]-([A-Z]{2})\b')
STATE_NAMES = '|'.join(sorted(STATE_CODES, key=len, reverse=True))
TERRITORIES = {'GU', 'PR', 'DC', 'AS', 'VI', 'MP'}
NUMBER = r'(\d+)(?:st|nd|rd|th|d)?\s+(?:congressional\s+)?district'
SEATS = (  # (pattern, which group is the state, which the district); district None means at large or a territory
    (re.compile(r'\(([a-z]{2})[- ](\d+|al|at[- ]large)\)'), 1, 2),
    (re.compile(NUMBER + r'\W{0,3}(?:of\s+)?(?:the\s+)?(?:state\s+of\s+)?(' + STATE_NAMES + r')\b'), 2, 1),
    (re.compile(r'\b(' + STATE_NAMES + r")(?:'s)?\W{0,3}" + NUMBER), 1, 2),
    (re.compile(NUMBER + r'\W{0,3}([a-z]{2})\s*(?:$|\|)'), 2, 1),
    (re.compile(r'\b(' + STATE_NAMES + r'),?\s+district\s+(\d+)\b'), 1, 2),
    (re.compile(r'\b(?:delegate|resident commissioner)\b[^|]*?\b(?:from|of|for)\s+(?:the\s+)?(?:(?:territory|commonwealth)\s+of\s+)?('
                + STATE_NAMES + r')\b'), 1, 'territory'),
    (re.compile(r'\b(' + STATE_NAMES + r')\b[^|]*\bat[- ]large\b'), 1, None),
)
MEMBER_DAY = re.compile(r"\bmembers?['\u2019]?s?\s+day\b")
FORMER_MEMBERS_DAY = re.compile(r"\bformer\s+members?['\u2019]?s?\s+day\b")

# The planted wrong values (reviews of c98dab56 and d8e1b039): release witness keys and the value laid over them.
PLANTS = {
    'member left a witness (Silvestre Reyes 2007)': ('5fc16a144de708d2', None),
    'outside witness retyped (Timothy V. Johnson, Corning)': ('6498602416854ede', 'J000177'),
    'nominee retyped (Mike Pompeo, CIA nomination)': ('3b96984ca30e4cc4', 'P000602'),
    'former Member retyped (Ben Nighthorse Campbell 2017)': ('76f6fc3772eafc1a', 'C000077'),
    'ambiguous name resolved (French J. Hill to Katie Hill)': ('98d539f7169ccf98', 'H001087'),
    'wrong one of two (Sander Levin to Carl Levin)': ('3c12eb0487bc421a', 'L000261'),
    'Member Day row naming only the Member left a witness (Dan Newhouse 2019)': ('0ad4c582d03b9bf2', None),
    'Member Day row stating only a seat left a witness (John R. Curtis, Utah, 3d District 2019)': ('79b0d948ee489e5a', None),
    'wrong one of two on a seat row (Mike Rogers, 3rd District, Alabama, to Mike Rogers of Michigan)': ('054887fc0e814102', 'R000572'),
    # An outside witness listed by name alone at a Member Day hearing that also hears outside witnesses (Michael Stern,
    # 2026-03-17), renamed to share a sitting Member's name and retyped as that Member.
    "outside witness sharing a sitting Member's name at a Member Day hearing, retyped (renamed Mike Johnson)":
        ('b0d3c472068029ec', 'J000299', dict(name='Mr. Mike Johnson')),
}


def fold(text):
    return unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()


def words(text):
    text = re.sub(r"['\u2019`]", '', re.sub(r'\([^)]*\)', ' ', (text or '').lower()))
    text = fold(text).split(',')[0]
    found = [w for w in re.split(r'[^a-z]+', text) if w and w not in HONORIFICS]
    while len(found) > 2 and len(found[-1]) == 1:  # credentials split into letters: 'M.D.'
        found.pop()
    return found


def first_names_agree(row_words, member_words, abbreviations=()):
    for a in row_words:
        for b in member_words:
            if a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a))):
                return True
        for abbr in abbreviations:
            if a[0] == abbr[0] and re.fullmatch('.*'.join(abbr) + '.*', a):
                return True
    return False


class Reference:
    """The members data as this check reads it: names, terms, family-name index and House seat holders."""

    def __init__(self, con, members, terms):
        self.names = {}
        for b, first, last, nick, others in con.execute(
                f"select bioguide_id,name_first,name_last,name_nickname,other_names from read_parquet('{members}')").fetchall():
            given = set(words(re.sub(r'[()]', ' ', first or ''))) | set(words(nick or ''))
            family = set(words(last or ''))
            abbreviations = {fold(first).strip('. ')} if re.fullmatch(r'\s*[A-Za-z]{2,4}\.\s*', first or '') else set()
            for other in others or []:
                given |= set(words(other.get('first') or '')) | set(words(other.get('nickname') or ''))
                family |= set(words(other.get('last') or ''))
            self.names[b] = (given, family, abbreviations)
        self.spans, self.holders = defaultdict(list), defaultdict(list)
        for b, kind, state, district, start, end in con.execute(
                f"select bioguide_id,term_type,term_state,term_district,term_start,term_end from read_parquet('{terms}')").fetchall():
            if start and end:
                chamber = 'senate' if (kind or '').lower().startswith('sen') else 'house'
                self.spans[b].append((chamber, state, start[:10], end[:10]))
                if chamber == 'house' and str(district or '').lstrip('-').isdigit() and int(district) >= 0:
                    self.holders[(state, int(district))].append(b)
        self.by_family = defaultdict(set)
        for b, (_given, family, _abbr) in self.names.items():
            for w in family:
                self.by_family[w].add(b)

    def sitting(self, bioguide, days):
        return [t for t in self.spans.get(bioguide, ()) if any(t[2] <= d <= t[3] for d in days)]

    def readings(self, row):
        """{bioguide: reading} for the sitting Members the row names, within the state and chamber it states."""
        w, days = words(row['name']), (row['dates'] or '').split(',')
        states, chambers = stated(row)
        def placed(b):
            terms = self.sitting(b, days)
            return terms and (not states or states & {t[1] for t in terms}) and (
                not chambers or chambers & {t[0] for t in terms})
        found = {}
        if len(w) >= 2:
            for b in self.by_family.get(w[-1], ()):
                if first_names_agree(w[:-1], *self.names[b][0::2]) and placed(b):
                    found[b] = 'name'
        heard = set(w) | set(words(((row['fields'] or '').split('|') + [''])[0]))
        for state, district in seats(row):
            for b in self.holders.get((state, district), ()):
                if b not in found and heard & self.names[b][1] and placed(b):
                    found[b] = 'seat'
        if not found and len(w) >= 2 and states:
            initials = {g[0] for g in w[:-1]}
            pool = [b for b in self.by_family.get(w[-1], ()) if placed(b) and initials & {g[0] for g in self.names[b][0]}]
            if len(pool) == 1 and any(g[0] == m[0] and min(len(g), len(m)) == 1 for g in w[:-1] for m in self.names[pool[0]][0]):
                found[pool[0]] = 'initial'
        return found


ROW_KEYS = ('witness_key', 'source', 'name', 'publisher_id', 'person', 'fields', 'dates', 'title', 'shown', 'record_entry',
            'retyped', 'matched', 'basis', 'occasion')


def read_rows(con, witnesses, decisions, meetings, prints):
    overlay = ''
    if decisions:
        overlay = f"""left join (select witness_key,outcome,matched_bioguide_id as decided_id,match_basis as decided_basis
            from read_parquet('{decisions}')) d using(witness_key)"""
    prints_join = (f"left join (select package_id,held_dates,title as print_title from read_parquet('{prints}')) p using(package_id)"
                   if prints else '')
    held = "array_to_string(p.held_dates,',')" if prints else 'NULL'
    title = 'coalesce(m.title,p.print_title)' if prints else 'm.title'
    member = ("d.outcome='member'" if decisions else "w.witness_type='member_appearance'")
    matched = ("d.decided_id" if decisions else "w.matched_bioguide_id")
    basis = ("d.decided_basis" if decisions else "w.match_basis")
    rows = con.execute(f"""select w.witness_key,w.source,w.name,w.bioguide_id,coalesce(w.superseded_by,w.witness_key) as person,
          concat_ws(' | ',w.position,w.organization,w.on_behalf_of,w.location) as fields,
          coalesce(cast(m.meeting_date as varchar),{held}) as dates,{title} as title,w.superseded_by is null as shown,
          coalesce(w.witness_type,'') in ('statement_for_record','member_statement','record_material') as record_entry,
          coalesce({member},false) as retyped,{matched} as matched,{basis} as basis,
          coalesce(cast(w.event_id as varchar),w.package_id,w.witness_key) as occasion
        from read_parquet('{witnesses}') w left join read_parquet('{meetings}') m using(event_id) {prints_join} {overlay}""").fetchall()
    return {r[0]: dict(zip(ROW_KEYS, r)) for r in rows}


def seats(row):
    """The House seats the row states, as (state, district): 0 for a state at large or a territory's Delegate."""
    text, found = fold((row['name'] or '') + ' | ' + (row['fields'] or '')), set()
    for pattern, state_group, district_group in SEATS:
        for m in pattern.finditer(text):
            state = m.group(state_group)
            state = STATE_CODES.get(state) or (state.upper() if state.upper() in STATE_CODES.values() else None)
            if state is None or (district_group == 'territory' and state not in TERRITORIES):
                continue
            district = m.group(district_group) if isinstance(district_group, int) else '0'
            found.add((state, int(district) if district.isdigit() else 0))
    return found


def stated(row):
    text = fold(row['fields'])
    states = {STATE_CODES[m] for m in STATE_PHRASE.findall(text)}
    states |= {STATE_CODES[f.strip(' .,;:')] for f in text.split('|') if f.strip(' .,;:') in STATE_CODES}
    states |= {a or b for a, b in CODE_PHRASE.findall(row['fields'] or '')}
    states |= {state for state, _district in seats(row)}
    chambers = set()
    if SENATE_WORDS.search(text):
        chambers.add('senate')
    if any(HOUSE_WORDS.search(field.strip()) for field in text.split('|')):
        chambers.add('house')
    return states, chambers


def own_nomination(row):
    if OWN_NOMINEE.search(fold(row['fields'])):
        return True
    title = ' ' + ' '.join(re.split(r'[^a-z]+', fold(row['title']))) + ' '
    w = words(row['name'])
    return 'nominat' in title and len(w) >= 2 and f' {w[-1]} ' in title and any(f' {g} ' in title for g in w[:-1])


def member_day(row):
    title = fold(row['title'])
    return bool(MEMBER_DAY.search(title)) and not FORMER_MEMBERS_DAY.search(title)


def read_words(rows, ref):
    """Each row's own words, read once (judge runs again for every plant): the Members it names, its office, places."""
    for row in rows.values():
        if 'found' in row:
            continue
        text = fold(row['fields'])
        states, chambers = stated(row)
        row.update(found=ref.readings(row) if row['name'] and row['dates'] else {}, states=states, chambers=chambers,
                   office=bool(OFFICE.search(text) or ROLE.search(text) or chambers or seats(row)),
                   office_field=any(OFFICE.search(f.strip()) for f in text.split('|')) or bool(seats(row)),
                   member_day=member_day(row), outside=bool(OUTSIDE.search(text)), nominee=own_nomination(row))


def judge(rows, decided, ref):
    flags, publisher, not_read = {}, Counter(), Counter()
    read_words(rows, ref)
    # One appearance stated by several publishers (superseded_by): an office any of its rows states counts for all.
    office_groups = {r['person'] for r in rows.values() if r['office']}
    # Hearings that also hear outside witnesses: a named row with fields that names no sitting Member.
    outside_heard = {r['occasion'] for r in rows.values()
                     if r['name'] and r['fields'] and not r['record_entry'] and not r['found'] and not r['retyped']}
    for key, row in rows.items():
        if row['name'] is None:
            not_read['no name'] += 1; continue
        if row['record_entry']:
            not_read['record entry'] += 1; continue
        if not row['dates']:
            not_read['no hearing date'] += 1; continue
        retyped, matched = decided.get(key, (False, None))
        days = row['dates'].split(',')
        if row['publisher_id'] in ref.names:  # the publisher's own label, both directions
            expected = bool(ref.sitting(row['publisher_id'], days)) and not row['nominee']
            publisher[(expected, retyped)] += 1
            if expected != retyped:
                flags[key] = 'publisher id ' + ('in office, left a witness' if expected else 'not in office or nominee, retyped')
            elif retyped and matched != row['publisher_id']:
                flags[key] = f'publisher id {row["publisher_id"]}, matched {matched}'
            continue
        found = row['found']
        named = 'names ' + ','.join(sorted(found)) if found else 'names no sitting Member'
        if retyped:
            why = []
            w = words(row['name'])
            given, family, abbreviations = ref.names.get(matched, (set(), set(), set()))
            if not ref.sitting(matched, days):
                why.append('no term covers the date')
            if matched not in found and not why:
                if not w or w[-1] not in family:
                    why.append('family name differs')
                elif not first_names_agree(w[:-1], given, abbreviations):
                    why.append('first name differs')
                else:
                    why.append('stated state or chamber is not the term')
            if len(found) > 1:
                why.append('more than one sitting Member fits')
            if row['nominee']:
                why.append("the hearing's own nominee")
            if row['outside']:
                why.append('former, state legislature or outside words')
            if not (row['office'] or row['states'] or row['member_day'] or row['person'] in office_groups):
                why.append('no congressional office stated')
            if row['member_day'] and not row['fields'] and row['occasion'] in outside_heard:
                why.append('a name alone at a Member Day hearing that also hears outside witnesses')
            if why:
                flags[key] = f'retyped: {"; ".join(why)} ({named}; matched {matched})'
        elif row['shown'] and (row['office_field'] or (row['member_day'] and row['occasion'] not in outside_heard)) \
                and not row['outside'] and not row['nominee'] and len(found) == 1:
            flags[key] = 'left a witness: names sitting ' + next(iter(found))
    not_read['superseded rows (not judged as left)'] = sum(1 for r in rows.values() if not r['shown'] and not r['retyped'])
    return flags, publisher, not_read


def cross_publisher(rows, decided, ref):
    """Grade the rule's own reading of other publishers' rows against the house_xml Bioguide ID of the same appearance."""
    labels, unlabelled = defaultdict(set), defaultdict(set)
    for row in rows.values():
        if row['publisher_id'] and row['name'] and row['dates'] and not row['record_entry']:
            sitting = row['publisher_id'] in ref.names and ref.sitting(row['publisher_id'], row['dates'].split(','))
            (labels if sitting and not row['nominee'] else unlabelled)[row['person']].add(row['publisher_id'])
    grade, examples, appearances = Counter(), defaultdict(list), labels.keys() | unlabelled.keys()
    for key, row in rows.items():
        if row['publisher_id'] or not row['name'] or row['record_entry'] or row['person'] not in appearances:
            continue
        retyped, matched = decided.get(key, (False, None))
        own = retyped and row['basis'] not in ('group', 'publisher_id')
        if row['person'] in labels:
            label = labels[row['person']]
            kind = ('two publisher IDs' if len(label) > 1 else 'same Member' if own and matched in label
                    else 'DIFFERENT Member' if own else 'silent: matched only through the appearance' if retyped
                    else 'left a witness with its appearance')
            grade[(row['source'], kind)] += 1
        elif own:
            kind = 'matched where the publisher ID is not a Member sitting on the date'
            grade[(row['source'], kind)] += 1
        else:
            continue
        if kind != 'same Member':
            examples[kind].append(dict(witness_key=key, source=row['source'], name=row['name'], fields=row['fields'],
                                       publisher_id=','.join(sorted(labels.get(row['person']) or unlabelled[row['person']])),
                                       matched=matched, basis=row['basis']))
    return dict(labelled_appearances=len(labels), grades={f'{s}: {k}': n for (s, k), n in sorted(grade.items())},
                totals=dict(Counter(k for (_s, k) in grade.elements())), examples=dict(examples))


def plant_results(rows, decided, baseline, plants, ref):
    """Lay each planted value over the decisions; it is caught when its row gets a flag the baseline lacks."""
    results = {}
    for label, (key, value, *renamed) in plants.items():
        if key not in rows:
            results[label] = 'not in these rows'; continue
        planted = dict(decided)
        planted[key] = (value is not None, value)
        planted_rows = rows
        if renamed:  # a fresh row: its words are read again
            planted_rows = dict(rows)
            planted_rows[key] = {k: v for k, v in rows[key].items() if k in ROW_KEYS} | renamed[0]
        got, _publisher, _not_read = judge(planted_rows, planted, ref)
        results[label] = ('caught: ' + got[key]) if got.get(key) and got.get(key) != baseline.get(key) else 'MISSED'
    return results


def run(args):
    con = duckdb.connect()
    ref = Reference(con, args.members, args.terms)
    rows = read_rows(con, args.witnesses, args.decisions, args.meetings, args.prints)
    decided = {k: (r['retyped'], r['matched']) for k, r in rows.items()}
    flags, publisher, not_read = judge(rows, decided, ref)  # reads every row's words first
    out = dict(rows=len(rows), retyped=sum(1 for r in rows.values() if r['retyped']),
               retyped_shown=sum(1 for r in rows.values() if r['retyped'] and r['shown']),
               cross_publisher=cross_publisher(rows, decided, ref),
               publisher_rows={f'expected {"member" if e else "witness"}, published {"member" if p else "witness"}': n
                               for (e, p), n in sorted(publisher.items())},
               flags=Counter(v.split(':')[0] for v in flags.values()), not_read=dict(not_read),
               flagged=[dict(witness_key=k, flag=v, name=rows[k]['name'], fields=rows[k]['fields'], dates=rows[k]['dates'])
                        for k, v in sorted(flags.items(), key=lambda x: x[1])])
    if args.plant:
        out['plants'] = plant_results(rows, decided, flags, PLANTS, ref)
    Path(args.output).write_text(json.dumps(out, indent=1, default=str))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    for name in ('witnesses', 'members', 'terms', 'meetings', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--decisions'); parser.add_argument('--prints'); parser.add_argument('--plant', action='store_true')
    out = run(parser.parse_args(argv))
    print(json.dumps({k: v for k, v in out.items() if k not in ('flagged',)}, indent=1, default=str))


if __name__ == '__main__':
    main()

"""Judge which witness rows are sitting Members of Congress acting officially (ct-kw85) with a reading of its own.

    member_appearances_raw_check.py --witnesses witnesses.parquet [--decisions witness_members.parquet]
        --members members.parquet --terms member_terms.parquet --meetings meetings.parquet
        [--prints prints.parquet] [--plant] --output OUT.json

The rows under test are a release's witnesses (witness_type member_appearance, matched_bioguide_id), or a release's
witnesses with an engine run's decisions laid over them (--decisions: witness_key, outcome, matched_bioguide_id).
Members come from the spicy-regs members table itself (name_first, name_last, name_nickname and other_names, which
the rule does not read) and its member_terms; hearing dates and titles from the release's meetings and, for prints
without a meeting, a prints table (package_id, held_dates, title) read from the raw MODS.

Everything here is this check's own reading: names are folded with Unicode NFKD and split on anything not a letter;
a first name agrees when one word starts with the other (three letters at least), or spells out an abbreviated one
('William' for 'Wm.', its letters in order); offices, states and outside words are its own short lists. It judges in
both directions and from one independent fact first:
 - publisher: every row whose publisher states a Bioguide ID of a known Member is a labelled example: a Member
   appearance exactly when one of that Member's terms covers the hearing date (and not when the hearing is that
   person's own nomination);
 - retyped: each other row published as a Member appearance must name, by family and first name, the Member it is
   matched to, who must hold a term on the date that agrees with a state or chamber the row states, be the only
   sitting Member who fits, not be the hearing's own nominee, and the row must state some congressional office or
   role and no former, state-legislature or outside employer words;
 - left: each shown row that is not one, has a date, states a congressional office and no such words, and names
   exactly one sitting Member who fits, is flagged as a Member left a witness.
Rows not read are counted by reason (no name, record entries, no hearing date, superseded rows for the 'left' side).
With --plant the six planted wrong values below are laid over the decisions and each must raise a flag the baseline
does not have (tests/test_member_appearances_raw_check.py plants the same six kinds on hand rows).
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
                     r'|institute|council|county|city of|clerk|staff\w*|counsel|of the senate)\b'
                     r'|\b(19|20)\d\d\s*[-–]\s*(19|20)\d\d\b|representative (of|for|to) ')
SENATE_WORDS = re.compile(r'\bsenator\b|\bsenate\b')
HOUSE_WORDS = re.compile(r'representative|congress(wo)?man|\bdelegate\b|resident commissioner|\bhouse\b|\(\w\w-(\d+|al|at large)\)|^rep\.?$')
STATE_PHRASE = re.compile(r'\b(?:from|of)\s+(?:the\s+)?(?:(?:state|commonwealth|territory)\s+of\s+)?('
                          + '|'.join(sorted(STATE_CODES, key=len, reverse=True)) + r')\b')
CODE_PHRASE = re.compile(r'\(([A-Z]{2})-(?:\d+|AL|At[- ]Large)\)|\b[DRI]-([A-Z]{2})\b')

# The six planted wrong values (review of c98dab56, mar-plant.py): release witness keys and the value laid over them.
PLANTS = {
    'member left a witness (Silvestre Reyes 2007)': ('5fc16a144de708d2', None),
    'outside witness retyped (Timothy V. Johnson, Corning)': ('6498602416854ede', 'J000177'),
    'nominee retyped (Mike Pompeo, CIA nomination)': ('3b96984ca30e4cc4', 'P000602'),
    'former Member retyped (Ben Nighthorse Campbell 2017)': ('76f6fc3772eafc1a', 'C000077'),
    'ambiguous name resolved (French J. Hill to Katie Hill)': ('98d539f7169ccf98', 'H001087'),
    'wrong one of two (Sander Levin to Carl Levin)': ('3c12eb0487bc421a', 'L000261'),
}


def fold(text):
    return unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()


def words(text):
    text = re.sub(r'\([^)]*\)', ' ', fold(text)).split(',')[0]
    return [w for w in re.split(r'[^a-z]+', text) if w and w not in HONORIFICS]


def first_names_agree(row_words, member_words, abbreviations=()):
    for a in row_words:
        for b in member_words:
            if a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a))):
                return True
        for abbr in abbreviations:
            if a[0] == abbr[0] and re.fullmatch('.*'.join(abbr) + '.*', a):
                return True
    return False


def load_members(con, members, terms):
    names = {}
    for b, first, last, nick, others in con.execute(
            f"select bioguide_id,name_first,name_last,name_nickname,other_names from read_parquet('{members}')").fetchall():
        given = set(words(re.sub(r'[()]', ' ', first or ''))) | set(words(nick or ''))
        family = set(words(last or ''))
        abbreviations = {fold(first).strip('. ')} if re.fullmatch(r'\s*[A-Za-z]{2,4}\.\s*', first or '') else set()
        for other in others or []:
            given |= set(words(other.get('first') or '')) | set(words(other.get('nickname') or ''))
            family |= set(words(other.get('last') or ''))
        names[b] = (given, family, abbreviations)
    spans = defaultdict(list)
    for b, kind, state, start, end in con.execute(
            f"select bioguide_id,term_type,term_state,term_start,term_end from read_parquet('{terms}')").fetchall():
        if start and end:
            spans[b].append(('senate' if (kind or '').lower().startswith('sen') else 'house', state, start[:10], end[:10]))
    by_family = defaultdict(set)
    for b, (_given, family, _abbr) in names.items():
        for w in family:
            by_family[w].add(b)
    return names, spans, by_family


def read_rows(con, witnesses, decisions, meetings, prints):
    overlay = ''
    if decisions:
        overlay = f"""left join (select witness_key,outcome,matched_bioguide_id as decided_id from read_parquet('{decisions}')) d using(witness_key)"""
    prints_join = (f"left join (select package_id,held_dates,title as print_title from read_parquet('{prints}')) p using(package_id)"
                   if prints else '')
    held = "array_to_string(p.held_dates,',')" if prints else 'NULL'
    title = 'coalesce(m.title,p.print_title)' if prints else 'm.title'
    member = ("d.outcome='member'" if decisions else "w.witness_type='member_appearance'")
    matched = ("d.decided_id" if decisions else "w.matched_bioguide_id")
    rows = con.execute(f"""select w.witness_key,w.source,w.name,w.bioguide_id,
          concat_ws(' | ',w.position,w.organization,w.on_behalf_of,w.location) as fields,
          coalesce(cast(m.meeting_date as varchar),{held}) as dates,{title} as title,w.superseded_by is null as shown,
          coalesce(w.witness_type,'') in ('statement_for_record','member_statement','record_material') as record_entry,
          coalesce({member},false) as retyped,{matched} as matched
        from read_parquet('{witnesses}') w left join read_parquet('{meetings}') m using(event_id) {prints_join} {overlay}""").fetchall()
    keys = ('witness_key', 'source', 'name', 'publisher_id', 'fields', 'dates', 'title', 'shown', 'record_entry', 'retyped', 'matched')
    return {r[0]: dict(zip(keys, r)) for r in rows}


def stated(row):
    text = fold(row['fields'])
    states = {STATE_CODES[m] for m in STATE_PHRASE.findall(text)}
    states |= {a or b for a, b in CODE_PHRASE.findall(row['fields'] or '')}
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


def sitting(spans, bioguide, days):
    return [t for t in spans.get(bioguide, ()) if any(t[2] <= d <= t[3] for d in days)]


def fits(row, names, spans, by_family):
    """Members sitting on the date whom the row's name and stated state and chamber fit."""
    w, days = words(row['name']), (row['dates'] or '').split(',')
    if len(w) < 2:
        return []
    states, chambers = stated(row)
    found = []
    for b in by_family.get(w[-1], ()):
        given, _family, abbreviations = names[b]
        terms = sitting(spans, b, days)
        if not terms or not first_names_agree(w[:-1], given, abbreviations):
            continue
        if states and not states & {t[1] for t in terms}:
            continue
        if chambers and not chambers & {t[0] for t in terms}:
            continue
        found.append(b)
    return found


def judge(rows, decided, names, spans, by_family):
    flags, publisher, not_read = {}, Counter(), Counter()
    for key, row in rows.items():
        if row['name'] is None:
            not_read['no name'] += 1; continue
        if row['record_entry']:
            not_read['record entry'] += 1; continue
        if not row['dates']:
            not_read['no hearing date'] += 1; continue
        retyped, matched = decided.get(key, (False, None))
        days = row['dates'].split(',')
        text = fold(row['fields'])
        if row['publisher_id'] in names:  # the publisher's own label, both directions
            expected = bool(sitting(spans, row['publisher_id'], days)) and not own_nomination(row)
            publisher[(expected, retyped)] += 1
            if expected != retyped:
                flags[key] = 'publisher id ' + ('in office, left a witness' if expected else 'not in office or nominee, retyped')
            elif retyped and matched != row['publisher_id']:
                flags[key] = f'publisher id {row["publisher_id"]}, matched {matched}'
            continue
        if retyped:
            why = []
            w = words(row['name'])
            given, family, abbreviations = names.get(matched, (set(), set(), set()))
            if not w or w[-1] not in family:
                why.append('family name differs')
            elif not first_names_agree(w[:-1], given, abbreviations):
                why.append('first name differs')
            if not sitting(spans, matched, days):
                why.append('no term covers the date')
            candidates = fits(row, names, spans, by_family)
            if matched not in candidates and not why:
                why.append('stated state or chamber is not the term')
            if len(candidates) > 1:
                why.append('more than one sitting Member fits: ' + ','.join(sorted(candidates)))
            if own_nomination(row):
                why.append("the hearing's own nominee")
            if OUTSIDE.search(text):
                why.append('former, state legislature or outside words')
            states, chambers = stated(row)
            if not (OFFICE.search(text) or ROLE.search(text) or states or chambers):
                why.append('no congressional office stated')
            if why:
                flags[key] = 'retyped: ' + '; '.join(why)
        elif row['shown'] and any(OFFICE.search(f.strip()) for f in text.split('|')) and not OUTSIDE.search(text) \
                and not own_nomination(row):
            candidates = fits(row, names, spans, by_family)
            if len(candidates) == 1:
                flags[key] = 'left a witness: names sitting ' + candidates[0]
    not_read['superseded rows (not judged as left)'] = sum(1 for r in rows.values() if not r['shown'] and not r['retyped'])
    return flags, publisher, not_read


def plant_results(rows, decided, baseline, plants, names, spans, by_family):
    """Lay each planted value over the decisions; it is caught when its row gets a flag the baseline lacks."""
    results = {}
    for label, (key, value) in plants.items():
        if key not in rows:
            results[label] = 'not in these rows'; continue
        planted = dict(decided)
        planted[key] = (value is not None, value)
        got, _publisher, _not_read = judge(rows, planted, names, spans, by_family)
        results[label] = ('caught: ' + got[key]) if got.get(key) and got.get(key) != baseline.get(key) else 'MISSED'
    return results


def run(args):
    con = duckdb.connect()
    names, spans, by_family = load_members(con, args.members, args.terms)
    rows = read_rows(con, args.witnesses, args.decisions, args.meetings, args.prints)
    decided = {k: (r['retyped'], r['matched']) for k, r in rows.items()}
    flags, publisher, not_read = judge(rows, decided, names, spans, by_family)
    out = dict(rows=len(rows), retyped=sum(1 for r in rows.values() if r['retyped']),
               retyped_shown=sum(1 for r in rows.values() if r['retyped'] and r['shown']),
               publisher_examples={f'expected {"member" if e else "witness"}, published {"member" if p else "witness"}': n
                                   for (e, p), n in sorted(publisher.items())},
               flags=Counter(v.split(':')[0] for v in flags.values()), not_read=dict(not_read),
               flagged=[dict(witness_key=k, flag=v, name=rows[k]['name'], fields=rows[k]['fields'], dates=rows[k]['dates'])
                        for k, v in sorted(flags.items(), key=lambda x: x[1])])
    if args.plant:
        out['plants'] = plant_results(rows, decided, flags, PLANTS, names, spans, by_family)
    Path(args.output).write_text(json.dumps(out, indent=1, default=str))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    for name in ('witnesses', 'members', 'terms', 'meetings', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--decisions'); parser.add_argument('--prints'); parser.add_argument('--plant', action='store_true')
    out = run(parser.parse_args(argv))
    print(json.dumps({k: v for k, v in out.items() if k != 'flagged'}, indent=1, default=str))


if __name__ == '__main__':
    main()

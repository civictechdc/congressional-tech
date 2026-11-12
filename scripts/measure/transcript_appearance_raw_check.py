"""Judge who appeared at a hearing (ct-sfra) from the print's own transcript with a reading of its own.

    transcript_appearance_raw_check.py --witnesses witnesses.parquet [--before witnesses.parquet]
        --captures captures.parquet --bodies DIR [--plant] --output OUT.json

The rows under test are a run's MODS witness rows (witness_key, source, package_id, name, position, organization,
on_behalf_of, location, witness_type, matched_bioguide_id); --before gives the same rows from the run before, so a
row the rule turned from a record entry into a witness is known. The transcript is the GovInfo HTML of the print
(captures: context_url ending /html/CHRG-....htm, sha256 and stored_sha256; bodies: <dir>/<sha[:2]>/<sha>.gz).

The rule reads the transcript's testimony headings and its roster page. This check reads neither. It reads two other
facts of the same print, in its own words:
 - speaker turns: a paragraph opening with a title and a family name and a period ('    Senator Gorton.',
   '    Mr. McCOLLUM.', '    Ms. Abbott.'): the person spoke at the hearing;
 - the members present: the convening paragraph's 'Members present: Representatives Thompson, Goodlatte, ...' or
   'Present: Senators Inhofe, Smith, ...' (not 'Also present' or 'Staff present'): the committee members at the
   hearing.
It judges both directions, over every named MODS row of a print with a transcript that is typed member_statement or
statement_for_record, that a Member matched (matched_bioguide_id), or whose type differs from --before:
 - statement_spoke         member_statement, and the Member spoke but is not among the members present: a Member who
                           testified, typed a statement;
 - appearance_silent       member_appearance, and the Member never spoke (a lead: the check cannot see a Member at the
                           table who said nothing);
 - committee_appearance    member_appearance, among the members present, and the row's own words name a statement or an
                           opening (a committee member's own statement taken for testimony);
 - entry_spoke             statement_for_record, and the person spoke (an answerer or record entry who testified);
 - promoted_silent         a witness now, statement_for_record before, and the person never spoke.
Agreements are counted by type. Rows not read are counted by reason: no transcript held, a body that cannot be read,
no family name. What this cannot see: a person at the table who never spoke, two people of one family name at one
hearing (turns rarely print a first name), unusual speaker labels ('The Chairman.', 'Voice.'), and a committee
member the print does not list as present.
With --plant four wrong values are laid, each on every row the rule's own output makes eligible (the run's types now
and before, the row's own words; never this check's facts), and the report gives each one's catch rate and names every
row it missed: a testifying Member typed member_statement (rows the run keeps a Member appearance whose words name a
statement; caught by statement_spoke); a submission typed witness (record entries in both runs; promoted_silent); an
answerer who testified typed statement_for_record (rows the run promoted; entry_spoke); a committee member's opening
taken for testimony (opening statements the run made Member statements; committee_appearance or appearance_silent).
"""
import argparse
from collections import Counter
import gzip
import html
import json
from pathlib import Path
import re
import unicodedata

import duckdb

TITLES = ('Senator|Representative|Congressman|Congresswoman|Delegate|Commissioner|Chairman|Chairwoman|Chair|'
          'Mr|Ms|Mrs|Miss|Dr|General|Admiral|Secretary|Judge|Governor|Mayor|Ambassador|Director|Reverend|Rev|Father|'
          'Captain|Colonel|Major|Sheriff|Chief|Professor|Justice|Dean')
TURN = re.compile(rf"(?m)^ {{2,8}}(?:{TITLES})\.?\s+(?:[A-Z][A-Za-z'’.-]*\s+){{0,2}}?(?P<family>(?:Mc|Mac|De|Van|O')?[A-Z][A-Za-z'’-]+)"
                  r"(?:\s+of\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)?(?:\s+\[[^\]]{1,30}\])?\.\s")
# 'Members present: ...' or 'Present: ...' to the sentence's end (a period closing the paragraph, or before 'Staff' or
# 'Also'), so 'G.K. Butterfield' is not cut at its initials; 'Also present' and 'Staff present' are not members.
PRESENT = re.compile(r"(?P<lead>\b[A-Za-z]+[ \t]+)?[Pp]resent:\s*(?P<names>.{0,2000}?)\.(?:[ \t]*\n\s{2,}|\s*$|\s+(?:Staff|Also)\b)",
                     re.S)
STATED = re.compile(r"(?i)\bstatements?\b|\bremarks\b")
SUFFIX = {'jr', 'sr', 'ii', 'iii', 'iv', 'md', 'phd'}
STATEMENT_TYPES = ('member_statement', 'statement_for_record')


def fold(text):
    return unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()


def family(name):
    """The check's own family word of a row's name: the last word that is not a suffix, nicknames dropped."""
    words = [w for w in re.findall(r"[a-z]+", re.sub(r"``[^']*''|\"[^\"]*\"|\([^)]*\)", ' ', fold(name).replace("'", '')))
             if w not in SUFFIX]
    return words[-1] if words else None


def read_text(shas, bodies):
    for sha in shas:
        path = Path(bodies) / sha[:2] / f'{sha}.gz'
        if path.exists():
            try:
                raw = gzip.decompress(path.read_bytes()).decode('utf-8', 'replace')
            except OSError:
                return 'unreadable'
            return html.unescape(re.sub(r'<[^>]+>', '', raw))
    return None


def transcript_facts(text):
    """(families who spoke, families among the members present) of one print's text."""
    spoke = {fold(m.group('family')).replace("'", '').replace('’', '') for m in TURN.finditer(text)}
    present = set()
    for m in PRESENT.finditer(text):
        if (m.group('lead') or '').strip().lower() in ('also', 'staff'):
            continue
        names = re.sub(r"\b(?:Senators?|Representatives?|Delegates?|Commissioners?|Chairman|Chairwoman|and|ex officio)\b",
                       ' ', re.sub(r"\([^)]*\)|\[[^\]]*\]", ' ', m.group('names')))
        for piece in re.split(r",|;", names):
            words = re.findall(r"[a-z]+", fold(piece).replace("'", ''))
            words = [w for w in words if w not in SUFFIX]
            if words and len(words) <= 3:
                present.add(words[-1])
    return spoke, present


def load(args):
    con = duckdb.connect()
    con.execute("set threads=2; set memory_limit='1GB'")
    cols = "witness_key,source,package_id,name,position,organization,on_behalf_of,location,witness_type,matched_bioguide_id"
    rows = {r[0]: dict(zip(cols.split(','), r)) for r in con.execute(
        f"select {cols} from read_parquet(?) where source='mods'", [str(args.witnesses)]).fetchall()}
    before = {}
    if args.before:
        before = dict(con.execute("select witness_key,witness_type from read_parquet(?) where source='mods'",
                                  [str(args.before)]).fetchall())
    for key, row in rows.items():
        row['before'] = before.get(key, row['witness_type'])
        row['words'] = ' | '.join(filter(None, (row['position'], row['organization'], row['on_behalf_of'], row['location'])))
    packages = sorted({r['package_id'] for r in rows.values() if r['package_id']})
    shas = {}
    for package, sha in con.execute(
            """select regexp_extract(context_url,'(CHRG-[0-9]+[hsj]hrg[0-9]+)[.]htm$',1) package,unnest([sha256,stored_sha256]) sha
               from read_parquet(?) where regexp_matches(context_url,'/html/CHRG-[0-9]+[hsj]hrg[0-9]+[.]htm$')
               and regexp_extract(context_url,'(CHRG-[0-9]+[hsj]hrg[0-9]+)[.]htm$',1) in (select unnest(?))""",
            [str(args.captures), packages]).fetchall():
        if sha:
            shas.setdefault(package, []).append(sha)
    return rows, shas


def in_scope(row):
    return bool(row['name']) and (row['witness_type'] in STATEMENT_TYPES or row['matched_bioguide_id'] is not None
                                  or row['witness_type'] != row['before'])


def judge(rows, facts):
    """Flags and agreements over the rows this check reads; rows it cannot read, by reason."""
    flags, agree, not_read = {}, Counter(), Counter()
    for key, row in sorted(rows.items()):
        if not in_scope(row):
            continue
        fact = facts.get(row['package_id'])
        if fact is None:
            not_read['no transcript held'] += 1; continue
        if fact == 'unreadable':
            not_read['transcript unreadable'] += 1; continue
        fam = family(row['name'])
        if not fam:
            not_read['no family name'] += 1; continue
        spoke, present = fact
        said, seated = fam in spoke, fam in present
        words = row['words']
        kind, flag = row['witness_type'], None
        if kind == 'member_statement' and said and not seated:
            flag = 'statement_spoke'
        elif kind == 'member_appearance' and seated and STATED.search(words or ''):
            flag = 'committee_appearance'
        elif kind == 'member_appearance' and not said:
            flag = 'appearance_silent'
        elif kind == 'statement_for_record' and said:
            flag = 'entry_spoke'
        elif kind is None and row['before'] == 'statement_for_record' and not said:
            flag = 'promoted_silent'
        if flag:
            flags[key] = dict(flag=flag, package=row['package_id'], name=row['name'], type=kind, before=row['before'],
                              spoke=said, present=seated, words=(words or '')[:120])
        else:
            agree[kind or 'witness'] += 1
    return flags, agree, not_read


# Plants come from the rule's side: the run's own types (now and --before) and the row's own words choose the rows, never
# this check's turns or members present, so a plant the check cannot see fails. Each is laid on every eligible row.
#   name: (flags that catch it, the rows it is laid on, the wrong value)
PLANTS = {
    'testifying member typed member_statement': (
        {'statement_spoke'},
        lambda r: r['witness_type'] == r['before'] == 'member_appearance' and STATED.search(r['words']),
        dict(witness_type='member_statement')),
    'submission typed witness': (
        {'promoted_silent'},
        lambda r: r['witness_type'] == r['before'] == 'statement_for_record',
        dict(witness_type=None)),
    'answerer who testified typed statement_for_record': (
        {'entry_spoke'},
        lambda r: r['before'] == 'statement_for_record' and r['witness_type'] in (None, 'member_appearance'),
        dict(witness_type='statement_for_record')),
    'committee member heading taken for testimony': (
        {'committee_appearance', 'appearance_silent'},
        lambda r: r['before'] == 'member_appearance' and r['witness_type'] == 'member_statement'
                  and re.search(r"(?i)\bopening statement", r['words']),
        dict(witness_type='member_appearance')),
}


def plant(rows, facts):
    """Each plant's catch rate over the rows it is laid on (every eligible row the check reads, flagged or not): a row it
    misses is one this check cannot judge wrong if the rule typed it so."""
    results = {}
    for name, (catching, eligible, wrong) in PLANTS.items():
        keys = [k for k, r in sorted(rows.items())
                if r['name'] and family(r['name']) and isinstance(facts.get(r['package_id']), tuple) and eligible(r)]
        flags, _, _ = judge({**rows, **{k: {**rows[k], **wrong} for k in keys}}, facts)
        missed = [k for k in keys if flags.get(k, {}).get('flag') not in catching]
        results[name] = dict(eligible=len(keys), caught=len(keys) - len(missed),
                             missed=[dict(key=k, name=rows[k]['name'], package=rows[k]['package_id']) for k in missed])
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--witnesses', type=Path, required=True)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--captures', type=Path, required=True)
    parser.add_argument('--bodies', type=Path, required=True)
    parser.add_argument('--plant', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    rows, shas = load(args)
    facts = {}
    for package in sorted({r['package_id'] for r in rows.values() if in_scope(r) and r['package_id']}):
        text = read_text(shas.get(package, []), args.bodies)
        facts[package] = text if text in (None, 'unreadable') else transcript_facts(text)
    flags, agree, not_read = judge(rows, facts)
    report = dict(rows=len(rows), read=sum(agree.values()) + len(flags), agree=dict(agree),
                  flags=dict(Counter(f['flag'] for f in flags.values())), not_read=dict(not_read),
                  transcripts_read=sum(isinstance(v, tuple) for v in facts.values()), flagged=flags)
    if args.plant:
        report['plants'] = plant(rows, facts)
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'flagged'}, sort_keys=True, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

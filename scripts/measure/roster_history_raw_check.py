"""Judge historical committee seats against a second publisher's raw roster for the same Congress (ct-8cno).

    roster_history_raw_check.py --seats ROSTERS.parquet|.json --congress 117
        [--house-memberdata MemberData.xml[.gz]] [--senate-cvc cvc_member_data.xml]
        [--legislators-yaml committee-membership-current.yaml] --output OUT.json

The seats under test (archive ``rosters`` shape: congress, system_code, bioguide_id, title; or SpicyRegs
``committee_assignments``, whose title is ``position``) come from
one publisher (for 113-118, the GovInfo Congressional Directory). Each independent file is another
publisher's own record, read here with ElementTree or YAML and nothing from the producer:

- House Clerk ``MemberData.xml`` (states its Congress; committees and subcommittees, leadership labels);
- Senate ``cvc_member_data.xml`` (states no Congress, only an update date; full committees only);
- ``unitedstates/congress-legislators`` ``committee-membership-current.yaml`` at a dated commit
  (both chambers, subcommittees, Chair/Ranking Member titles; scraped from the chamber sites).

Committees are compared by chamber letter plus the four-character committee/subcommittee suffix
(``hsag15`` and ``AG15`` and ``HSAG15`` are all ``h:ag15``), not by the producer's name matching or code
normalization. Per committee present in both, members are compared in both directions; chairs are
compared where both sides state one. The two files are different dates, so a mid-Congress change between
them shows as a disagreement: read the listed names, not only the rate. Committees present on one side
only are listed, never dropped. A planted wrong chair or seat must appear in ``chair_mismatches`` or
``seat_differences`` (tests/test_roster_history_raw_check.py).
"""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import xml.etree.ElementTree as ET

CHAIR = {'chair', 'chairman', 'chairwoman', 'chairperson'}


def key(code, chamber=None):
    """``h:ag15`` from a system or legislators code (hsag15, HSAG15, HSAG = full committee) or, with
    ``chamber``, a chamber file's bare comcode (AG15)."""
    code = code.strip().lower()
    if chamber:
        return f'{chamber}:{code}'
    return f'{code[0]}:{code[2:]}' + ('00' if len(code) == 4 else '')


def _open(path):
    data = Path(path).read_bytes()
    return gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data


def house_memberdata(path):
    root = ET.fromstring(_open(path))
    congress = int(root.findtext('title-info/congress-num'))
    seats, chairs = defaultdict(set), {}
    for member in root.iter('member'):
        bioguide = (member.findtext('member-info/bioguideID') or '').strip()
        if not bioguide:
            continue  # vacancy
        for item in member.iter():
            code = item.get('comcode') or item.get('subcomcode')
            if item.tag not in ('committee', 'subcommittee') or not code:
                continue
            k = key(code, 'h')
            seats[k].add(bioguide)
            if (item.get('leadership') or '').lower() in CHAIR:
                chairs[k] = bioguide
    return {'publisher': 'House Clerk MemberData.xml', 'congress': congress,
            'date': root.get('publish-date'), 'seats': seats, 'chairs': chairs, 'chambers': {'h'}, 'subcommittees': True}


def senate_cvc(path):
    root = ET.fromstring(_open(path))
    seats, chairs = defaultdict(set), {}
    for senator in root.iter('senator'):
        bioguide = (senator.findtext('bioguideId') or '').strip()
        for committee in senator.iter('committee'):
            k = key(committee.get('code', ''))
            seats[k].add(bioguide)
            if (committee.get('position') or '').lower() in CHAIR:
                chairs[k] = bioguide
    return {'publisher': 'Senate cvc_member_data.xml', 'congress': None,
            'date': root.findtext('lastUpdate/date'), 'seats': seats, 'chairs': chairs, 'chambers': {'s'},
            'subcommittees': False}


def legislators(path):
    import yaml
    data = yaml.safe_load(Path(path).read_text())
    seats, chairs = defaultdict(set), {}
    for code, members in data.items():
        k = key(code)
        for member in members or []:
            seats[k].add(member['bioguide'])
            if (member.get('title') or '').lower() in CHAIR:
                chairs[k] = member['bioguide']
    return {'publisher': 'congress-legislators committee-membership-current.yaml', 'congress': None, 'date': None,
            'seats': seats, 'chairs': chairs, 'chambers': {'h', 's', 'j'}, 'subcommittees': True}


def load_seats(path, congress):
    """Seats from the archive ``rosters`` (position in ``title``) or SpicyRegs ``committee_assignments``
    (``position``), parquet or JSON; whichever position column the file has is read."""
    path = Path(path)
    if path.suffix == '.parquet':
        import duckdb
        names = {row[0] for row in duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()}
        position = 'title' if 'title' in names else 'position'
        rows = duckdb.sql(f"SELECT congress, system_code, bioguide_id, {position} FROM read_parquet('{path}')").fetchall()
        rows = [dict(zip(('congress', 'system_code', 'bioguide_id', 'title'), r)) for r in rows]
    else:
        rows = [dict(row, title=row.get('title', row.get('position'))) for row in json.loads(path.read_text())]
    seats, chairs = defaultdict(set), {}
    for row in rows:
        if int(row['congress']) != congress:
            continue
        k = key(row['system_code'])
        seats[k].add(row['bioguide_id'])
        if (row.get('title') or '').lower() in CHAIR:
            chairs[k] = row['bioguide_id']
    return seats, chairs


def compare(seats, chairs, source):
    """Both directions, per committee the independent source can see."""
    visible = {k for k in seats if k[0] in source['chambers'] and (source['subcommittees'] or k.endswith('00'))}
    both = sorted(visible & set(source['seats']))
    differences, inter, ours, theirs = [], 0, 0, 0
    for k in both:
        a, b = seats[k], source['seats'][k]
        inter, ours, theirs = inter + len(a & b), ours + len(a), theirs + len(b)
        if a != b:
            differences.append({'committee': k, 'only_under_test': sorted(a - b), 'only_independent': sorted(b - a)})
    chair_checked = [k for k in both if k in chairs and k in source['chairs']]
    mismatches = [{'committee': k, 'under_test': chairs[k], 'independent': source['chairs'][k]}
                  for k in chair_checked if chairs[k] != source['chairs'][k]]
    return {
        'publisher': source['publisher'], 'independent_congress': source['congress'], 'independent_date': source['date'],
        'committees_compared': len(both),
        'committees_only_under_test': sorted(visible - set(source['seats'])),
        'committees_only_independent': sorted(k for k in source['seats'] if k not in seats),
        'seats_under_test': ours, 'seats_independent': theirs, 'seats_in_both': inter,
        'agreement': round(2 * inter / (ours + theirs), 4) if ours + theirs else None,
        'chairs_compared': len(chair_checked), 'chair_mismatches': mismatches, 'seat_differences': differences,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--seats', required=True)
    parser.add_argument('--congress', type=int, required=True)
    parser.add_argument('--house-memberdata')
    parser.add_argument('--senate-cvc')
    parser.add_argument('--legislators-yaml')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    seats, chairs = load_seats(args.seats, args.congress)
    sources = ([house_memberdata(args.house_memberdata)] if args.house_memberdata else []) + \
              ([senate_cvc(args.senate_cvc)] if args.senate_cvc else []) + \
              ([legislators(args.legislators_yaml)] if args.legislators_yaml else [])
    report = {'congress': args.congress, 'seats': args.seats, 'results': []}
    for source in sources:
        if source['congress'] not in (None, args.congress):
            raise SystemExit(f"{source['publisher']} states Congress {source['congress']}, not {args.congress}")
        report['results'].append(compare(seats, chairs, source))
    Path(args.output).write_text(json.dumps(report, indent=1))
    for result in report['results']:
        print(f"{result['publisher']}: {result['committees_compared']} committees, agreement {result['agreement']}, "
              f"{result['seats_in_both']}/{result['seats_under_test']} under test vs {result['seats_independent']} independent, "
              f"chairs {result['chairs_compared'] - len(result['chair_mismatches'])}/{result['chairs_compared']} agree")
    return report


if __name__ == '__main__':
    main()

"""Read the raw record behind every meeting row the round-1b meeting rules changed.

    meeting_semantics_raw_check.py --before DIR --before-witnesses PARQUET --after DIR --records PARQUET
        --appearances PARQUET --captures PARQUET --mirror R2 --mods DIR --output OUT.json

The changed set is a diff by event of access, not_held, status, rescheduled_to/basis, coverage
(state, reason) and the witness (occasion, source) sets. Each changed row gets the raw values read
and a verdict: raw_supports_after, raw_supports_before, ambiguous or unread. Raw is read here with
plain regex, JSON and XML walks, never through congress_api.parsers.meeting_facts or the model SQL,
so the rule under test cannot agree with itself. Titles are compared whole (normalized), not by
title_key. No raw record can prove ``unknown``: for coverage relabels only the premise is checked.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

import duckdb

sys.path.insert(0, str(Path(__file__).parent))
from explorer_class_validation import raw_meetings  # noqa: E402
from explorer_full_compare import body  # noqa: E402

SAMPLES = 40
EVENT_IN_URL = re.compile(r'/meetings/[A-Za-z0-9]+/[A-Za-z0-9]+/\d{8}/(\d+)/')


def norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


def table(db, path, sql='*'):
    return db.execute(f"SELECT {sql} FROM read_parquet('{path}')")


def records(cursor):
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


class Family:
    def __init__(self, name):
        self.name, self.rows, self.verdicts, self.samples, self.unread = name, 0, Counter(), defaultdict(list), []

    def add(self, key, verdict, **raw):
        self.rows += 1
        self.verdicts[verdict] += 1
        if verdict == 'unread':
            self.unread.append(key)
        if len(self.samples[verdict]) < SAMPLES:
            self.samples[verdict].append(dict(key=key, **raw))

    def report(self):
        return dict(rows=self.rows, verdicts=dict(self.verdicts), unread=self.unread, samples=dict(self.samples))


def house_root(xml_texts):
    """The latest House XML version's root <current-status> and title."""
    best = None
    for text in xml_texts:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        if best is None or (root.get('update-date') or '') >= (best.get('update-date') or ''):
            best = root
    if best is None:
        return None
    title = best.findtext('meeting-details/meeting-title') or best.findtext('heading') or ''
    return dict(status=(best.findtext('current-status') or '').strip(), title=' '.join(title.split()),
                files=[f.get('doc-url') for f in best.iter('file') if f.get('doc-url') and not (f.get('remove-date') or '').strip()])


def raw_status(cg, hx):
    """Publisher statuses and title as stated: Congress.gov word, House code."""
    return dict(congress_gov=(cg or {}).get('meetingStatus'), house=(hx or {}).get('status'),
                title=(cg or {}).get('title') or (hx or {}).get('title'))


def says_not_held(raw):
    words = {str(raw['congress_gov'] or '').lower(), {'p': 'postponed'}.get(str(raw['house'] or '').lower(), '')}
    if words & {'postponed', 'canceled', 'cancelled'}:
        return True
    title = (raw['title'] or '').lower().lstrip(' \t\r\n*:-"“')
    return bool(re.match(r'(postponed|cancel+ed|test)\b', title)) and not re.match(r'postponed\s+(until|to)\s+\d', title)


def mods(directory, package):
    path = Path(directory) / f'{package}.xml'
    if not path.is_file():
        return None
    text = path.read_text(errors='replace')
    return dict(event_ids=sorted({int(v) for v in re.findall(r'<eventId>\s*(\d+)\s*</eventId>', text)}),
                held=sorted(set(re.findall(r'<heldDate>([^<]+)</heldDate>', text))),
                title=' '.join((re.search(r'<title>([^<]*)</title>', text) or [None, ''])[1].split()),
                witnesses=len(re.findall(r'<witness>', text)))


def check_meetings(args, db, congress, house, report):
    before = {r['event_id']: r for r in records(table(db, Path(args.before) / 'meetings.parquet',
              'event_id,access,not_held,status,rescheduled_to,rescheduled_basis,videos,meeting_date,title'))}
    after = {r['event_id']: r for r in records(table(db, Path(args.after) / 'meetings.parquet',
             'event_id,access,not_held,status,rescheduled_to,rescheduled_basis,videos,meeting_date,title'))}
    fams = {k: Family(k) for k in ('access', 'not_held', 'status', 'rescheduled_to')}
    for event in sorted(set(before) | set(after)):
        b, a = before.get(event) or {}, after.get(event) or {}
        cg, hx = congress.get(str(event)), house_root(house.get(str(event), []))
        raw = raw_status(cg, hx)
        if b.get('access') != a.get('access'):
            if cg is None:
                fams['access'].add(event, 'unread', before=b.get('access'), after=a.get('access'))
            else:
                kind, title = str(cg.get('type') or '').lower(), (cg.get('title') or '').lower()
                stated = {v for v in ('open', 'closed') if re.search(rf'\b{v}\b', kind)}
                other = re.search(r'(followed|preceded) by (an? )?(open|closed) (session|hearing|meeting|briefing)', title)
                mixed = len(stated) == 1 and other and other.group(3) not in stated
                fams['access'].add(event, 'raw_supports_after' if (mixed and a.get('access') == 'partly_closed') else 'ambiguous',
                                   type=cg.get('type'), title=cg.get('title'), before=b.get('access'), after=a.get('access'))
        if bool(b.get('not_held')) != bool(a.get('not_held')):
            if cg is None and hx is None:
                fams['not_held'].add(event, 'unread', before=b.get('not_held'), after=a.get('not_held'))
            else:
                verdict = 'raw_supports_after' if says_not_held(raw) == bool(a.get('not_held')) else 'raw_supports_before'
                fams['not_held'].add(event, verdict, **raw, before=b.get('not_held'), after=a.get('not_held'),
                                     own_videos=[v['url'] for v in a.get('videos') or []])
        if (b.get('status') or None) != (a.get('status') or None):
            stated = (raw['congress_gov'] or {'s': 'Scheduled', 'r': 'Rescheduled', 'p': 'Postponed'}.get(str(raw['house'] or '').lower()))
            fams['status'].add(event, 'unread' if cg is None and hx is None else
                               'raw_supports_after' if stated == a.get('status') else 'ambiguous', **raw, before=b.get('status'), after=a.get('status'))
        if (b.get('rescheduled_to'), b.get('rescheduled_basis')) != (a.get('rescheduled_to'), a.get('rescheduled_basis')):
            twin_id = a.get('rescheduled_to') or b.get('rescheduled_to')
            tcg = congress.get(str(twin_id)) or {}
            twin_title = tcg.get('title') or (house_root(house.get(str(twin_id), [])) or {}).get('title')
            own = [v.get('url') for v in (cg or {}).get('videos') or []]
            row = dict(**raw, date=(cg or {}).get('date'), own_videos=own, twin=twin_id, twin_status=tcg.get('meetingStatus'),
                       twin_date=tcg.get('date'), twin_title=twin_title, twin_videos=[v.get('url') for v in tcg.get('videos') or []],
                       jackets=[t.get('jacketNumber') for t in (cg or {}).get('hearingTranscript') or []],
                       before=[b.get('rescheduled_to'), b.get('rescheduled_basis')], after=[a.get('rescheduled_to'), a.get('rescheduled_basis')])
            if cg is None and hx is None:
                fams['rescheduled_to'].add(event, 'unread', **row)
                continue
            same = norm(raw['title']) == norm(twin_title)
            moved = says_not_held(raw) or (not own and same)
            if a.get('rescheduled_to'):
                verdict = 'raw_supports_after' if moved and same else 'ambiguous'
            else:
                verdict = 'raw_supports_after' if (own and not says_not_held(raw)) or not same else 'ambiguous'
            fams['rescheduled_to'].add(event, verdict, **row)
    report.update({k: f.report() for k, f in fams.items()})


def check_witnesses(args, db, congress, report):
    cols = 'event_id,occasion,source,package_id,name,record_sha'
    before = records(table(db, args.before_witnesses, cols))
    after = records(table(db, Path(args.after) / 'witnesses.parquet', cols))
    side = lambda rows: {(r['occasion'], r['source'], r['name'], bytes(r['record_sha']).hex()) for r in rows}
    gone, came = side(before) - side(after), side(after) - side(before)
    package, house_list, other = Family('package_choice'), Family('house_witness_event'), Family('other_witness_changes')
    sha_events = defaultdict(set)
    for occasion, source, _, sha in gone | came:
        sha_events[sha].add((occasion, source))
    house_shas = {sha for sha, items in sha_events.items() if any(s == 'house_xml' for _, s in items)}
    paths = original_paths(args, db, house_shas)
    seen_record = set()
    for occasion, source, name, sha in sorted(gone | came):
        if (sha, occasion) in seen_record:
            continue
        seen_record.add((sha, occasion))
        state = 'after' if (occasion, source, name, sha) in came else 'before'
        if source == 'mods':
            pkg = next((r['package_id'] for r in before + after if bytes(r['record_sha']).hex() == sha and r['package_id']), None)
            raw = mods(args.mods, pkg) if pkg else None
            event = int(occasion.split(':')[1]) if occasion.startswith('meeting:') else None
            if raw is None:
                package.add([pkg, occasion, state], 'unread')
                continue
            cg = congress.get(str(event)) if event else None
            if state == 'after' and event is not None:
                verdict = 'raw_supports_after' if raw['event_ids'] == [event] else 'ambiguous'
            elif state == 'before' and event is not None:
                # The row left meeting:E. Raw backs that when its own MODS names another or several events.
                verdict = ('raw_supports_after' if raw['event_ids'] and raw['event_ids'] != [event]
                           else 'raw_supports_before' if raw['event_ids'] == [event] else 'ambiguous')
            else:
                verdict = 'ambiguous'
            package.add([pkg, occasion, state], verdict, mods=raw, meeting_title=(cg or {}).get('title'), meeting_date=(cg or {}).get('date'))
        elif source == 'house_xml' and state == 'after' and occasion.startswith('meeting:'):
            data = body(args.mirror, sha)
            if data is None:
                house_list.add([sha, occasion], 'unread')
                continue
            events = {int(e) for e in EVENT_IN_URL.findall(data.decode('utf-8', 'replace'))}
            path_events = {int(m) for p in paths.get(sha, ()) for m in re.findall(r'wlist/(\d+)\.xml$', p)}
            event = int(occasion.split(':')[1])
            verdict = 'raw_supports_after' if events == {event} and path_events in (set(), {event}) else 'ambiguous'
            house_list.add([sha, occasion], verdict, body_events=sorted(events), receipt_path_events=sorted(path_events))
        else:
            other.add([sha, occasion, source, state], 'ambiguous')
    report.update(package_choice=package.report(), house_witness_event=house_list.report(), other_witness_changes=other.report())
    report['witness_keys'] = dict(rows_gone=len(gone), rows_new=len(came))


def original_paths(args, db, shas):
    """Each body's receipt-line original_path (file_references), read from the receipt itself."""
    if not shas:
        return {}
    lines = db.execute(f"""SELECT DISTINCT lower(hex(sha256)),receipt_key,receipt_line FROM read_parquet('{args.captures}')
        WHERE lower(hex(sha256)) IN (SELECT unnest(?))""", [sorted(shas)]).fetchall()
    by_key = defaultdict(lambda: defaultdict(set))
    for sha, key, line in lines:
        by_key[key][line].add(sha)
    found = defaultdict(set)
    for key, wanted in by_key.items():
        with gzip.open(Path(args.mirror) / key, 'rt') as source:
            for number, text in enumerate(source, 1):
                if number in wanted:
                    item = json.loads(text)
                    for ref in item.get('file_references') or []:
                        if ref.get('sha256') in wanted[number] and ref.get('original_path'):
                            found[ref['sha256']].add(ref['original_path'])
    return found


def check_coverage(args, db, congress, house, report):
    key = 'event_id,aspect,state,reason'
    before = {(r['event_id'], r['aspect']): r for r in records(table(db, Path(args.before) / 'meeting_coverage.parquet',
              "event_id,aspect,state,cast(NULL AS VARCHAR) AS reason" if not has_reason(db, args.before) else key))}
    after = {(r['event_id'], r['aspect']): r for r in records(table(db, Path(args.after) / 'meeting_coverage.parquet', key))}
    fam = Family('coverage_relabels')
    transitions = Counter()
    mods_named = defaultdict(set)
    for path in Path(args.mods).glob('CHRG-*.xml'):
        for value in re.findall(r'<eventId>\s*(\d+)\s*</eventId>', path.read_text(errors='replace')):
            mods_named[int(value)].add(path.stem)
    for k in sorted(set(before) | set(after)):
        b, a = before.get(k) or {}, after.get(k) or {}
        if (b.get('state'), b.get('reason')) == (a.get('state'), a.get('reason')):
            continue
        transitions[(k[1], b.get('state'), a.get('state'), a.get('reason'))] += 1
        event, reason = k[0], a.get('reason')
        cg, hx = congress.get(str(event)), house_root(house.get(str(event), []))
        if reason == 'senate_page_links_pending':
            premise = None if cg is None else str(cg.get('chamber') or '').lower() == 'senate'
        elif reason == 'stated_documents_not_held':
            urls = [d.get('url') for d in ((cg or {}).get('meetingDocuments') or []) + ((cg or {}).get('witnessDocuments') or []) if d.get('url')]
            premise = None if cg is None and hx is None else bool(urls or (hx or {}).get('files'))
        elif reason == 'package_names_meeting_unlinked':
            premise = bool(mods_named.get(event))
        else:
            premise = 'not_checked'
        verdict = 'unread' if premise is None else 'premise_holds' if premise is True else 'premise_fails' if premise is False else 'ambiguous'
        if len(fam.samples[verdict]) < SAMPLES or verdict != 'premise_holds':
            fam.add([event, k[1]], verdict, before=[b.get('state'), b.get('reason')], after=[a.get('state'), reason])
        else:
            fam.rows += 1
            fam.verdicts[verdict] += 1
    report['coverage_relabels'] = dict(fam.report(), transitions=[[*t, n] for t, n in sorted(transitions.items(), key=str)],
        note='No raw record can prove unknown; only the premise of each relabel is checked.')


def has_reason(db, directory):
    return 'reason' in [c[0] for c in db.execute(f"DESCRIBE SELECT * FROM read_parquet('{Path(directory) / 'meeting_coverage.parquet'}')").fetchall()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('before', 'before-witnesses', 'after', 'records', 'appearances', 'captures', 'mirror', 'mods', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    db = duckdb.connect(config=dict(memory_limit='3GB', threads=4))
    congress, house, read, unread = raw_meetings(args)
    report = dict(raw_meeting_records=dict(read=read, unread=unread))
    check_meetings(args, db, congress, house, report)
    check_witnesses(args, db, congress, report)
    check_coverage(args, db, congress, house, report)
    Path(args.output).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: (v.get('verdicts'), v.get('rows')) if isinstance(v, dict) and 'verdicts' in v else v for k, v in report.items()}, default=str))


if __name__ == '__main__':
    main()

"""Read the raw records behind every meeting row the round-1b meeting rules changed, and judge each
from independent raw facts.

    meeting_semantics_raw_check.py --before DIR --before-witnesses PARQUET --after DIR --records PARQUET
        --appearances PARQUET --captures PARQUET --mirror R2 --output OUT.json

Facts come from raw bodies read here with ElementTree, JSON and regex, never through
congress_api.parsers, the appearance producer or the model SQL:

- a print's held dates, titles, eventIds and witness count, from the GovInfo MODS body in the mirror;
- a meeting's date, status, title, type, witnesses and transcript files, from its Congress.gov line;
- an own video's publish day (Eastern), from the videos table built from the YouTube cache.

Titles are compared by a different measure from the
model's shared-word rule: token containment of the print title in the meeting title (or difflib
ratio, whichever is higher): agree at >= 0.6, disagree below 0.3, ambiguous between. Each changed row gets
raw_supports_after, raw_contradicts_after, ambiguous or unread, with the facts read. Unread rows are
listed. No raw record can prove `unknown`; coverage relabels check only their premise.
"""
import argparse
from collections import Counter, defaultdict
from datetime import timezone
import difflib
import gzip
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import duckdb

sys.path.insert(0, str(Path(__file__).parent))
from explorer_class_validation import raw_meetings  # noqa: E402

SAMPLES = 40
EVENT_IN_URL = re.compile(r'/meetings/[A-Za-z0-9]+/[A-Za-z0-9]+/\d{8}/(\d+)/')
MODS = '{http://www.loc.gov/mods/v3}'
EASTERN = ZoneInfo('America/New_York')


def norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


def tokens(text):
    return {t for t in norm(text).split() if len(t) >= 3}


def similarity(left, rights):
    """How much of a print's title the meeting's title contains, at best over the print's titles.

    Containment, not the model's shared-word ratio: Senate Congress.gov titles join a business meeting
    and the hearing that follows, so the print's title is a part of the meeting's. difflib's whole-string
    ratio is kept as a second opinion for short titles."""
    meeting = tokens(left)
    best = 0.0
    for right in rights:
        if not right:
            continue
        own = tokens(right)
        contained = len(own & meeting) / len(own) if own else 0.0
        best = max(best, contained, difflib.SequenceMatcher(None, norm(left), norm(right)).ratio())
    return best


def agreement(score):
    return 'agree' if score >= 0.6 else 'disagree' if score < 0.3 else 'ambiguous'


def records(cursor):
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def local_body(mirror, sha):
    """The mirror's stored body, or None; no network fallback, so unread stays visible."""
    for suffix in ('.gz', ''):
        path = Path(mirror) / 'bodies/sha256' / sha[:2] / (sha + suffix)
        if path.is_file():
            data = path.read_bytes()
            return gzip.decompress(data) if suffix else data
    return None


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


class Prints:
    """Each package's MODS body, read once from the mirror by the record digest the lake names."""
    def __init__(self, args, db):
        self.mirror, self.cache = args.mirror, {}
        self.sha = dict(db.execute(f"""SELECT package_id,lower(hex(min(record_sha))) FROM read_parquet('{args.appearances}')
            WHERE source='mods' AND package_id IS NOT NULL GROUP BY 1""").fetchall())

    def __call__(self, package):
        if package not in self.cache:
            sha = self.sha.get(package)
            data = local_body(self.mirror, sha) if sha else None
            self.cache[package] = None if data is None else self.parse(data)
        return self.cache[package]

    @staticmethod
    def parse(data):
        root = ET.fromstring(data)
        held = sorted({(e.text or '').strip()[:10] for e in root.iter(MODS + 'heldDate') if (e.text or '').strip()})
        titles = [(e.text or '').strip() for e in root.iter(MODS + 'title')] + [(e.text or '').strip() for e in root.iter(MODS + 'searchTitle')]
        events = sorted({int(e.text) for e in root.iter(MODS + 'eventId') if (e.text or '').strip().isdigit()})
        return dict(held=held, titles=[t for t in titles if t and not t.lower().startswith('united states congress serial')],
                    events=events, witnesses=sum(1 for _ in root.iter(MODS + 'witness')))


def belongs(print_facts, event, cg):
    """Raw verdict on whether a print records this meeting: its day, its title, and any eventId it states."""
    if print_facts is None or cg is None:
        return 'unread'
    day = str(cg.get('date') or '')[:10]
    if day not in print_facts['held'] or (print_facts['events'] and event not in print_facts['events']):
        return 'disagree'
    return agreement(similarity(cg.get('title'), print_facts['titles']))


def video_days(db, after):
    """Each video's publish day in Eastern time, from the videos table (YouTube cache)."""
    out = {}
    for key, published in db.execute(f"SELECT video_key,coalesce(video_published_at,published_at) FROM read_parquet('{Path(after) / 'videos.parquet'}')").fetchall():
        if published is not None:
            out[key] = published.astimezone(EASTERN).date().isoformat()
    return out


def own_facts(cg, packages, prints, event, days):
    """A meeting's own evidence of sitting on its date, as raw states it."""
    cg = cg or {}
    day = str(cg.get('date') or '')[:10]
    videos = [re.search(r'(?:v=|youtu\.be/)([\w-]{11})', str(v.get('url') or '')) for v in cg.get('videos') or []]
    same_day_videos = [m.group(1) for m in videos if m and days.get('youtube:' + m.group(1)) == day]
    docs = cg.get('meetingDocuments') or []
    printed = [p for p in packages if belongs(prints(p), event, cg) == 'agree']
    return dict(status=cg.get('meetingStatus'), type=cg.get('type'), day=day,
                transcripts=[d.get('url') for d in docs if 'transcript' in (str(d.get('documentType') or '') + str(d.get('url') or '')).lower()],
                witnesses=len(cg.get('witnesses') or []), same_day_videos=same_day_videos, prints=printed)


def stated_not_held(cg):
    status = str((cg or {}).get('meetingStatus') or '').lower()
    title = (cg or {}).get('title') or ''
    lead = title.lower().lstrip(' \t\r\n*:-"“')
    return status in ('postponed', 'canceled', 'cancelled') or (
        bool(re.match(r'(postponed|cancel+ed|test)\b', lead)) and not re.match(r'postponed\s+(until|to)\s+\d', lead))


def meeting_kind(text):
    text = str(text or '').lower()
    return 'hearing' if 'hearing' in text else 'markup' if 'markup' in text else None


def check_meetings(args, db, congress, prints, packages, days, report):
    cols = 'event_id,access,not_held,status,rescheduled_to,rescheduled_basis,meeting_date,title'
    before = {r['event_id']: r for r in records(db.execute(f"SELECT {cols} FROM read_parquet('{Path(args.before) / 'meetings.parquet'}')"))}
    after = {r['event_id']: r for r in records(db.execute(f"SELECT {cols} FROM read_parquet('{Path(args.after) / 'meetings.parquet'}')"))}
    fams = {k: Family(k) for k in ('access', 'not_held', 'rescheduled_to')}
    for event in sorted(set(before) | set(after)):
        b, a = before.get(event) or {}, after.get(event) or {}
        cg = congress.get(str(event))
        if b.get('access') != a.get('access'):
            if cg is None:
                fams['access'].add(event, 'unread')
            else:
                kind, title = str(cg.get('type') or '').lower(), (cg.get('title') or '').lower()
                stated = {v for v in ('open', 'closed') if re.search(rf'\b{v}\b', kind)}
                other = re.search(r'(followed|preceded) by (an? )?(open|closed) (session|hearing|meeting|briefing)', title)
                mixed = len(stated) == 1 and other and other.group(3) not in stated
                fams['access'].add(event, 'raw_supports_after' if mixed and a.get('access') == 'partly_closed' else 'ambiguous',
                                   type=cg.get('type'), title=cg.get('title'), before=b.get('access'), after=a.get('access'))
        own = own_facts(cg, packages.get(event, ()), prints, event, days) if cg else None
        if bool(b.get('not_held')) != bool(a.get('not_held')) or (cg and stated_not_held(cg)):
            if cg is None:
                fams['not_held'].add(event, 'unread', before=b.get('not_held'), after=a.get('not_held'))
            else:
                sat = bool(own['prints'] or own['same_day_videos'] or own['transcripts'])
                raw_not_held = stated_not_held(cg) and not sat
                verdict = 'raw_supports_after' if raw_not_held == bool(a.get('not_held')) else 'raw_contradicts_after'
                fams['not_held'].add(event, verdict, title=cg.get('title'), own=own, before=b.get('not_held'), after=a.get('not_held'),
                                     status_conflict=stated_not_held(cg) and sat)
        if a.get('rescheduled_to') or (b.get('rescheduled_to'), b.get('rescheduled_basis')) != (a.get('rescheduled_to'), a.get('rescheduled_basis')):
            twin = a.get('rescheduled_to') or b.get('rescheduled_to')
            tcg = congress.get(str(twin))
            if cg is None or tcg is None:
                fams['rescheduled_to'].add(event, 'unread', twin=twin)
                continue
            sat = bool(own['prints'] or own['same_day_videos'] or own['transcripts'] or (own['witnesses'] and not stated_not_held(cg)))
            same_kind = None in (meeting_kind(cg.get('type')), meeting_kind(tcg.get('type'))) or meeting_kind(cg.get('type')) == meeting_kind(tcg.get('type'))
            title = agreement(similarity(cg.get('title'), [tcg.get('title')]))
            if a.get('rescheduled_to'):
                verdict = 'raw_contradicts_after' if sat or not same_kind or title == 'disagree' else 'raw_supports_after' if title == 'agree' else 'ambiguous'
            else:
                verdict = 'raw_supports_after' if sat or not same_kind or title == 'disagree' else 'ambiguous'
            fams['rescheduled_to'].add(event, verdict, title=cg.get('title'), twin=twin, twin_title=tcg.get('title'),
                                       twin_type=tcg.get('type'), own=own, before=[b.get('rescheduled_to'), b.get('rescheduled_basis')],
                                       after=[a.get('rescheduled_to'), a.get('rescheduled_basis')])
    report.update({k: f.report() for k, f in fams.items()})


def check_witnesses(args, db, congress, prints, report):
    cols = 'event_id,occasion,source,package_id,name,record_sha'
    before = records(db.execute(f"SELECT {cols} FROM read_parquet('{args.before_witnesses}')"))
    after = records(db.execute(f"SELECT {cols} FROM read_parquet('{Path(args.after) / 'witnesses.parquet'}')"))
    key = lambda r: (bytes(r['record_sha']).hex(), r['source'])
    def occasions(rows):
        out = defaultdict(lambda: [set(), None])
        for r in rows:
            out[key(r)][0].add(r['occasion'])
            out[key(r)][1] = out[key(r)][1] or r['package_id']
        return out
    ob, oa = occasions(before), occasions(after)
    package_fam, house_fam = Family('package_choice'), Family('house_witness_event')
    covered = {r['occasion'] for r in after if r['source'] != 'mods'}
    paths = original_paths(args, db, {k[0] for k in set(ob) | set(oa) if k[1] == 'house_xml'})
    for k in sorted(set(ob) | set(oa)):
        b, a = ob.get(k, (set(), None)), oa.get(k, (set(), None))
        if b[0] == a[0]:
            continue
        sha, source = k
        if source == 'mods':
            package = a[1] or b[1]
            events = {int(o.split(':')[1]) for o in a[0] | b[0] if o and o.startswith('meeting:')}
            for event in sorted(events):
                verdict = belongs(prints(package), event, congress.get(str(event)))
                # A print on meeting:E publishes nothing when a higher-priority source holds that meeting.
                attached = f'meeting:{event}' in a[0] or (not a[0] and f'meeting:{event}' in covered)
                raw = dict(package=package, event=event, before=sorted(b[0]), after=sorted(a[0]), print=prints(package),
                           meeting=(congress.get(str(event)) or {}).get('title'), date=str((congress.get(str(event)) or {}).get('date'))[:10])
                if verdict == 'unread':
                    package_fam.add([package, event], 'unread', **raw)
                elif verdict == 'ambiguous':
                    package_fam.add([package, event], 'ambiguous', **raw)
                else:
                    package_fam.add([package, event], 'raw_supports_after' if attached == (verdict == 'agree') else 'raw_contradicts_after', **raw)
        elif source == 'house_xml' and any(o.startswith('meeting:') for o in a[0]):
            data = local_body(args.mirror, sha)
            occasion = sorted(a[0])[0]
            event = int(occasion.split(':')[1])
            if data is None:
                house_fam.add([sha, occasion], 'unread')
                continue
            events = {int(e) for e in EVENT_IN_URL.findall(data.decode('utf-8', 'replace'))}
            path_events = {int(m) for p in paths.get(sha, ()) for m in re.findall(r'wlist/(\d+)\.xml$', p)}
            verdict = ('raw_supports_after' if events == {event} and path_events in (set(), {event}) else
                       'receipt_path_only' if not events and path_events == {event} else 'raw_contradicts_after')
            house_fam.add([sha, occasion], verdict, body_events=sorted(events), receipt_path_events=sorted(path_events))
    report.update(package_choice=package_fam.report(), house_witness_event=house_fam.report())
    report['witness_rows'] = dict(before=len(before), after=len(after))


def original_paths(args, db, shas):
    """Each body's receipt-line original_path (file_references), read from the receipt itself."""
    if not shas:
        return {}
    lines = db.execute(f"""SELECT DISTINCT lower(hex(sha256)),receipt_key,receipt_line FROM read_parquet('{args.captures}')
        WHERE lower(hex(sha256)) IN (SELECT unnest(?))""", [sorted(shas)]).fetchall()
    by_key = defaultdict(lambda: defaultdict(set))
    for sha, receipt, line in lines:
        by_key[receipt][line].add(sha)
    found = defaultdict(set)
    for receipt, wanted in by_key.items():
        with gzip.open(Path(args.mirror) / receipt, 'rt') as source:
            for number, text in enumerate(source, 1):
                if number in wanted:
                    for ref in json.loads(text).get('file_references') or []:
                        if ref.get('sha256') in wanted[number] and ref.get('original_path'):
                            found[ref['sha256']].add(ref['original_path'])
    return found


def check_coverage(args, db, congress, prints, packages, report):
    key = 'event_id,aspect,state,reason'
    has_reason = 'reason' in [c[0] for c in db.execute(f"DESCRIBE SELECT * FROM read_parquet('{Path(args.before) / 'meeting_coverage.parquet'}')").fetchall()]
    before = {(r['event_id'], r['aspect']): r for r in records(db.execute(
        f"SELECT {key if has_reason else 'event_id,aspect,state,cast(NULL AS VARCHAR) AS reason'} FROM read_parquet('{Path(args.before) / 'meeting_coverage.parquet'}')"))}
    after = {(r['event_id'], r['aspect']): r for r in records(db.execute(f"SELECT {key} FROM read_parquet('{Path(args.after) / 'meeting_coverage.parquet'}')"))}
    fam, transitions, by_aspect = Family('coverage_relabels'), Counter(), Counter()
    own_lists = {e for (e,) in db.execute(f"""SELECT DISTINCT event_id FROM read_parquet('{Path(args.after) / 'witnesses.parquet'}')
        WHERE source IN ('house_xml','congress_gov') AND event_id IS NOT NULL""").fetchall()}
    for k in sorted(set(before) | set(after)):
        b, a = before.get(k) or {}, after.get(k) or {}
        if (b.get('state'), b.get('reason')) == (a.get('state'), a.get('reason')):
            continue
        event, aspect, reason = k[0], k[1], a.get('reason')
        transitions[(aspect, b.get('state'), a.get('state'), reason)] += 1
        cg = congress.get(str(event))
        verdicts = {p: belongs(prints(p), event, cg) for p in packages.get(event, ())}
        if reason == 'senate_page_links_pending':
            premise = None if cg is None else str(cg.get('chamber') or '').lower() == 'senate'
        elif reason == 'stated_documents_not_held':
            premise = None if cg is None else bool([d for d in (cg.get('meetingDocuments') or []) + (cg.get('witnessDocuments') or []) if d.get('url')]) or None
        elif reason == 'package_witnesses_unattached':
            # Unknown is right only if no print that records this meeting holds witnesses.
            own = [p for p, v in verdicts.items() if v == 'agree' and (prints(p) or {}).get('witnesses')]
            premise = None if any(v == 'unread' for v in verdicts.values()) else not own
        elif aspect == 'witnesses' and a.get('state') == 'present' and event in own_lists:
            premise = True  # Its own House XML or Congress.gov list now reaches it (ct-x78c).
        elif aspect in ('recording', 'witnesses', 'transcript') and verdicts and a.get('state') == 'present' and b.get('state') != 'present':
            # A gain through a print needs a print that raw says records this meeting.
            states = set(verdicts.values())
            premise = True if 'agree' in states else None if 'unread' in states else 'ambiguous' if 'ambiguous' in states else False
        else:
            premise = 'not_checked'
        verdict = ('unread' if premise is None else 'premise_holds' if premise is True else 'premise_fails' if premise is False
                   else 'ambiguous' if premise == 'ambiguous' else 'not_checked')
        by_aspect[(aspect, verdict)] += 1
        if verdict != 'premise_holds' or len(fam.samples[verdict]) < SAMPLES:
            fam.add([event, aspect], verdict, before=[b.get('state'), b.get('reason')], after=[a.get('state'), reason], prints=verdicts)
        else:
            fam.rows += 1
            fam.verdicts[verdict] += 1
    report['coverage_relabels'] = dict(fam.report(), by_aspect={f'{a}:{v}': n for (a, v), n in sorted(by_aspect.items())},
        transitions=[[*t, n] for t, n in sorted(transitions.items(), key=str)],
        note='No raw record can prove unknown; only the premise of each relabel is checked.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('before', 'before-witnesses', 'after', 'records', 'appearances', 'captures', 'mirror', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    db = duckdb.connect(config=dict(memory_limit='3GB', threads=4))
    congress, house, read, unread = raw_meetings(args)
    prints = Prints(args, db)
    packages = defaultdict(set)
    for directory in (args.before, args.after):
        for event, package in db.execute(f"""SELECT event_id,t['package_id'] FROM (SELECT event_id,unnest(transcripts) AS t
            FROM read_parquet('{Path(directory) / 'meetings.parquet'}'))""").fetchall():
            packages[event].add(package)
    for row in records(db.execute(f"SELECT DISTINCT event_id,package_id FROM read_parquet('{Path(args.after) / 'witnesses.parquet'}') WHERE package_id IS NOT NULL AND event_id IS NOT NULL")):
        packages[row['event_id']].add(row['package_id'])
    report = dict(raw_meeting_records=dict(read=read, unread=unread))
    check_meetings(args, db, congress, prints, packages, video_days(db, args.after), report)
    check_witnesses(args, db, congress, prints, report)
    check_coverage(args, db, congress, prints, packages, report)
    report['prints'] = dict(read=sum(v is not None for v in prints.cache.values()), unread=sorted(p for p, v in prints.cache.items() if v is None))
    Path(args.output).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: (v.get('verdicts'), v.get('rows')) if isinstance(v, dict) and 'verdicts' in v else
                      (len(v['unread']) if k == 'prints' else v) for k, v in report.items()}, default=str))


if __name__ == '__main__':
    main()

"""Check every meeting whose transcripts changed (ct-1i4q) against raw, without the model's rules.

    transcript_sources_raw_check.py --before DIR --after DIR --release DIR --records PARQUET --mirror R2 --output OUT.json

committee_transcript: the meeting's own raw record (its Congress.gov line or House XML) lists a file with
that list row's filename, and Congress.gov's documentType, where stated, says it is a transcript.
captions: the track body read from the mirror is a WEBVTT/SRT/TTML file with at least one cue, and the
meeting's raw Congress.gov line names that video. Each row gets raw_supports_after, raw_contradicts_after
or unread, with the raw values read.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

import duckdb

sys.path.insert(0, str(Path(__file__).parent))
from explorer_class_validation import raw_meetings  # noqa: E402
from meeting_semantics_raw_check import Family, local_body  # noqa: E402


def basename(url):
    return (url or '').rstrip('/').rsplit('/', 1)[-1].lower()


def raw_files(cg, house_xml):
    """Filenames the meeting's own records list, with Congress.gov's document type when stated."""
    files = {}
    for doc in (cg or {}).get('meetingDocuments') or []:
        files[basename(doc.get('url'))] = doc.get('documentType') or doc.get('name')
    for text in house_xml or []:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        for f in root.iter('file'):
            if not (f.get('remove-date') or '').strip():
                files.setdefault(basename(f.get('doc-url')), None)
    return files


def cues(body):
    text = body.decode('utf-8', 'replace')
    return len(re.findall(r'\d{2}:\d{2}[:.,]\d{2}[.,]\d{3}\s*-->', text)) + len(re.findall(r'<p\b[^>]*\bbegin=', text))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('before', 'after', 'release', 'records', 'mirror', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    db = duckdb.connect()
    def entries(d):
        path = Path(d) / 'meetings.parquet'
        labelled = 'source' in str(db.execute(f"DESCRIBE SELECT transcripts FROM read_parquet('{path}')").fetchall())
        # Releases before ct-1i4q list printed hearings only, as (package_id, list_row).
        sql = (f"""SELECT event_id,t.source,coalesce(t.package_id,cast(t.list_row AS VARCHAR)),coalesce(t.video_key,'')||'|'||coalesce(t.production,'')
                FROM read_parquet('{path}'),unnest(transcripts) u(t)""" if labelled else
               f"SELECT event_id,'printed_hearing',t.package_id,'|' FROM read_parquet('{path}'),unnest(transcripts) u(t)")
        return {tuple(r) for r in db.execute(sql).fetchall()}
    before, after = entries(args.before), entries(args.after)
    gained, lost = after - before, before - after
    names = dict(db.execute(f"SELECT file_row_number,filename FROM read_parquet('{Path(args.release) / 'list.parquet'}',file_row_number=true)").fetchall())
    tracks = {}
    for key, t in db.execute(f"SELECT video_key,unnest(tracks) FROM read_parquet('{Path(args.release) / 'recordings.parquet'}')").fetchall():
        tracks[(key, t['production'])] = t
    congress, house, read, unread = raw_meetings(args)
    dates = {e: str(d) for e, d in db.execute(f"SELECT event_id,meeting_date FROM read_parquet('{Path(args.after) / 'meetings.parquet'}')").fetchall()}
    fams = {k: Family(k) for k in ('committee_transcript', 'captions', 'removed')}
    for event, source, ident, track in sorted(gained, key=str):
        cg = congress.get(str(event))
        if source == 'committee_transcript':
            name = names.get(int(ident))
            files = raw_files(cg, house.get(str(event)))
            if not files:
                fams[source].add([event, name], 'unread')
                continue
            kind = files.get((name or '').lower(), 'missing')
            day = (re.search(r'Transcript-(\d{8})', name or '', re.I) or [None, ''])[1]
            ok = kind != 'missing' and (kind is None or 'transcript' in str(kind).lower()) and day == dates.get(event, '').replace('-', '')
            fams[source].add([event, name], 'raw_supports_after' if ok else 'raw_contradicts_after',
                             listed_as=kind, meeting_date=dates.get(event))
        elif source == 'captions':
            key, production = track.split('|')
            t = tracks.get((key, production))
            body = local_body(args.mirror, bytes(t['body']).hex()) if t and t['body'] else None
            if body is None:
                fams[source].add([event, key], 'unread')
                continue
            video = key.split(':', 1)[1]
            named = any(video in str(v.get('url') or '') for v in (cg or {}).get('videos') or [])
            n = cues(body)
            fams[source].add([event, key], 'raw_supports_after' if n > 0 and named else 'raw_contradicts_after',
                             cues=n, bytes=len(body), named_by_meeting=named)
        else:
            fams['removed'].add([event, source, ident], 'not_checked')
    for row in sorted(lost, key=str):
        fams['removed'].add(list(row), 'lost')
    report = dict(raw_meeting_records=dict(read=read, unread=unread), meetings_changed=len({r[0] for r in gained | lost}),
                  **{k: f.report() for k, f in fams.items()})
    Path(args.output).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: (v['verdicts'], v['rows']) if isinstance(v, dict) and 'verdicts' in v else v for k, v in report.items()}, default=str))


if __name__ == '__main__':
    main()

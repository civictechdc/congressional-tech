"""Replay run 44737429192 from the retained archive and content-addressed raw objects."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request, urlopen

from congress_shared.custody import verify_local_file
from viewer_publication.archive_format import release_identity
from viewer_publication.data_only_night import data_only_causes
from viewer_publication.recording_pages import captured_body, page_links
from viewer_publication.release_gate import new_recording_pages

FAILED = 'caf35cec7d01d2ee9bf0dd37e4369823a966a22a8830ef7f164b2d82ee816277'
AVAILABLE = '0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3'
EVENT = 116718
VIDEO = 'youtube:Fyr9cXKd6NU'
PUBLISHER = 'receipts/congress/meetings/2026-10-31/20261031T004823Z-8de73c920546-001238.jsonl.gz'
PAGE = ('receipts/house/pages/2026-11-20/20261120T115840Z-ec7f78b9a47b-'
        'ace7e2ad8ada1131a2767b8a324d67b087ada69dd649a18416b64cd803431407.jsonl.gz')
RECEIPT_HASHES = {PUBLISHER: '762783b893f318ce62b385f5ee795a2ba30d1d991f2ea9284bd8ef43d8932b3c',
                  PAGE: 'a0a4f36aba707d80eb3187d3f33ac2b7d5b8e453aea605a4c62fa5ac001f545b'}
RECORDINGS = ('recordings.parquet', 'recording_matches.parquet')
OTHER = ('meetings.parquet', 'detail.parquet')


def check(ok, message):
    if not ok:
        raise ValueError(message)


def read_json(path, digest):
    raw = path.read_bytes()
    check(sha256(raw).hexdigest() == digest, f'Unexpected retained artifact {path.name}')
    return json.loads(raw)


def compare_manifests(failed, available, directory):
    check(failed['release_id'] == FAILED and available['release_id'] == AVAILABLE, 'Wrong candidate manifest')
    for manifest in (failed, available):
        check(release_identity(manifest['schema_version'], manifest['files']) == manifest['release_id'], 'Invalid manifest identity')
    pairs = {}
    for name in (*RECORDINGS, *OTHER):
        original, other = (next(item for item in m['files'] if item['name'] == name) for m in (failed, available))
        verify_local_file((directory / name).resolve(), other['sha256'], other['size'])
        same = (original['sha256'], original['size']) == (other['sha256'], other['size'])
        check(same == (name in RECORDINGS), f'Unexpected candidate comparison for {name}')
        pairs[name] = dict(failed_sha256=original['sha256'], available_sha256=other['sha256'],
                           failed_size=original['size'], available_size=other['size'], identical=same)
    return pairs


def replacement(admitted, new, read, receipt_hashes):
    check(PUBLISHER in admitted and PAGE in new and PAGE in admitted, 'Replacement receipt outside the admitted set')
    evidence = {}
    for key, family, fmt in [(PUBLISHER, 'congress/meetings', 'json'), (PAGE, 'house/pages', 'html')]:
        raw = read(key)
        digest = sha256(raw).hexdigest()
        check(digest == receipt_hashes[key], f'Replacement receipt digest differs for {key}')
        row = json.loads(gzip.decompress(raw).splitlines()[0])
        check(row['mode'] == 'fetch' and row['outcome'] in ('stored', 'unchanged') and row['http_status'] == 200
              and row['family'] == family, 'Unsuccessful replacement receipt')
        cap = row['captures'][0]
        check(cap['complete'] is True and cap['sniffed_format'] == fmt, 'Incomplete replacement body')
        body = captured_body(cap, read)
        if key == PUBLISHER:
            meeting = json.loads(body)['committeeMeeting']
            check(row['requested_url'].split('?')[0] == 'https://api.congress.gov/v3/committee-meeting/118/house/116718'
                  and str(meeting['eventId']) == str(EVENT) and
                  any(v['url'] == 'https://www.youtube.com/watch?v=Fyr9cXKd6NU' for v in meeting['videos']),
                  'Congress.gov does not list the replacement for this event')
        else:
            videos, events = page_links(body, row['url'], {})
            check(VIDEO in videos and events == [EVENT], 'Committee page does not link this video and event')
        evidence[family] = dict(receipt_key=key, receipt_line=1, capture_index=0, receipt_sha256=digest,
                                page_url=row['url'], body_sha256=cap['sha256'], new=key in new)
    return dict(event_id=EVENT, video_key=VIDEO, receipts=evidence)


def replay(archive, local):
    retained = archive / 'long-tail-20261120/friction'
    out = archive / 'publish-44737429192/congressional-tech/congressional-tech/output'
    report = read_json(next(out.glob('archive-publish/candidate-*/release-gate.json')),
                       'c70bdb8b8df1cb217fe667e55e365674c9272dacffcee60e4288cd36df649c81')
    failed = read_json(out / 'archive-release/manifest.json', '27a866a41aebc9864882b4c238e22fe5162f021abb5f088cf71b2e75d60e5caa')
    check(report['candidate_release'] == FAILED, 'Wrong failed-run gate report')
    summary = read_json(out / 'archive-daily/daily-summary.json', '8dd2b8587012062efb33d6ab644a6bc40d6b20884aca7a23d3a3730fcbfaf00e')
    base, candidate = retained / report['base_release'], retained / AVAILABLE
    hashes = compare_manifests(failed, json.loads((candidate / 'manifest.json').read_bytes()), candidate)
    admitted, new = set(summary['receipt_keys']), set(summary['new_receipt_keys'])
    check(new <= admitted, 'New receipts absent from daily input')
    def read(key):
        for path in (retained / key, local / key):
            if path.is_file():
                return path.read_bytes()
        request = Request('https://congressional-data.spicygov.ai/' + key, headers={'Range': 'bytes=0-', 'Accept-Encoding': 'identity'})
        with urlopen(request, timeout=45) as response:
            return response.read()

    raw_proof = replacement(admitted, new, read, RECEIPT_HASHES)
    traces = read_json(retained / 'all-receipt-trace.json', 'd54730a4ed22b6a84b515e8e76d0790b6ead9d8285f77e8b538a8f9a66b360a9')
    export = verify_local_file(retained / 'recording_video_links.parquet',
                               '4f39b9d363f003e5232b21c8300233adb1d945fdbf33407b0e4acff539ba4748', 68440)
    base_manifest = json.loads((base / 'manifest.json').read_bytes())
    check(release_identity(base_manifest['schema_version'], base_manifest['files']) == report['base_release'], 'Wrong base manifest')
    for name in (*RECORDINGS, 'detail.parquet'):
        pin = next(f for f in base_manifest['files'] if f['name'] == name)
        verify_local_file((base / name).resolve(), pin['sha256'], pin['size'])
    # The report records no edits to the fields used to identify a proceeding on its calendar.
    columns = {'event_id', 'committees', 'sittings', 'videos', 'title', 'meeting_date'}
    meeting_report = report['files']['meetings.parquet']
    check(all(g['group'].startswith('changed ') and g['group'][8:] not in columns for g in meeting_report['groups']),
          'Failed candidate changed its meeting calendar')
    calendar_key = f"viewer-publications/releases/{report['base_release']}/meetings.parquet"
    calendar = local / calendar_key
    if not calendar.exists():
        calendar.parent.mkdir(parents=True, exist_ok=True)
        calendar.write_bytes(read(calendar_key))
    pin = next(f for f in base_manifest['files'] if f['name'] == 'meetings.parquet')
    verify_local_file(calendar, pin['sha256'], pin['size'])

    record = dict(profile={'fixture': 'same as live'}, entity_digests={}, provenance=[], unprofiled_inputs={})
    def pages(videos, new_receipts):
        return new_recording_pages(videos, new_receipts, export=export, meetings=calendar,
                                   trace=lambda keys: [r for r in traces if r['prefix'] in keys],
                                   read_receipt=read, read_object=read)
    entries, reasons, facts = data_only_causes(report, base_dir=base, candidate_dir=candidate, candidate_record=record,
        live_records=[dict(key='live', record=record, receipt_keys=admitted - new)], candidate_receipt_keys=admitted,
        recording_page_proof=pages)
    check(not reasons and len(entries) == len(report['failing']), f'Replay refused: {reasons}')
    removal, = facts['replaced_recording_matches']
    page = raw_proof['receipts']['house/pages']
    check((removal['event_id'], removal['replacement_video_key'], removal['candidate_page']) ==
          (EVENT, VIDEO, page['body_sha256']) and removal['page_receipts'][0]['receipt_key'] == PAGE,
          'Replayed match differs from original raw receipts')
    counts = Counter(p['receipt_key'] for p in facts['added_recording_pages'].values())
    return dict(run=44737429192, failed_release=FAILED, available_release=AVAILABLE, files=hashes,
                scope=dict(original=['gate report', 'manifest', 'admitted raw receipts'],
                           reconstructed=['recording video links'], substituted_tables=list(OTHER),
                           definitions='equal fixture values', event_calendar_release=report['base_release']),
                replacement=raw_proof, receipt_count=len(counts), most_unlinked_on_one_receipt=max(counts.values()),
                entries=entries, reasons=reasons, facts=facts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, help='Shared archive-release directory (read only)')
    parser.add_argument('local', type=Path, help='Local cache for raw objects and the base calendar')
    args = parser.parse_args()
    result = replay(args.archive, args.local)
    here = Path(__file__).parent
    (here / 'nightly-replay.json').write_text(json.dumps(result, indent=1) + '\n')
    counts = result['facts']
    summary = f"""# Run 44737429192

Candidate `{FAILED}` replaced the generic match for meeting 116718 with publisher-listed
video `{VIDEO}`. The admitted October 31 Congress.gov JSON lists the event and video URL.
The new November 20 committee HTML embeds the same video and links to the House calendar
entry for 116718. Both decompressed bodies match the SHA-256 on the first line of their
respective raw receipts. [Receipt keys and hashes](nightly-replay.json)

| File | Failed candidate SHA-256 | Available release SHA-256 |
| --- | --- | --- |
"""
    for name, p in result['files'].items():
        summary += f"| `{name}` | `{p['failed_sha256']}` | `{p['available_sha256']}` |\n"
    summary += f"""
The recording tables match byte for byte. The meeting and detail tables differ. The replay
used the failed run's gate report, manifest, admitted receipts, and a receipt-derived video
link export. The base release's pinned calendar supplied the meeting identity fields, which
the failed comparison reports unchanged. The independent replacement check used raw bytes.

The gate explained {len(result['entries'])} groups using equal fixture definitions and the available
`{AVAILABLE[:12]}` meeting and detail tables for the model-side replacement and column checks.
This is a partial historical replay. The original failed meeting and detail tables were unavailable.

All {len(counts['added_recording_pages'])} unlinked keys traced to {result['receipt_count']} new receipts.
The busiest receipt accounted for {result['most_unlinked_on_one_receipt']} keys. All {len(counts['added_recording_events'])}
added linked keys had their event corroborated. [Replay script](replay.py)
"""
    (here / 'verification.md').write_text(summary)


if __name__ == '__main__':
    main()

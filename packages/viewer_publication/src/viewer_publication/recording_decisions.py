"""One-time import of curated recording verdicts into provenance records.

These are human decisions, so after the import the records are the authority and the
CSVs stop being read. `decided_at` is unknown and stays null, never invented. The ID
hashes the decision without its origin, so re-importing from a later commit keeps it.

    python -m viewer_publication.recording_decisions --commit SHA --output decisions.jsonl

Writes a local file only; uploading provenance belongs to the live switch.
"""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).parents[4]
OVERRIDES = 'apps/committee_youtube/data/hearing_video_overrides.csv'
FOUND = 'apps/committee_youtube/data/meeting_recordings_found.csv'


def _blank(value):
    return value or None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _record(*, subject_kind, subject_id, verdict, video_refs, origin, channel=None, lock=None, note=None, found_by=None):
    record = dict(subject_kind=subject_kind, subject_id=subject_id, verdict=verdict, video_refs=video_refs,
        channel=channel, lock=lock, note=note, found_by=found_by, decided_at=None, supersedes=None)
    return dict(id=sha256(_canonical(record).encode()).hexdigest(), **record, origin=origin)


def _origin(path, commit, root):
    return dict(path=path, commit=commit, sha256=sha256((Path(root) / path).read_bytes()).hexdigest())


def import_records(*, commit, root=ROOT):
    """Every CSV row, in CSV order; a repeated row keeps its own record."""
    records = []
    origin = _origin(OVERRIDES, commit, root)
    with (Path(root) / OVERRIDES).open(newline='') as source:
        for row in csv.DictReader(source):
            records.append(_record(subject_kind='package', subject_id=row['package_id'], verdict=row['verdict'],
                video_refs=row['video_ids'].split(), channel=_blank(row['channel']), lock=_blank(row['lock']),
                note=_blank(row['note']), origin=origin))
    origin = _origin(FOUND, commit, root)
    with (Path(root) / FOUND).open(newline='') as source:
        for row in csv.DictReader(source):
            records.append(_record(subject_kind='event', subject_id=row['event_id'], verdict='found',
                video_refs=[row['recording']] if row['recording'] else [], note=_blank(row['note']),
                found_by=_blank(row['found_by']), origin=origin))
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.write_text(''.join(_canonical(item) + '\n' for item in import_records(commit=args.commit)))


if __name__ == '__main__':
    main()

"""Curated verdicts survive the one-time import value for value."""
import csv
import json

from viewer_publication.recording_decisions import FOUND, OVERRIDES, ROOT, import_records, main


def rows(path):
    with (ROOT / path).open(newline='') as source:
        return list(csv.DictReader(source))


def test_every_row_and_value_round_trips():
    records = import_records(commit='abc')
    overrides, found = rows(OVERRIDES), rows(FOUND)
    assert len(records) == len(overrides) + len(found) == 7200
    rebuilt = [dict(package_id=r['subject_id'], verdict=r['verdict'], video_ids=' '.join(r['video_refs']), channel=r['channel'] or '',
        lock=r['lock'] or '', note=r['note'] or '') for r in records[:len(overrides)]]
    normal = [dict(row, video_ids=' '.join(row['video_ids'].split())) for row in overrides]
    assert rebuilt == normal
    rebuilt = [dict(event_id=r['subject_id'], recording=r['video_refs'][0], found_by=r['found_by'] or '', note=r['note'] or '')
        for r in records[len(overrides):]]
    assert rebuilt == found


def test_ids_are_unique_stable_and_ignore_origin():
    first, second = import_records(commit='abc'), import_records(commit='def')
    assert [r['id'] for r in first] == [r['id'] for r in second]
    assert len({r['id'] for r in first}) == len(first)


def test_decided_at_is_never_invented():
    assert {r['decided_at'] for r in import_records(commit='abc')} == {None}


def test_output_is_deterministic_jsonl(tmp_path):
    one, two = tmp_path / 'one.jsonl', tmp_path / 'two.jsonl'
    main(['--commit', 'abc', '--output', str(one)])
    main(['--commit', 'abc', '--output', str(two)])
    assert one.read_bytes() == two.read_bytes()
    assert json.loads(one.read_text().splitlines()[0])['origin']['path'] == OVERRIDES


def test_a_dispute_never_moves_a_decision_id_and_marks_only_negative_verdicts():
    records = import_records(commit='abc')
    disputed = [r for r in records if r['disputed_by']]
    assert disputed and {r['verdict'] for r in disputed} == {'no_video_found'}
    assert all('disputed_by' not in json.dumps({k: v for k, v in r.items() if k != 'disputed_by'}) for r in disputed[:3])

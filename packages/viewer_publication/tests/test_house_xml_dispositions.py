"""The local House syntax transition preserves old selections and exact dispositions."""
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from congress_api.lake import meeting_records
from congress_api.lake._record_producer import unreadable_decision
from congress_api.retention.provenance import file_pin
from viewer_publication import archive_house_xml_dispositions as transition
from viewer_publication.archive_backfill_job import execute, load_spec, plan
from viewer_publication.producer_proof import BACKFILL

STAMP = '2026-11-06T18:00:00Z'
GOOD = b'<committee-meeting meeting-id="HMKP117001" update-date="2020-01-01"/>'
BAD = b'<committee-meeting'
RESOLUTION = b'<resolution><title>Complete resolution</title></resolution>'
AMP = b'<committee-meeting meeting-id="HMKP117002"><meeting-title>R & D</meeting-title></committee-meeting>'
WITNESSES = b'<witness-list meeting-id="HMKP117003"><witnesses/></witness-list>'


def pin(path):
    return dict(path=str(path), **file_pin(path))


def digest(data):
    return sha256(data).hexdigest()


def empty(name, body):
    column = {'meeting_records': 'meetings', 'appearance_records': 'appearances', 'committee_records': 'records'}[name]
    return dict(record_sha=digest(body), source='house_xml', parser_version=transition.OLD[name],
                status='completed', **{column: []})


@pytest.fixture
def writer(monkeypatch):
    # Unit fixtures may run in a dirty tree; production still requires the real clean writer.
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    value = dict(commit=commit, lockfile_digest=file_pin(transition.ROOT / 'uv.lock')['sha256'], job=BACKFILL)
    monkeypatch.setattr(transition, 'writer_identity', lambda *a: value)
    import congress_api.retention.writer_identity as identity
    monkeypatch.setattr(identity, 'writer_identity', lambda *a: value)
    return value


def make_spec(tmp_path, *, selected=None, candidate_extra=None, decisions=(), bodies=None):
    selected = selected or {name: [] for name in transition.MODULES}
    candidate_extra = candidate_extra or {}
    raw = tmp_path / 'raw'
    raw.mkdir()
    for body in bodies or []:
        target = raw / 'bodies' / 'sha256' / digest(body)[:2] / (digest(body) + '.gz')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gzip.compress(body, mtime=0))
    files = []
    if decisions:
        path = tmp_path / 'old-unreadable.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in decisions))
        files.append(dict(key='provenance/unreadable/fixture.jsonl', **pin(path)))
    bases, origins, candidates, counts = {}, {}, {}, {}
    proof = {row['record_sha'] for name, rows in selected.items() for row in rows
             if (bool(row.get('meetings')) if name == 'meeting_records' else
                 row.get('collection_state') in {'present', 'empty', 'absent'} if name == 'appearance_records' else
                 bool(row.get('records')) or row.get('event_id') is not None or row.get('updated') is not None)}
    for name, module in transition.MODULES.items():
        path = tmp_path / (name + '.parquet')
        pq.write_table(module.table(selected[name]), path)
        bases[name] = dict(kind='parquet', **pin(path))
        origin = tmp_path / (name + '.origin.json')
        origin.write_text(json.dumps(dict(version=1, input=name, selector=bases[name], job=BACKFILL,
            commit='742dbe70b42f0618e95816cd7cf0e6ba2f9939b0', lockfile_digest=file_pin(transition.ROOT / 'uv.lock')['sha256'])))
        origins[name] = pin(origin)
        keys = {row['record_sha'] for row in selected[name]} | set(candidate_extra.get(name, []))
        key_path = tmp_path / (name + '.keys.parquet')
        pq.write_table(pa.table(dict(record_sha=pa.array(sorted(keys), type=pa.string()),
                                    source=pa.array(['house_xml'] * len(keys), type=pa.string()))), key_path)
        candidates[name] = pin(key_path)
        active = transition._refusals(name, transition._decisions(files), transition.OLD[name])
        old = {row['record_sha'] for row in selected[name]}
        counts[name] = dict(O=len(old), K_base=len(keys), U=len(active), P=len(keys - old - active),
                            ambiguous=len(old - proof))
    census_path = tmp_path / 'census.json'
    census_path.write_text(json.dumps(dict(selectors=bases, tables=counts)))
    spec_path = tmp_path / 'transition.json'
    spec_path.write_text(json.dumps(dict(version=1, work=str(tmp_path / 'work'), engine_config=str(Path(os.environ['DOCSPEC_JOB_CONFIG']).resolve()),
        house_xml_disposition=dict(census=pin(census_path), bases=bases, origins=origins, candidates=candidates,
            unreadable_files=files, raw_root=str(raw), decided_at=STAMP, resume=False, pilot_body=None,
            limits=dict(max_pairs=100, max_recompute_pairs=100, max_unique_bodies=100,
                        max_body_bytes=1 << 20, max_stored_bytes=1 << 20,
                        max_total_decoded_bytes=10 << 20, max_output_bytes=10 << 20, min_disk_bytes=1)))))
    return load_spec(spec_path)


def cohort(tmp_path):
    held = meeting_records.build_meeting_record_row(digest(GOOD), 'house_xml', GOOD,
                                                    parser_version=transition.OLD['meeting_records'])
    assert held['meetings']
    rows = {name: [] for name in transition.MODULES}
    rows['meeting_records'] = [held, empty('meeting_records', BAD)]
    rows['committee_records'] = [empty('committee_records', body) for body in [BAD, RESOLUTION, AMP]]
    rows['committee_records'] += [transition.committee_records.build_row(digest(body), 'house_xml', body,
        parser_version=transition.OLD['committee_records']) for body in [GOOD, WITNESSES]]
    rows['appearance_records'] = [transition.appearance_records.build_appearance_record_row(
        digest(WITNESSES), 'house_xml', WITNESSES, parser_version=transition.OLD['appearance_records'])]
    assert rows['appearance_records'][0]['collection_state'] == 'empty'
    spec = make_spec(tmp_path, selected=rows, bodies=[BAD, RESOLUTION, AMP])
    # Discovery no longer includes this established row. Its bytes are deliberately absent.
    job = spec['house_xml_disposition']
    key_pin = job['candidates']['meeting_records']
    table = pq.read_table(key_pin['path'])
    table = table.filter(pc.not_equal(table['record_sha'], digest(GOOD)))
    pq.write_table(table, key_pin['path'])
    job['candidates']['meeting_records'] = pin(key_pin['path'])
    census_path = Path(job['census']['path'])
    census = json.loads(census_path.read_text())
    census['tables']['meeting_records']['K_base'] -= 1
    census_path.write_text(json.dumps(census))
    job['census'] = pin(census_path)
    return spec


def test_preserves_selected_outside_discovery_and_stages_syntax_dispositions(tmp_path, writer):
    spec = cohort(tmp_path)
    assert plan(spec)['executed'] is False and not Path(spec['work']).exists()
    result = execute(spec)
    assert result['status'] == 'local_staged' and result['shared_writes'] == 0
    assert result['settlement'] == dict(fresh_runtime=True, pending_pairs=0, settled_work_items=0)
    tables = result['tables']
    assert (tables['meeting_records']['reused'], tables['meeting_records']['unreadable']) == (1, 1)
    assert (tables['appearance_records']['reused'], tables['appearance_records']['produced']) == (1, 0)
    assert (tables['committee_records']['reused'], tables['committee_records']['produced'],
            tables['committee_records']['unreadable']) == (2, 2, 1)
    assert digest(GOOD) not in result['integrity']['bodies']  # cross-producer proof needs no raw open
    assert digest(WITNESSES) not in result['integrity']['bodies']
    committees = {row['record_sha'].hex(): row for row in pq.read_table(tables['committee_records']['selector']['path']).to_pylist()}
    assert committees[digest(RESOLUTION)]['records'] == []  # a complete wrong root remains completed empty
    assert committees[digest(AMP)]['event_id'] == '117002'
    for name, stage in tables.items():
        origin = json.loads(Path(stage['producer']['path']).read_text())
        assert origin['job'] == BACKFILL and origin['commit'] == writer['commit']
        assert origin['delta_only'] is True and origin['final_reconciliation_required'] is True
        assert origin['base'] == spec['house_xml_disposition']['bases'][name]
        for row in pq.read_table(stage['selector']['path']).to_pylist():
            assert row['parser_version'] == transition.NEW[name]
        for pin_ in stage['unreadable_files']:
            decisions = transition._decisions([pin_])
            assert decisions[0]['reason'] == 'parse_error'
            assert stage['unreadable_pending'] is True


def test_resume_reuses_completed_local_stages_and_fixed_decision_bytes(tmp_path, writer, monkeypatch):
    spec = cohort(tmp_path)
    first = execute(spec)
    monkeypatch.setattr(transition, 'stage_selected_records', lambda *a, **kw: pytest.fail('replayed a completed phase'))
    monkeypatch.setattr(transition, '_qualify_body', lambda *a, **kw: pytest.fail('reopened raw bytes'))
    spec['house_xml_disposition']['resume'] = True
    assert execute(spec) == first
    output = Path(first['tables']['meeting_records']['selector']['path'])
    output.write_bytes(b'changed')
    with pytest.raises(ValueError, match='differs from its pin'):
        execute(spec)


def test_active_prior_refusal_recomputed_superseded_refusal_not_reopened_and_missing_new_pending(tmp_path, writer):
    old = unreadable_decision('appearances', transition.OLD['appearance_records'], digest(BAD), ValueError(), STAMP)
    ignored = unreadable_decision('meeting_records', transition.OLD['meeting_records'], '22' * 32, ValueError(), STAMP)
    replacement = dict(ignored, id='replacement', parser_version='other', supersedes=ignored['id'])
    spec = make_spec(tmp_path, decisions=[old, ignored, replacement], bodies=[BAD],
        candidate_extra=dict(appearance_records=[digest(BAD)], committee_records=['11' * 32]))
    report = execute(spec)
    assert report['tables']['appearance_records']['unreadable'] == 1
    assert report['tables']['committee_records']['pending'] == 1
    assert '22' * 32 not in report['integrity']['bodies']
    assert report['settlement']['pending_pairs'] == 1
    assert report['tables']['committee_records']['unreadable_files'] == []


@pytest.mark.parametrize('failure', ['missing', 'gzip', 'sha', 'body_limit', 'stored_limit', 'total_limit'])
def test_integrity_failures_stop_before_any_producer_or_syntax_decision(tmp_path, writer, monkeypatch, failure):
    rows = {name: [] for name in transition.MODULES}
    rows['committee_records'] = [empty('committee_records', BAD)]
    spec = make_spec(tmp_path, selected=rows, bodies=[] if failure == 'missing' else [BAD])
    job = spec['house_xml_disposition']
    raw = Path(job['raw_root']) / 'bodies' / 'sha256' / digest(BAD)[:2] / (digest(BAD) + '.gz')
    if failure == 'gzip':
        raw.write_bytes(raw.read_bytes()[:-3])
    if failure == 'sha':
        raw.write_bytes(gzip.compress(b'different'))
    if failure.endswith('_limit'):
        job['limits'][{'body_limit': 'max_body_bytes', 'stored_limit': 'max_stored_bytes',
                       'total_limit': 'max_total_decoded_bytes'}[failure]] = 1
    monkeypatch.setattr(transition, 'stage_selected_records', lambda *a, **kw: pytest.fail('producer reached bad storage'))
    with pytest.raises((ValueError, EOFError, gzip.BadGzipFile)):
        execute(spec)
    assert not list(Path(spec['work']).rglob('unreadable-decisions.jsonl'))


def test_duplicate_selected_keys_are_refused(tmp_path, writer):
    rows = {name: [] for name in transition.MODULES}
    rows['committee_records'] = [empty('committee_records', BAD)] * 2
    spec = make_spec(tmp_path, selected=rows, bodies=[BAD])
    from docspec_client.models import DocSpecFailure
    with pytest.raises((ValueError, DocSpecFailure), match='duplicate|unique|Duplicate'):
        execute(spec)


def test_total_stored_bytes_are_bounded_across_objects(tmp_path, writer, monkeypatch):
    rows = {name: [] for name in transition.MODULES}
    rows['committee_records'] = [empty('committee_records', body) for body in [BAD, RESOLUTION]]
    spec = make_spec(tmp_path, selected=rows, bodies=[BAD, RESOLUTION])
    job = spec['house_xml_disposition']
    sizes = [path.stat().st_size for path in Path(job['raw_root']).rglob('*.gz')]
    job['limits']['max_stored_bytes'] = max(sizes)  # each fits individually, both do not
    monkeypatch.setattr(transition, 'stage_selected_records', lambda *a, **kw: pytest.fail('producer exceeded stored budget'))
    with pytest.raises(ValueError, match='stored body exceeds'):
        execute(spec)


def test_largest_body_pilot_keeps_selected_rows_resident_and_only_parses_named_body(tmp_path, writer):
    spec = cohort(tmp_path)
    spec['house_xml_disposition']['pilot_body'] = digest(BAD)
    report = execute(spec)
    assert report['status'] == 'local_pilot' and report['resident_selected_rows'] == 8
    assert set(report['integrity']['bodies']) == {digest(BAD)}
    assert set(report['tables']) == {'meeting_records', 'committee_records'}
    assert all(stage['unreadable'] == 1 and stage['reused'] == 0 and 'producer' not in stage
               for stage in report['tables'].values())
    assert report['settlement']['settled_work_items'] == 0


def test_resume_keeps_each_completed_body_qualification(tmp_path, writer, monkeypatch):
    rows = {name: [] for name in transition.MODULES}
    rows['committee_records'] = [empty('committee_records', body) for body in [BAD, RESOLUTION]]
    spec = make_spec(tmp_path, selected=rows, bodies=[BAD, RESOLUTION])
    qualify = transition._qualify_body
    called = []

    def interrupted(key, *args):
        called.append(key)
        if len(called) == 2:
            raise RuntimeError('interrupted after one completed body')
        return qualify(key, *args)

    monkeypatch.setattr(transition, '_qualify_body', interrupted)
    with pytest.raises(RuntimeError, match='interrupted'):
        execute(spec)
    held = called[0]
    spec['house_xml_disposition']['resume'] = True

    def resumed(key, *args):
        assert key != held, 'reopened an already qualified body'
        return qualify(key, *args)

    monkeypatch.setattr(transition, '_qualify_body', resumed)
    assert execute(spec)['tables']['committee_records']['unreadable'] == 1


def test_mismatched_origin_is_refused_before_raw_read(tmp_path, writer, monkeypatch):
    spec = make_spec(tmp_path)
    job = spec['house_xml_disposition']
    origin_pin = job['origins']['meeting_records']
    path = Path(origin_pin['path'])
    value = json.loads(path.read_text())
    value['selector']['sha256'] = '00' * 32
    path.write_text(json.dumps(value))
    job['origins']['meeting_records'] = pin(path)
    monkeypatch.setattr(transition, '_qualify_body', lambda *a, **kw: pytest.fail('opened raw before provenance'))
    with pytest.raises(ValueError, match='producer refused'):
        execute(spec)


def test_unsupported_operations_and_pins_remain_guarded(tmp_path):
    spec = make_spec(tmp_path)
    value = dict(spec, house_xml_version_transition={})
    with pytest.raises(ValueError):
        transition.load_dispositions(value, base=tmp_path)
    spec['house_xml_disposition']['limits']['max_body_bytes'] = 0
    with pytest.raises(ValueError, match='positive finite'):
        transition.load_dispositions(spec, base=tmp_path)

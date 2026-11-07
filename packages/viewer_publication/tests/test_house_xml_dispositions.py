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
HOUSE_ORIGIN = '742dbe70b42f0618e95816cd7cf0e6ba2f9939b0'
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

    # This fixture replays the historical House-only change. Its pinned
    # predecessor never produced later Senate or MODS generations.
    from viewer_publication import producer_proof
    versions_at = producer_proof.versions_at
    historical = versions_at(HOUSE_ORIGIN)['appearance_records']
    house_version = transition.appearance_records.current_versions()['house_xml']
    house_fixture_versions = dict(historical, house_xml=house_version)
    monkeypatch.setattr(transition.appearance_records, 'current_versions', lambda **kw: dict(house_fixture_versions))

    def fixture_versions_at(revision, **kw):
        versions = versions_at(revision, **kw)
        if revision == commit:
            return dict(versions, appearance_records=dict(house_fixture_versions))
        return versions

    monkeypatch.setattr(producer_proof, 'versions_at', fixture_versions_at)
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
            commit=HOUSE_ORIGIN, lockfile_digest=file_pin(transition.ROOT / 'uv.lock')['sha256'])))
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


def activation_fixture(tmp_path, writer, monkeypatch, *, conflict=False):
    """Small native analogue; production count guards remain fixed in the caller."""
    from congress_api.lake import daily, tables
    from docspec_client.client import NativeDatasets
    from viewer_publication import archive_house_xml_activation as activation
    from viewer_publication.producer_proof import IMPORT

    monkeypatch.setattr(daily, 'writer_identity', lambda root, job: dict(writer, job=job))
    selected = {name: [] for name in transition.MODULES}
    selected['meeting_records'] = [meeting_records.build_meeting_record_row(digest(GOOD), 'house_xml', GOOD,
        parser_version=transition.OLD['meeting_records']), empty('meeting_records', RESOLUTION)]
    selected['appearance_records'] = [transition.appearance_records.build_appearance_record_row(digest(WITNESSES),
        'house_xml', WITNESSES, parser_version=transition.OLD['appearance_records'])]
    selected['committee_records'] = [transition.committee_records.build_row(digest(body), 'house_xml', body,
        parser_version=transition.OLD['committee_records']) for body in [GOOD, WITNESSES]]
    selected['committee_records'] += [empty('committee_records', body) for body in [RESOLUTION, AMP]]
    spec = make_spec(tmp_path, selected=selected, bodies=[RESOLUTION, AMP])
    job = spec['house_xml_disposition']
    raw = Path(job['raw_root'])
    for number in range(31):
        row = unreadable_decision('fixture', 'prior', f'{number+1:064x}', ValueError(), STAMP)
        key = f'provenance/unreadable/fixture-{number}.jsonl'
        path = raw / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + '\n')
        job['unreadable_files'].append(dict(key=key, **pin(path)))
    catalog = tmp_path / 'catalog'
    targets = {name: dict(namespace=['house'], name=name) for name in transition.MODULES}
    anchors = {}
    with NativeDatasets.from_config(spec['engine_config']) as engine:
        engine.verify_runtime()
        for index, (name, module) in enumerate(transition.MODULES.items()):
            path = tmp_path / (name + '.parquet')
            rows = pq.read_table(path).to_pylist()
            historical = dict(rows[0], record_sha=bytes.fromhex('99' * 32), parser_version='historical')
            rows.append(historical)
            if conflict and name == 'meeting_records':
                held = next(row for row in rows if row['record_sha'] == bytes.fromhex(digest(GOOD)))
                assert held['meetings']
                rows.append(dict(held, parser_version=transition.NEW[name], meetings=[]))
            pq.write_table(module.table(rows), path)
            source = dict(kind='parquet', **pin(path))
            module.create_table(engine=engine, work=tmp_path / ('create-' + name), catalog_root=catalog,
                table=targets[name], location=str(tmp_path / 'warehouse' / name), create_namespace=index == 0)
            tables.append_rows(path, engine=engine, work=tmp_path / ('base-' + name), catalog_root=catalog,
                table=targets[name], keys=list(tables.TABLE_SPECS[name]['primary_key']), definition='synthetic old base')
            head = tables.resolve_tables(engine=engine, work=tmp_path / ('resolve-' + name), catalog_root=catalog,
                tables={name: targets[name]})[name]
            selector = dict(kind='native_table', **head)
            origin = dict(version=1, input=name, selector=source, job=BACKFILL,
                commit=HOUSE_ORIGIN, lockfile_digest=writer['lockfile_digest'])
            anchor = dict(version=1, input=name, selector=selector, job=IMPORT,
                commit=origin['commit'], lockfile_digest=origin['lockfile_digest'], source={k: v for k, v in source.items() if k != 'kind'},
                origin=dict(record=origin))
            anchor_path = tmp_path / (name + '.anchor.json')
            anchor_path.write_text(json.dumps(anchor, indent=1, sort_keys=True) + '\n')
            anchors[name] = pin(anchor_path)
            job['bases'][name] = selector
            job['origins'][name] = pin(anchor_path)
    # A retained selected success outside the fresh-fetch set must still activate.
    keys_pin = job['candidates']['meeting_records']
    keys = pq.read_table(keys_pin['path'])
    pq.write_table(keys.filter(pc.not_equal(keys['record_sha'], digest(GOOD))), keys_pin['path'])
    job['candidates']['meeting_records'] = pin(keys_pin['path'])
    census_path = Path(job['census']['path'])
    census = json.loads(census_path.read_text())
    census['selectors'] = job['bases']
    census['tables']['meeting_records']['K_base'] -= 1
    census_path.write_text(json.dumps(census))
    job['census'] = pin(census_path)
    staged = execute(spec)
    assert all(stage['unreadable'] == 0 and stage['pending'] == 0 for stage in staged['tables'].values())
    expected = {name: {key: stage[key] for key in ('selected', 'reused', 'produced')} for name, stage in staged['tables'].items()}
    monkeypatch.setattr(activation, 'EXPECTED', expected)
    path = tmp_path / 'activate.json'
    path.write_text(json.dumps(dict(version=1, work=str(tmp_path / 'activate'), engine_config=spec['engine_config'],
        house_xml_activation=dict(cohort=pin(Path(spec['work']) / 'state.json'), tables=targets, anchors=anchors,
            catalog_root=str(catalog), raw_root=str(raw), bucket=None, decided_at=STAMP, resume=False,
            max_output_bytes=32 << 20, min_disk_bytes=1))))
    return load_spec(path), staged


def activate(spec):
    # Synthetic in-process fault injection keeps the isolated catalog lock in
    # pytest. The production API/CLI uses the owned launcher; its lifetime has a
    # separate real-process test below.
    from viewer_publication.archive_house_xml_activation import _activation_lock
    with _activation_lock(spec['house_xml_activation']['catalog_root']) as fd:
        return execute(spec, activation_lock_fd=fd)


def test_activation_preserves_values_and_outside_fetch_rows_then_next_daily_chain(tmp_path, writer, monkeypatch):
    from congress_api.lake import daily, tables
    from congress_api.lake.producer_records import ProducerRecords, DAILY_JOB
    from congress_api.retention.body_store import BodyStore
    from docspec_client.client import NativeDatasets
    from viewer_publication.producer_proof import snapshot_reasons

    spec, staged = activation_fixture(tmp_path, writer, monkeypatch)
    monkeypatch.setattr(BodyStore, 'put', lambda *a, **kw: pytest.fail('zero-refusal activation imported raw data'))
    first = activate(spec)
    assert first['status'] == 'activated' and first['receipts_unchanged'] is True
    assert first['new_unreadable_files'] == [] and len(first['unreadable_files']) == 31
    job = spec['house_xml_activation']
    records = ProducerRecords({name: Path(item['path']).read_bytes() for name, item in job['anchors'].items()}, root=job['raw_root'])
    heads = {name: {k: v for k, v in item.items() if k != 'kind'} for name, item in first['pins'].items()}
    for name, item in first['producers'].items():
        head_record = json.loads(Path(item['path']).read_text())
        assert head_record['job'] == DAILY_JOB and 'delta_only' not in head_record
        source_origin = json.loads(Path(staged['tables'][name]['producer']['path']).read_text())
        assert source_origin['delta_only'] is True
        assert head_record['house_xml_transition']['delta_producer'] == staged['tables'][name]['producer']
    with NativeDatasets.from_config(spec['engine_config']) as engine:
        # Test the next daily append chain through the activation to the import anchor.
        chain, refusal = daily._producer_bases(records, heads)
        assert refusal is None
        extra = tmp_path / 'next.parquet'
        row = meeting_records.build_meeting_record_row('55' * 32, 'house_xml', GOOD)
        pq.write_table(meeting_records.table([row]), extra)
        meeting_records.append(dict(records=extra, parser_version=meeting_records.current_versions()), engine=engine,
            work=tmp_path / 'next-append', catalog_root=job['catalog_root'], table=job['tables']['meeting_records'])
        after = tables.resolve_tables(engine=engine, work=tmp_path / 'next-head', catalog_root=job['catalog_root'], tables=job['tables'])
        daily._record_moved(records, chain, heads, after, decided_at=STAMP)
        model = dict(**{name: dict(kind='native_table', **head) for name, head in after.items()},
            parser_versions={name: module.current_versions() for name, module in transition.MODULES.items()})
        assert snapshot_reasons(model, {name: records.find(name, head)[0] for name, head in after.items()}, ledger=records) == []
        # Historical rows and the outside-fetch selected row remain physically present.
        from congress_api.retention.provenance import run_job
        data = run_job(tmp_path / 'contents', engine, inputs=[tables.table_input('t', after['meeting_records'])], steps=[], outputs=[],
            queries=[dict(name='rows', sql="SELECT encode(record_sha,'hex') AS sha,parser_version FROM t ORDER BY sha,parser_version")])['rows']
        assert dict(sha=digest(GOOD), parser_version=transition.NEW['meeting_records']) in data
        assert dict(sha='99' * 32, parser_version='historical') in data


def test_activation_resume_does_not_append_duplicate_rows(tmp_path, writer, monkeypatch):
    from congress_api.lake import daily
    spec, _ = activation_fixture(tmp_path, writer, monkeypatch)
    first = activate(spec)
    for module in (daily.meeting_records, daily.appearance_records, daily.committee_records):
        monkeypatch.setattr(module, 'append', lambda *a, **kw: pytest.fail('reappended completed activation'))
    spec['house_xml_activation']['resume'] = True
    assert activate(spec)['pins'] == first['pins']


def test_appearance_activation_appends_two_generations_in_one_snapshot_and_resumes(tmp_path, writer, monkeypatch):
    from congress_api.lake import daily, tables
    from congress_api.lake.producer_records import ProducerRecords
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    from docspec_client.client import NativeDatasets
    from viewer_publication import archive_house_xml_activation as activation
    from viewer_publication.producer_proof import snapshot_reasons

    spec, _ = activation_fixture(tmp_path, writer, monkeypatch)
    job = spec['house_xml_activation']
    prepared = activation.prepare_activation(job['cohort'])
    name = 'appearance_records'
    versions = daily.appearance_records.current_versions()
    records_path = tmp_path / 'mods.parquet'
    staged_versions = {key: versions[key] for key in ('mods', 'senate_page')}
    rows = daily.appearance_records.table([
        dict(record_sha=digest(source.encode()), source=source,
             parser_version=version, status='completed', appearances=[])
        for source, version in staged_versions.items()
    ])
    pq.write_table(rows, records_path)
    prepared['tables'] = {name: dict(prepared['tables'][name], records=pin(records_path), versions=staged_versions)}
    raw = Path(job['raw_root'])
    records = ProducerRecords({key: Path(value['path']).read_bytes() for key, value in job['anchors'].items()}, root=raw)
    work = tmp_path / 'mods-activate'
    with NativeDatasets.from_config(spec['engine_config']) as engine, activation._activation_lock(job['catalog_root']):
        initial = tables.resolve_tables(engine=engine, work=tmp_path/'mods-before', catalog_root=job['catalog_root'],
                                        tables=job['tables'])
        args = dict(engine=engine, raw_store=BodyStore(LocalAdapter(raw)), producer_records=records,
                    catalog_root=job['catalog_root'], targets={name: job['tables'][name]}, work=work,
                    decided_at=STAMP, max_output_bytes=32 << 20, min_disk_bytes=1)
        result = daily.activate_appearance_generations(prepared, resume=False, **args)
        final = tables.resolve_tables(engine=engine, work=tmp_path/'mods-after', catalog_root=job['catalog_root'],
                                      tables=job['tables'])
        assert set(result['pins']) == {name}
        assert result['pins'][name] == dict(kind='native_table', **final[name])
        assert final[name] != initial[name]
        assert all(final[key] == head for key, head in initial.items() if key != name)
        head, _ = records.find(name, final[name])
        assert head['appearance_transition']['records'] == pin(records_path)
        assert not snapshot_reasons(dict(result['pins'], parser_versions={name: versions}), {name: head}, ledger=records)
        monkeypatch.setattr(daily.appearance_records, 'append', lambda *a, **kw: pytest.fail('reappended completed appearance generations'))
        assert daily.activate_appearance_generations(prepared, resume=True, **args)['pins'] == result['pins']


def test_activation_completion_requires_final_proof_and_preserves_prior_success(tmp_path, writer, monkeypatch):
    from congress_api.lake import daily
    from viewer_publication import archive_house_xml_activation as activation
    spec, _ = activation_fixture(tmp_path, writer, monkeypatch)
    proof = activation.snapshot_reasons
    monkeypatch.setattr(activation, 'snapshot_reasons', lambda *a, **kw: ['planted chain-proof refusal'])
    completion = Path(spec['work']) / 'activation-complete.json'
    with pytest.raises(ValueError, match='producer chain refused'):
        activate(spec)
    state = json.loads((Path(spec['work']) / 'activation.json').read_text())
    assert state['status'] == 'appended' and state['result']['status'] == 'appended'
    assert 'producer_chain_verified' not in state['result'] and not completion.exists()
    for module in (daily.meeting_records, daily.appearance_records, daily.committee_records):
        monkeypatch.setattr(module, 'append', lambda *a, **kw: pytest.fail('reappended after a reporting refusal'))
    monkeypatch.setattr(activation, 'snapshot_reasons', proof)
    spec['house_xml_activation']['resume'] = True
    result = activate(spec)
    assert result['status'] == 'activated' and result['producer_chain_verified'] is True
    assert json.loads(completion.read_text()) == result
    assert result['anchors'] == spec['house_xml_activation']['anchors']
    retained = pin(completion)
    monkeypatch.setattr(activation, 'snapshot_reasons', lambda *a, **kw: ['later failed recheck'])
    with pytest.raises(ValueError, match='producer chain refused'):
        activate(spec)
    assert pin(completion) == retained


def test_activation_lost_append_response_keeps_head_and_resumes_other_tables(tmp_path, writer, monkeypatch):
    from congress_api.lake import daily
    spec, _ = activation_fixture(tmp_path, writer, monkeypatch)
    append = daily.meeting_records.append

    def lost(*args, **kwargs):
        append(*args, **kwargs)
        raise RuntimeError('lost append response')

    monkeypatch.setattr(daily.meeting_records, 'append', lost)
    with pytest.raises(RuntimeError, match='lost append response'):
        activate(spec)
    state = json.loads((Path(spec['work']) / 'activation.json').read_text())
    assert state['completed'] == ['meeting_records'] and 'result' not in state
    held = state['heads']['meeting_records']
    monkeypatch.setattr(daily.meeting_records, 'append', lambda *a, **kw: pytest.fail('replayed committed first table'))
    spec['house_xml_activation']['resume'] = True
    assert activate(spec)['pins']['meeting_records'] == dict(kind='native_table', **held)


def test_activation_recovers_durable_intent_after_head_record_interruption(tmp_path, writer, monkeypatch):
    from congress_api.lake import daily
    spec, _ = activation_fixture(tmp_path, writer, monkeypatch)
    record_moved = daily._record_moved
    monkeypatch.setattr(daily, '_record_moved', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('head response interrupted')))
    with pytest.raises(RuntimeError, match='head response interrupted'):
        activate(spec)
    state = json.loads((Path(spec['work']) / 'activation.json').read_text())
    assert state['intent'] == ['meeting_records'] and state['completed'] == []
    monkeypatch.setattr(daily, '_record_moved', record_moved)
    monkeypatch.setattr(daily.meeting_records, 'append', lambda *a, **kw: pytest.fail('duplicated intent-owned append'))
    spec['house_xml_activation']['resume'] = True
    assert activate(spec)['status'] == 'activated'


def test_activation_reconciles_lost_ack_after_head_record_is_written(tmp_path, writer, monkeypatch):
    from congress_api.lake import daily
    from congress_api.lake.producer_records import ProducerRecords
    spec, _ = activation_fixture(tmp_path, writer, monkeypatch)
    write = ProducerRecords.write
    lost = False

    def committed_then_lost(records, record):
        nonlocal lost
        acknowledged = write(records, record)
        if not lost:
            lost = True
            raise RuntimeError('lost acknowledgment after immutable head write')
        return acknowledged

    monkeypatch.setattr(ProducerRecords, 'write', committed_then_lost)
    with pytest.raises(RuntimeError, match='lost acknowledgment'):
        activate(spec)
    state = json.loads((Path(spec['work']) / 'activation.json').read_text())
    assert state['completed'] == ['meeting_records']
    held = state['heads']['meeting_records']
    assert len(list((Path(spec['house_xml_activation']['raw_root']) / 'lake/producers').rglob('*.json'))) == 1
    monkeypatch.setattr(daily.meeting_records, 'append', lambda *a, **kw: pytest.fail('reappended an acknowledged head'))
    spec['house_xml_activation']['resume'] = True
    assert activate(spec)['pins']['meeting_records'] == dict(kind='native_table', **held)


def test_activation_semantic_collision_refuses_before_head_records(tmp_path, writer, monkeypatch):
    spec, _ = activation_fixture(tmp_path, writer, monkeypatch, conflict=True)
    with pytest.raises(ValueError, match='conflict with the staged values'):
        activate(spec)
    assert not list((Path(spec['house_xml_activation']['raw_root']) / 'lake/producers').rglob('*.json'))


@pytest.mark.parametrize('failure', ['head_drift', 'refusal_drift', 'new_refusal', 'production_counts'])
def test_activation_preflight_rejects_changed_scope_without_shared_effects(tmp_path, writer, monkeypatch, failure):
    from congress_api.lake import daily, tables
    from docspec_client.client import NativeDatasets
    from viewer_publication import archive_house_xml_activation as activation
    production_counts = dict(meeting_records=dict(selected=6183, reused=6182, produced=1),
        appearance_records=dict(selected=3401, reused=3401, produced=0), committee_records=dict(selected=6238, reused=5654, produced=584))
    spec, _ = activation_fixture(tmp_path, writer, monkeypatch)
    job = spec['house_xml_activation']
    if failure == 'head_drift':
        extra = tmp_path / 'drift.parquet'
        pq.write_table(meeting_records.table([dict(empty('meeting_records', BAD), record_sha='44' * 32)]), extra)
        with NativeDatasets.from_config(spec['engine_config']) as engine:
            tables.append_rows(extra, engine=engine, work=tmp_path / 'drift', catalog_root=job['catalog_root'],
                table=job['tables']['meeting_records'], keys=list(tables.TABLE_SPECS['meeting_records']['primary_key']), definition='unrelated drift')
    elif failure == 'refusal_drift':
        extra = Path(job['raw_root']) / 'provenance/unreadable/extra.jsonl'
        extra.write_text(json.dumps(unreadable_decision('fixture', 'other', '33' * 32, ValueError(), STAMP)) + '\n')
    elif failure == 'new_refusal':
        path = Path(job['cohort']['path'])
        value = json.loads(path.read_text())
        value['report']['tables']['meeting_records']['unreadable'] = 1
        path.write_text(json.dumps(value))
        job['cohort'] = pin(path)
    else:
        monkeypatch.setattr(activation, 'EXPECTED', production_counts)
    for module in (daily.meeting_records, daily.appearance_records, daily.committee_records):
        monkeypatch.setattr(module, 'append', lambda *a, **kw: pytest.fail('preflight issued an append'))
    with pytest.raises(ValueError):
        activate(spec)
    assert not list((Path(job['raw_root']) / 'lake/producers').rglob('*.json'))


def test_activation_owned_launcher_keeps_lock_until_descendants_stop_after_death(tmp_path):
    import fcntl
    import signal
    import sys
    import time

    parent_marker = tmp_path / 'watchdog.pid'
    child_marker = tmp_path / 'native.pid'
    worker = ("import signal,os,pathlib,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
              f"pathlib.Path({str(child_marker)!r}).write_text(str(os.getpid()));time.sleep(60)")
    fake_activation = f"import subprocess,sys;subprocess.run([sys.executable,'-c',{worker!r}])"
    # Exercise the production supervisor and inherited-FD command builder, replacing
    # only the expensive worker with an inert process that ignores termination.
    code = f'''
from pathlib import Path
import subprocess,sys
from viewer_publication import archive_house_xml_activation as activation
original=activation._activation_command
def command(spec,invocation,fd):
    args=original(spec,invocation,fd)
    assert '--hold-fd' in args and '--activation-lock-fd' in args
    assert args[args.index('--interval')+1]=='0.2'
    args[args.index('--expect-gb')+1]='0.05'
    args[args.index('--start-available-gb')+1]='0'
    args[args.index('--min-disk-gb')+1]='0'
    cut=args.index('--')
    args[cut+1:]=[sys.executable,'-c',{fake_activation!r}]
    return args
def run(args,**kwargs):
    process=subprocess.Popen(args,**kwargs)
    Path({str(parent_marker)!r}).write_text(str(process.pid))
    return subprocess.CompletedProcess(args,process.wait())
activation._activation_command=command
activation.subprocess.run=run
activation.execute_activation(dict(work={str(tmp_path / 'activation')!r},
    house_xml_activation=dict(catalog_root={str(tmp_path / 'catalog')!r})))
'''
    environment = dict(os.environ, ARCHIVE_WATCHDOG_STATE=str(tmp_path / 'watchdog-state'))
    launcher = subprocess.Popen([sys.executable, '-c', code], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def marker(path):
        deadline = time.monotonic() + 20
        while not path.exists() or not path.read_text():
            assert launcher.poll() is None, 'activation launcher exited before its child started'
            assert time.monotonic() < deadline, 'owned activation child did not start'
            time.sleep(0.05)
        return int(path.read_text())

    watchdog_pid = native_pid = None
    try:
        watchdog_pid = marker(parent_marker)
        native_pid = marker(child_marker)
        launcher.kill()
        launcher.wait(timeout=10)
        with (tmp_path / 'house-activation.lock').open('a') as retry:
            with pytest.raises(BlockingIOError):
                fcntl.flock(retry, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # The existing owned guardian retains the FD even after its watchdog
            # is killed, until the native descendant has actually stopped.
            os.kill(watchdog_pid, signal.SIGKILL)
            with pytest.raises(BlockingIOError):
                fcntl.flock(retry, fcntl.LOCK_EX | fcntl.LOCK_NB)
            deadline = time.monotonic() + 15
            while True:
                try:
                    os.kill(native_pid, 0)
                except ProcessLookupError:
                    break
                assert time.monotonic() < deadline, 'native descendant outlived owned-process cleanup'
                time.sleep(0.05)
            fcntl.flock(retry, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.wait(timeout=10)
        for pid in (watchdog_pid, native_pid):
            if pid is not None:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

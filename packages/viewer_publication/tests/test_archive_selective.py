"""Selective backfill on real producers. Expectations come from injected facts, not this code."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive_job_fixture import selective_base,selective_spec
from congress_api.lake import appearance_records,captures,committee_records,meeting_records,video_records
from congress_api.lake.capture_backfill_guard import GenerationViolation
from congress_api.lake.filenames import current_version as catalog_version
from congress_api.retention.provenance import parquet_output,run_job
from docspec_client.client import NativeDatasets
from native_test_helpers import compatible_entry
from viewer_publication.archive_backfill_job import execute
from viewer_publication.archive_selective_records import SelectiveStop

B="receipt_key LIKE '%/b.jsonl.gz' AND receipt_line=1"
BOTH="receipt_key LIKE '%/b%.jsonl.gz'"
PK={'captures':list(captures.PK),'readings':['body_sha','parser','parser_version'],'filename_readings':['filename','source_url','catalog_version'],
    'meeting_records':['record_sha','source','parser_version'],'appearance_records':['record_sha','source','parser_version']}


@pytest.fixture(scope='module')
def fixture(tmp_path_factory):
    return selective_base(tmp_path_factory.mktemp('selective-base'))


def changed(tmp_path,fixture,name,update):
    """A base table with `update(rows)` applied, written beside the test."""
    table=pq.read_table(fixture['base'][name]);rows=table.to_pylist();update(rows)
    path=tmp_path/('stale-'+name+'.parquet');pq.write_table(pa.Table.from_pylist(rows,schema=table.schema),path)
    return str(path)


def on_receipt(rows,suffix):
    return [row for row in rows if row['receipt_key'].endswith(suffix)]


def head(spec,name):
    """The final table's rows, read through the catalog."""
    state=json.loads((Path(spec['work'])/'state.json').read_text());work=Path(spec['work'])/('read-'+name+os.urandom(4).hex())
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        run_job(work,engine,inputs=[dict(name='t',kind='native_table',**state['pins'][name])],steps=[],
            outputs=[parquet_output(work,'rows','SELECT * FROM t',PK.get(name,['record_sha','source','parser_version']))])
    return pq.read_table(work/'rows.parquet').to_pylist()


def sorted_rows(rows):
    return sorted(rows,key=lambda row:repr(sorted(row.items(),key=lambda item:item[0])))


def test_filename_transition_reuses_values_and_records_the_producer(tmp_path, monkeypatch):
    from datetime import date
    from congress_api.lake import filenames, tables
    from viewer_publication.archive_backfill_job import FILENAME_ACT_CITATION_VERSION, FILENAME_PRIOR_VERSION, load_spec
    from viewer_publication.producer_proof import snapshot_reasons, versions_at

    # Rehearse the historical Act-citation endpoint; attributing it to a later HEAD refuses.
    assert filenames.current_version() != FILENAME_ACT_CITATION_VERSION
    monkeypatch.setattr(filenames, 'current_version', lambda: FILENAME_ACT_CITATION_VERSION)

    runtime = os.environ['DOCSPEC_JOB_CONFIG']
    catalog = tmp_path / 'base-catalog'
    table = dict(namespace=['fixture'], name='filename_readings')
    eps = 'FP Opening Statement--EPS Improvement Act of 2016 1-12-16.pdf'
    afwa = 'AFWA testimony_H.R. 2264_Bear Protection Act of 2019_6-23-20_final.pdf'
    unaffected = dict(filenames.read_filename('Opening Statement 20160112.pdf', '', catalog_version=FILENAME_PRIOR_VERSION),
                      date_token='retained reading')
    old_rows = [unaffected,
                dict(filenames.read_filename(eps, '', catalog_version=FILENAME_PRIOR_VERSION), date_token='2016 1-12'),
                dict(filenames.read_filename(afwa, '', catalog_version=FILENAME_PRIOR_VERSION),
                     date_token='2019_6-23', filename_date=date(2019, 6, 23))]
    path = tmp_path / 'old-rows.parquet'
    pq.write_table(pa.Table.from_pylist(old_rows, schema=filenames.SCHEMA), path)
    with NativeDatasets.from_config(runtime) as engine:
        filenames.create_table(engine=engine, work=tmp_path / 'create', catalog_root=catalog, table=table,
                               location=tmp_path / 'base-table', create_namespace=True)
        filenames.append(dict(catalog_version=FILENAME_PRIOR_VERSION, readings=path), engine=engine,
                         work=tmp_path / 'append', catalog_root=catalog, table=table)
        base = tables.resolve_tables(engine=engine, work=tmp_path / 'resolve', catalog_root=catalog,
                                     tables={'filename_readings': table})['filename_readings']
    work = tmp_path / 'transition'
    spec_file = tmp_path / 'transition.json'
    spec_file.write_text(json.dumps(dict(version=1, work=str(work), engine_config=runtime,
        filename_transition=dict(base=dict(kind='native_table', **base), engine_config=runtime))))
    report = execute(load_spec(spec_file))
    assert report['rows'] == 3 and report['reused'] == 1 and report['recomputed'] == 2
    rows = {row['filename']: row for row in pq.read_table(work / 'check' / 'filename-readings.parquet').to_pylist()}
    assert rows[unaffected['filename']] == dict(unaffected, catalog_version=FILENAME_ACT_CITATION_VERSION)
    assert (rows[eps]['date_token'], rows[eps]['filename_date']) == ('1-12-16', date(2016, 1, 12))
    assert (rows[afwa]['date_token'], rows[afwa]['filename_date']) == ('6-23-20', None)
    producer = json.loads(Path(report['producer']['path']).read_text())
    producing_commit = producer['commit']
    model = dict(filename_readings=report['selector'], catalog_version=report['catalog_version'], parser_versions={})
    expected = ([] if versions_at(producing_commit)['filename_readings'] == FILENAME_ACT_CITATION_VERSION else [
        f'producer proof: filename_readings: the code at {producing_commit[:12]} computes another version than the pinned rows carry'
    ])
    assert snapshot_reasons(model, {'filename_readings': producer}) == expected


@pytest.mark.parametrize('basename,refused', [
    ('Protection%20Act%20of%202019.pdf', False),
    ('Protection_Act%5Fof_2019_6-23-20.pdf', True),
])
def test_house_xml_transition_checks_the_normalized_consumer_input(basename, refused):
    from viewer_publication.archive_house_xml_transition import NEW, OLD, _advance_rows

    source = ['house_xml', 'congress_gov']
    urls = ['https://example.test/' + basename + '?Act_of_2019=ignored']
    rows = pa.table(dict(record_sha=[b'house', b'congress'], source=source,
        parser_version=[OLD[s] for s in source], status=['completed', 'completed'],
        meetings=[[dict(document_urls=urls)], [dict(document_urls=[])]]))
    if refused:
        with pytest.raises(ValueError, match='requires replay'):
            _advance_rows(rows)
        return
    updated, counts = _advance_rows(rows)
    assert updated['parser_version'].to_pylist() == [NEW[s] for s in source]
    assert updated.drop_columns(['parser_version']).equals(rows.drop_columns(['parser_version']))
    assert counts == dict(rows=2, house_xml=1, congress_gov=1, urls_checked=1)


@pytest.mark.parametrize('change,message',[
    (dict(catalog_root=None),'local catalog_root'),
    (dict(tables={name:dict(namespace=['archive'],name=name) for name in ('captures','readings','filename_readings','meeting_records','appearance_records')}),'archive namespace'),
])
def test_refuses_unsafe_targets_before_any_effect(tmp_path,fixture,change,message):
    with pytest.raises(ValueError,match=message):
        selective_spec(tmp_path,fixture,dict(captures=B),**change)
    assert not (tmp_path/'work').exists() and not (tmp_path/'catalog').exists()


@pytest.mark.parametrize('where,message',[
    (dict(readings='true'),'ct-pocg'),(dict(),'at least one predicate'),(dict(captures='true; DROP'),'semicolon'),
])
def test_refuses_bad_predicates_before_any_effect(tmp_path,fixture,where,message):
    with pytest.raises(ValueError,match=message):selective_spec(tmp_path,fixture,where)
    assert not (tmp_path/'work').exists()


def test_the_job_owns_model_output_while_a_pinned_spicy_regs_is_accepted(tmp_path,fixture):
    # Contract: the selective job owns work/model-{output,scratch} (db7345c8); spicy-regs is a pin (925036be).
    from viewer_publication.archive_backfill_job import load_spec
    spec=selective_spec(tmp_path,fixture,dict(captures=B))
    pinned=spec['selective']['model']['spicy_regs']
    assert set(pinned)=={'path','sha256','size'} and Path(pinned['path']).is_file()
    path=tmp_path/'spec.json';value=json.loads(path.read_text())
    value['selective']['model']['output']=str(tmp_path/'caller-output');path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='the job owns work/model'):load_spec(path)
    assert not (tmp_path/'work').exists()


def test_refuses_a_digest_mismatch_and_absent_raw_root_before_any_effect(tmp_path,fixture):
    spec=selective_spec(tmp_path/'digest',fixture,dict(captures=B))
    spec['selective']['base']['captures']['sha256']='0'*64
    with pytest.raises(ValueError,match='does not match its pin'):execute(spec)
    assert not Path(spec['work']).exists()
    moved=dict(fixture,raw=tmp_path/'absent')
    with pytest.raises(ValueError,match='raw_root is absent'):selective_spec(tmp_path/'raw',moved,dict(captures=B))


def test_a_pinned_input_manifest_must_match_before_any_effect(tmp_path,fixture):
    manifest=tmp_path/'manifest.json';manifest.write_text('{}')
    from congress_api.retention.provenance import file_pin
    spec=selective_spec(tmp_path,fixture,dict(captures=B))
    spec['selective']['input_manifest']=dict(path=str(manifest),**file_pin(manifest))
    manifest.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='does not match its pin'):execute(spec)
    assert not Path(spec['work']).exists()


def test_zero_hits_stops_before_any_table_exists(tmp_path,fixture):
    spec=selective_spec(tmp_path,fixture,dict(captures="receipt_key='absent'"))
    with pytest.raises(SelectiveStop,match='selects no rows'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_stale_unselected_record_rows_stop_before_any_table(tmp_path,fixture):
    # Defect guarded: re-stamping them with the current version, an unverified claim.
    def stale(rows):rows[0]['parser_version']='old'
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,
        base=dict(meeting_records=changed(tmp_path,fixture,'meeting_records',stale)))
    with pytest.raises(SelectiveStop,match='D3/D4 have no compatible versions'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_readings_at_an_uncovered_version_stop_before_any_table(tmp_path,fixture):
    def stale(rows):rows[0]['parser_version']='old'
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,
        base=dict(readings=changed(tmp_path,fixture,'readings',stale)))
    with pytest.raises(SelectiveStop,match='neither current nor in the compatible-versions registry'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_a_duplicate_base_primary_key_stops_before_any_table(tmp_path,fixture):
    def duplicate(rows):rows.append(dict(rows[0]))
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,
        base=dict(readings=changed(tmp_path,fixture,'readings',duplicate)))
    with pytest.raises(ValueError,match='duplicated before selection'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_covered_readings_are_copied_verbatim_at_their_old_versions(tmp_path,fixture,monkeypatch):
    from congress_api.lake import compatible_versions as cv
    pins=cv.current_pins()
    def relabel(rows):
        for row in rows:row['parser_version']='old-'+row['parser']
    registry=tmp_path/'registry.json'
    registry.write_text(json.dumps(dict(version=2,entries=[compatible_entry(p,'old-'+p,pins[p]) for p in cv.LEAF_PARSERS])))
    monkeypatch.setattr(cv,'REGISTRY',registry)
    base=changed(tmp_path,fixture,'readings',relabel)
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,base=dict(readings=base),through='tables')
    report=execute(spec)
    assert report['status']=='tables_built' and not (Path(spec['work'])/'candidate-model.json').exists()
    assert sorted_rows(head(spec,'readings'))==sorted_rows(pq.read_table(base).to_pylist())


def test_a_base_that_predates_a_nullable_column_seeds_null_and_reports_it_added(tmp_path,fixture):
    # Defect guarded: seeding and diffing every current schema column against a base written
    # before the column existed (v21 captures before mapping_version/original_path).
    table=pq.read_table(fixture['base']['captures']);old=tmp_path/'old-captures.parquet'
    pq.write_table(table.drop(['h_content_disposition']),old)
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,base=dict(captures=str(old)),through='tables')
    report=execute(spec)
    assert report['status']=='tables_built' and report['rebuilt_diff'].get('added_columns')==['h_content_disposition']
    rows=head(spec,'captures')
    assert all(row['h_content_disposition'] is None for row in rows if not row['receipt_key'].endswith('/b.jsonl.gz'))
    assert len(rows)==table.num_rows


def test_an_all_selected_table_seeds_nothing_without_reading_its_shape(tmp_path,fixture):
    table=pq.read_table(fixture['base']['captures']);old=tmp_path/'old-captures.parquet'
    pq.write_table(table.drop(['receipt_line_bytes'] if 'receipt_line_bytes' in table.column_names else ['h_content_disposition']),old)
    spec=selective_spec(tmp_path,fixture,dict(captures='true'),differential_rows=0,base=dict(captures=str(old)),through='tables')
    report=execute(spec)
    assert report['tables']['captures']['reused']==0 and report['tables']['captures']['selected']==table.num_rows


def test_d2_reads_missing_readings_from_the_local_mirror(tmp_path,fixture):
    # Defect guarded: _daily wrote an empty body inventory, so any D2 work stayed pending and
    # the run stopped "Daily producers stopped at pending". Existing cases had no D2 work.
    base=pq.read_table(fixture['base']['readings']).to_pylist()
    body=next(row['body_sha'] for row in base if row['parser']!='sniff')
    def missing(rows):rows[:]=[row for row in rows if row['body_sha']!=body]
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,base=dict(readings=changed(tmp_path,fixture,'readings',missing)),
        through='tables')
    assert execute(spec)['status']=='tables_built'
    reread={(row['parser'],row['status']) for row in head(spec,'readings') if row['body_sha']==body}
    assert reread=={(row['parser'],row['status']) for row in base if row['body_sha']==body}


def test_a_run_naming_the_explorer_tables_builds_them_from_its_captures(tmp_path,fixture,monkeypatch):
    # ct-gi01: video_records and committee_records had a producer but no job; the selective run
    # builds them in its completion pass so its model can write the five Explorer files.
    from congress_api.retention.provenance import file_pin
    import viewer_publication.archive_selective as selective
    monkeypatch.setattr(selective,'_writer',lambda run:dict(job=selective.PRODUCER_JOB,commit='a'*40,lockfile_digest='0'*64))
    names=('captures','readings','filename_readings','meeting_records','appearance_records','video_records','committee_records')
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,through='tables',
        tables={name:dict(namespace=['selective'],name=name) for name in names})
    decisions=tmp_path/'recording-decisions.jsonl'
    decisions.write_text(json.dumps(dict(id='a'*64,subject_kind='event',subject_id='118888',verdict='found',
        video_refs=['https://example.test/watch'],note=None,disputed_by=None,decided_at=None,supersedes=None))+'\n')
    template=Path(spec['selective']['model']['template']);model=json.loads(template.read_text())
    model['recording_decision_files']=[dict(key='provenance/recording_decisions/a.jsonl',path=str(decisions),**file_pin(decisions))]
    template.write_text(json.dumps(model))
    report=execute(spec)
    assert report['status']=='tables_built' and set(report['tables'])==set(names)
    for name,appended in {'video_records':0,'committee_records':2}.items():
        counts=dict(base=0,hits=0,selected=0,reused=0,appended=appended)
        assert report['completion'][name]['appended']==appended and report['tables'][name]==counts
        producer=json.loads(Path(report['producers'][name]['path']).read_text())
        assert (producer['reused_rows'],producer['appended'])==(0,appended)
    tables=report['tables']
    report=execute(dict(spec,resume=True,through='model'))
    assert report['status']=='built' and report['tables']==tables
    assert {'video_records','committee_records'}<=report['completion'].keys()
    state=json.loads((Path(spec['work'])/'state.json').read_text())
    candidate=json.loads((Path(spec['work'])/'candidate-model.json').read_text())
    for name in ('captures','video_records','committee_records'):
        assert candidate[name]==dict(kind='native_table',**state['pins'][name])
    assert candidate['parser_versions']['video_records']==video_records.current_versions()
    assert candidate['parser_versions']['committee_records']==committee_records.current_versions()
    written={path.name for path in Path(report['release']).glob('*.parquet')}
    assert {'meeting_coverage.parquet','videos.parquet','channels.parquet','recording_matches.parquet','committee_records.parquet'}<=written
    committee=head(spec,'committee_records')
    assert {row['event_id'] for row in committee}=={'118888',None}
    assert all(row['parser_version'] in set(committee_records.current_versions().values()) for row in committee)
    assert head(spec,'video_records')==[]


def test_fresh_explorer_run_refuses_a_preseeded_same_pin_target_before_production(tmp_path,fixture):
    names=('captures','readings','filename_readings','meeting_records','appearance_records','video_records','committee_records')
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,through='tables',
        tables={name:dict(namespace=['selective'],name=name) for name in names})
    source=tmp_path/'stale-video.parquet'
    row=video_records.build_row('ab'*32,video_records.SOURCE,b'{}',
        parser_version=video_records.current_versions()[video_records.SOURCE])
    pq.write_table(video_records.table([row]),source)
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        video_records.create_table(engine=engine,work=tmp_path/'create-stale',catalog_root=spec['catalog_root'],
            table=spec['tables']['video_records'],location=str(tmp_path/'stale-lake'),create_namespace=True)
        video_records.append(dict(records=str(source),parser_version=video_records.current_versions()),engine=engine,
            work=tmp_path/'append-stale',catalog_root=spec['catalog_root'],table=spec['tables']['video_records'])
    with pytest.raises(SelectiveStop,match='video_records.*already exists'):execute(spec)
    state=json.loads((Path(spec['work'])/'state.json').read_text())
    assert 'selection' not in state and 'daily' not in state and 'pins' not in state


def test_explorer_completion_recovers_counts_after_an_append_save_crash(tmp_path,fixture,monkeypatch):
    import viewer_publication.archive_selective as selective
    monkeypatch.setattr(selective,'_writer',lambda run:dict(job=selective.PRODUCER_JOB,commit='a'*40,lockfile_digest='0'*64))
    names=('captures','readings','filename_readings','meeting_records','appearance_records','video_records','committee_records')
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,through='tables',
        tables={name:dict(namespace=['selective'],name=name) for name in names})
    original=committee_records.append
    def crash_after_append(staged,**kwargs):
        original(staged,**kwargs)
        raise RuntimeError('injected crash after native append')
    monkeypatch.setattr(committee_records,'append',crash_after_append)
    with pytest.raises(RuntimeError,match='after native append'):execute(spec)
    state=json.loads((Path(spec['work'])/'state.json').read_text())
    assert 'committee_records' not in state['completion']
    monkeypatch.setattr(committee_records,'append',original)
    report=execute(dict(spec,resume=True))
    assert report['status']=='tables_built'
    assert report['completion']['committee_records']==dict(appended=2,sources={'house_xml':2})
    assert report['tables']['committee_records']['appended']==2 and len(head(spec,'committee_records'))==2
    producer=json.loads(Path(report['producers']['committee_records']['path']).read_text())
    assert (producer['reused_rows'],producer['appended'])==(0,2)


def test_narrow_fix_rebuilds_the_whole_receipt_and_reuses_the_rest_untouched(tmp_path,fixture):
    def stale(rows):
        on_receipt(rows,'/b.jsonl.gz')[0]['http_status']=299
        on_receipt(rows,'/a.jsonl.gz')[0]['http_status']=201
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,
        base=dict(captures=changed(tmp_path,fixture,'captures',stale)))
    report=execute(spec)
    assert report['status']=='built'
    rows=head(spec,'captures')
    assert [row['http_status'] for row in on_receipt(rows,'/b.jsonl.gz')]==[200,200]
    assert {row['http_status'] for row in on_receipt(rows,'/a.jsonl.gz')}=={200,201}
    assert len(rows)==sum(row['expected_captures'] for row in fixture['counts'])
    # One predicate hit expanded to its whole receipt; the guard cannot see this difference.
    assert report['tables']['captures']['hits']==1 and report['tables']['captures']['selected']==2
    assert report['rebuilt_diff']=={'http_status':1}
    assert (Path(spec['work'])/'candidate-model.json').is_file() and (Path(spec['work'])/'candidate-publish.json').is_file()


def test_null_predicate_rows_are_seeded_not_dropped(tmp_path,fixture):
    # True for one row and NULL for every other: a bare NOT would drop them all.
    spec=selective_spec(tmp_path,fixture,dict(filename_readings="CASE WHEN filename LIKE 'b-one%' THEN true END"),differential_rows=0)
    report=execute(spec)
    base=pq.ParquetFile(fixture['base']['filename_readings']).metadata.num_rows
    assert base>1 and report['tables']['filename_readings']['selected']==1
    assert len(head(spec,'filename_readings'))==base


def test_selected_records_recompute_and_unselected_are_copied_verbatim(tmp_path,fixture):
    meeting=meeting_records.current_versions()
    spec=selective_spec(tmp_path,fixture,dict(meeting_records="source='house_xml'",appearance_records="source='congress_gov'",filename_readings="filename LIKE 'b-one%'"))
    report=execute(spec)
    assert report['tables']['meeting_records']['appended']==report['tables']['meeting_records']['selected']>0
    assert {row['parser_version'] for row in head(spec,'meeting_records')}<=set(meeting.values())
    assert {row['catalog_version'] for row in head(spec,'filename_readings')}=={catalog_version()}
    assert report['tables']['filename_readings']['appended']==report['filenames_recomputed']
    for name in ('meeting_records','appearance_records','filename_readings'):
        assert sorted_rows(head(spec,name))==sorted_rows(pq.read_table(fixture['base'][name]).to_pylist())
    assert report['differential']['meeting_records'] and report['differential']['filename_readings']


def test_too_narrow_predicate_stops_naming_the_key_and_column(tmp_path,fixture):
    def sentinel(rows):on_receipt(rows,'/c.jsonl.gz')[0]['http_status']=201
    spec=selective_spec(tmp_path,fixture,dict(captures=B),base=dict(captures=changed(tmp_path,fixture,'captures',sentinel)))
    with pytest.raises(SelectiveStop,match=r'c\.jsonl\.gz.*differs in http_status'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_differential_stops_when_a_table_had_nothing_to_check(tmp_path,fixture):
    spec=selective_spec(tmp_path,dict(fixture,inventory=[row for row in fixture['inventory'] if row['key'].endswith('/b.jsonl.gz')]),dict(captures=B))
    with pytest.raises(SelectiveStop,match='no unselected receipt'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_rows_recomputed_but_absent_from_base_also_stop(tmp_path,fixture):
    def lost(rows):rows.remove(on_receipt(rows,'/m.jsonl.gz')[0])
    spec=selective_spec(tmp_path,fixture,dict(captures=B),base=dict(captures=changed(tmp_path,fixture,'captures',lost)))
    with pytest.raises(SelectiveStop,match='recomputed but not in base'):execute(spec)


def test_wrong_independent_count_fails_closed(tmp_path,fixture):
    counts=[dict(row,expected_captures=row['expected_captures']+1,list_items=row['list_items']+1) if row['key'].endswith('/b.jsonl.gz') else row for row in fixture['counts']]
    spec=selective_spec(tmp_path,fixture,dict(captures=B),counts=counts,differential_rows=0)
    with pytest.raises(RuntimeError,match='Batch exited'):execute(spec)
    assert not (Path(spec['work'])/'candidate-model.json').exists()


def test_filename_only_run_guards_with_a_wrong_count(tmp_path,fixture):
    counts=[dict(row,expected_captures=9,list_items=9) if row['key'].endswith('/a.jsonl.gz') else row for row in fixture['counts']]
    spec=selective_spec(tmp_path,fixture,dict(filename_readings="filename LIKE 'b-one%'"),counts=counts,differential_rows=0)
    with pytest.raises(GenerationViolation):execute(spec)
    assert not (Path(spec['work'])/'candidate-model.json').exists()


def test_positive_model_invariant_leaves_no_candidates(tmp_path,fixture,monkeypatch):
    import viewer_publication.archive_selective as module
    def lost(*args,**kwargs):raise ValueError('Release key invariant failed')
    monkeypatch.setattr(module,'execute_model',lost)
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0)
    with pytest.raises(ValueError,match='invariant'):execute(spec)
    assert not (Path(spec['work'])/'candidate-model.json').exists()


def test_absent_suite_leaves_no_candidates(tmp_path,fixture,monkeypatch):
    import viewer_publication.archive_selective as module
    monkeypatch.setattr(module,'SUITES',(*module.SUITES,'suite_that_never_ran'))
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0)
    with pytest.raises(SelectiveStop,match='suite_that_never_ran'):execute(spec)
    assert not (Path(spec['work'])/'candidate-publish.json').exists()


def test_missing_selected_body_lists_every_gap_before_any_append(tmp_path,fixture):
    mirror=tmp_path/'mirror';shutil.copytree(fixture['raw'],mirror)
    table=pq.read_table(fixture['base']['meeting_records']).to_pylist()
    shas=[row['record_sha'].hex() for row in table if row['source']=='house_xml']
    assert shas
    for sha in shas:(mirror/'bodies/sha256'/sha[:2]/(sha+'.gz')).unlink()
    moved=dict(fixture,raw=mirror,inventory=[dict(row,path=row['path'].replace(str(fixture['raw']),str(mirror))) for row in fixture['inventory']])
    spec=selective_spec(tmp_path,moved,dict(meeting_records="source='house_xml'"),differential_rows=0)
    with pytest.raises(SelectiveStop,match='not available') as error:execute(spec)
    assert all(sha in str(error.value) for sha in shas)
    assert 'd4' not in json.loads((Path(spec['work'])/'state.json').read_text()) or not json.loads((Path(spec['work'])/'state.json').read_text())['d4']


def test_selected_receipt_absent_from_inventory_is_a_named_gap(tmp_path,fixture):
    spec=selective_spec(tmp_path,dict(fixture,inventory=[row for row in fixture['inventory'] if not row['key'].endswith('/b.jsonl.gz')]),dict(captures=B),differential_rows=0)
    with pytest.raises(SelectiveStop,match=r'absent from the inventory.*b\.jsonl\.gz'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_gpo_mods_digest_mismatch_refuses(tmp_path,fixture):
    from viewer_publication.archive_selective_records import Bodies
    xml=tmp_path/'mods';xml.mkdir();(xml/'CHRG-1.xml').write_bytes(b'<mods/>')
    receipts=tmp_path/'receipts.jsonl';receipts.write_text(json.dumps(dict(package_id='CHRG-1',sha256='0'*64))+'\n')
    class Run:
        selective=dict(raw_root=str(fixture['raw']),body_fallback=dict(gpo_mods=dict(receipts=str(receipts),root=str(xml))))
        attempt=tmp_path/'attempt'
    with pytest.raises(ValueError,match='digest mismatch'):Bodies(Run()).selection('appearance_records',[dict(record_sha='0'*64,source='mods')])

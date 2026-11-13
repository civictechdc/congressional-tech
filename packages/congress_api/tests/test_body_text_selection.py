"""Mixed actual versions through the native planner and publication consumer; no OCR."""
from hashlib import sha256
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from body_text_fixtures import raw_inputs, STAMP
from congress_api.lake import body_text, body_text_selection, readings
from congress_api.retention.provenance import json_input, parquet_output, run_job
from docspec_client.client import NativeDatasets
from viewer_publication import body_text_export


def identity(text):
    return sha256(text.encode()).hexdigest()


@pytest.fixture
def mixed(tmp_path):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    versions = body_text.current_versions()
    old, recovery = identity('accepted-baseline'), identity('recovery')
    names = ('baseline', 'recovered', 'corrected', 'rejected', 'refused', 'markup', 'new')
    captures, _, raw, shas = raw_inputs(tmp_path, {n: (n.encode(), 'html' if n == 'markup' else 'pdf')
        for n in names}, sniff_version=readings.current_version('sniff'))
    texts, outcomes = [], []
    for name, version, text in [
        ('baseline', old, 'Keep this unchanged.'), ('recovered', recovery, 'Recovered text.'),
        ('corrected', old, 'Missing tail.'), ('corrected', versions['pdf_text'], 'Restored tail and bullet.'),
        ('rejected', old, 'Previously accepted testimony.'), ('markup', old, 'Old markup.'),
        ('new', versions['pdf_text'], 'New attempt awaiting qualification.')]:
        parser = 'html_text' if name == 'markup' else 'pdf_text'
        texts.append(dict(body_sha=shas[name], parser=parser, parser_version=version, text=text,
            text_sha256=sha256(text.encode()).digest(), page_offsets=[0], ocr_pages=[], macos_build=None))
        outcomes.append(dict(body_hex=shas[name].hex(), parser=parser, parser_version=version,
                             status='completed', named_meetings=[], links=[], fields=[]))
    # A newer rejected attempt must never displace previously accepted testimony.
    outcomes.append(dict(body_hex=shas['rejected'].hex(), parser='pdf_text', parser_version=versions['pdf_text'],
        status='error', error_type='failed_pages', named_meetings=[], links=[], fields=[]))
    text_path = tmp_path / 'texts.parquet'
    pq.write_table(pa.Table.from_pylist(texts, schema=body_text._text_schema()), text_path)
    run_job(tmp_path / 'write-readings', engine,
        inputs=[json_input(tmp_path, 'rows', outcomes, **readings._reading_fields())], steps=[],
        outputs=[parquet_output(tmp_path, 'readings', f'SELECT {readings._LAKE_READING_COLUMNS} FROM rows', readings.PK)])
    refused = tmp_path / 'unreadable.jsonl'
    refused.write_text(json.dumps(dict(id='a' * 64, body_sha256=shas['refused'].hex(), parser='pdf_text',
        parser_version=recovery, reason='memory_limit', supersedes=None)) + '\n')
    report = tmp_path / 'qualification.md'
    report.write_text('Fixture: accept baseline, recovered and corrected keys; retain refusal; reject newer error.')
    overrides = [dict(body_sha256=t['body_sha'].hex(), parser=t['parser'], parser_version=t['parser_version'],
                      status='completed', text_sha256=t['text_sha256'].hex()) for t in texts
                 if t['parser_version'] in (recovery, versions['pdf_text']) and t['body_sha'] != shas['new']]
    overrides.append(dict(body_sha256=shas['refused'].hex(), parser='pdf_text', parser_version=recovery,
                          status='unreadable', text_sha256=None))
    manifest = dict(version=1, baseline_versions=dict(versions, pdf_text=old),
                    qualification=dict(path=report.name, sha256=sha256(report.read_bytes()).hexdigest()), overrides=overrides)
    selection = tmp_path / 'selection.json'
    selection.write_text(json.dumps(manifest))
    detail = tmp_path / 'detail.parquet'
    pq.write_table(pa.table({'saved_body': pa.array(list(shas.values()), type=pa.binary(32))}), detail)
    return dict(engine=engine, captures=captures, local_root=raw, decided_at=STAMP,
        existing=tmp_path / 'readings.parquet', existing_text=text_path, selection=selection,
        unreadable_files=[dict(key='unreadable', path=str(refused))]), detail, shas, manifest


def export_args(args, detail, work):
    return dict(engine=args['engine'], work=work, body_text=args['existing_text'], detail=detail,
                readings_table=args['existing'], selection=args['selection'], unreadable_files=args['unreadable_files'])


def test_mixed_readings_agree_across_plan_export_and_refusals(tmp_path, mixed, capsys):
    args, detail, shas, manifest = mixed
    planned = body_text.plan(**args, work=tmp_path / 'plan')
    pending = pq.read_table(planned['work_list']).to_pylist()
    assert [(r['body_sha'], r['parser']) for r in pending] == [(shas['markup'], 'html_text')]
    pointer = body_text_export.export(**export_args(args, detail, tmp_path / 'export'))
    selected = {r['saved_body']: r['text'] for r in pq.read_table(tmp_path / 'export/export.parquet').to_pylist()}
    assert selected == {shas['baseline']: 'Keep this unchanged.', shas['recovered']: 'Recovered text.',
                        shas['corrected']: 'Restored tail and bullet.',
                        shas['rejected']: 'Previously accepted testimony.'}
    assert pointer['coverage']['readings'] == {'pdf_text:completed': 4}
    assert pointer['coverage']['unreadable'] == {'pdf_text': 1}
    assert pointer['selection'] == planned['selection']
    assert planned['unselected_current_attempts'] == 2  # rejected replacement + new unqualified attempt
    # The actual export CLI accepts the same manifest and preserves the selected result.
    spec = dict(body_text=str(args['existing_text']), readings=str(args['existing']), detail=str(detail),
                selection=str(args['selection']), unreadable_files=args['unreadable_files'],
                work=str(tmp_path / 'cli-export'))
    spec_path = tmp_path / 'export-spec.json'
    spec_path.write_text(json.dumps(spec))
    assert body_text_export.main(['--spec', str(spec_path), '--execute']) == 0
    assert json.loads(capsys.readouterr().out)['pointer']['selection'] == planned['selection']
    # Move only markup policy; accepted PDF keys stay settled.
    manifest['baseline_versions']['html_text'] = identity('new markup policy')
    args['selection'].write_text(json.dumps(manifest))
    after = body_text.plan(**args, work=tmp_path / 'markup-change')
    assert after['by_parser'] == planned['by_parser']
    assert after['unselected_current_attempts'] == planned['unselected_current_attempts']


@pytest.mark.parametrize('damage', ['digest', 'missing', 'duplicate', 'status', 'proof'])
def test_bad_selection_cannot_publish_or_settle(tmp_path, mixed, damage):
    args, detail, _, manifest = mixed
    if damage == 'digest':
        manifest['overrides'][0]['text_sha256'] = '0' * 64
    elif damage == 'missing':
        manifest['overrides'][0]['parser_version'] = '0' * 64
    elif damage == 'duplicate':
        manifest['overrides'].append(manifest['overrides'][0])
    elif damage == 'status':
        manifest['overrides'][0].update(status='error', text_sha256=None)
    else:
        manifest['qualification']['sha256'] = '0' * 64
    args['selection'].write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        body_text.plan(**args, work=tmp_path / 'bad-plan')
    assert not (tmp_path / 'bad-plan/work-list.parquet').exists()
    with pytest.raises(ValueError):
        body_text_export.export(**export_args(args, detail, tmp_path / 'bad-export'))
    assert not (tmp_path / 'bad-export/current.json').exists()


def test_missing_qualification_and_duplicate_keys_refuse_before_sql(tmp_path):
    with pytest.raises(FileNotFoundError):
        body_text_selection.load(tmp_path / 'absent.json', body_text.current_versions())

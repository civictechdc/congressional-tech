"""Reviewed PDF identity reaches final model rows without rewriting source facts."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import pyarrow.parquet as pq
import pytest

from congress_api.retention.provenance import file_pin, json_input, list_of, run_job
from docspec_client.client import NativeDatasets
from viewer_publication import archive_model
from viewer_publication.release_comparison import compare
from viewer_publication.release_gate import group_id, load_causes, require_release_gates, verdict
from archive_job_fixture import spicy_input
from test_phase2_model_entities import _stage_raw_fixture

ROOT = Path(__file__).parents[3]
SHA = 'f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee'
URLS = [
    'https://www.congress.gov/118/meeting/house/115732/documents/BILLS-118HR4775ih.pdf',
    'https://docs.house.gov/meetings/SY/SY00/20230727/115732/BILLS-118HR4775ih.pdf',
]
PDF = ROOT / 'docs/experiments/url-normalization-validation-20261031/evidence/accepted-hr4824.pdf'


def _cover_issues(row):
    """Read the actual cover independently of the registry and model's rules."""
    assert hashlib.sha256(PDF.read_bytes()).hexdigest() == SHA
    text = subprocess.run(['pdftotext', '-f', '1', '-l', '1', str(PDF), '-'],
                          check=True, capture_output=True, text=True).stdout
    congress = re.findall(r'^(\d+)TH CONGRESS\s*$', text, re.M)
    number = re.findall(r'^H\.\s*R\.\s*(\d+)\s*$', text, re.M)
    assert len(congress) == len(number) == 1
    assert 'Privacy Enhancing' in text and 'Technology Research Act' in text
    expected = f'{congress[0]}-hr-{number[0]}'
    issues = []
    if row['measure_keys'] != [expected]:
        issues.append('direct bill differs from the numbered cover')
    if row['package_id'] is not None:
        issues.append('package edition has no independent evidence')
    return issues


def test_reviewed_bill_reaches_final_export_and_recovery_fill_cannot_restore_it(tmp_path, monkeypatch):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    staged = _stage_raw_fixture(tmp_path, engine, [dict(url=u, data=PDF.read_bytes(), format='pdf', compress=False)
                                                  for u in URLS])
    # Independent meeting context is a separate supported relationship, even
    # when the document's direct identity contradicts its source filenames.
    staged['meeting_records'] = [dict(record_sha='dd'*32, source='congress_gov', meetings=[dict(
        event_id='115732', chamber='house', congress=118, title='Committee markup', subject_keys=['118-hr-4775'])])]
    staged['spicy_regs'] = spicy_input(spicy_congress_bills=[
        dict(bill_id='118-hr-4755', title='Privacy Enhancing Technology Research Act'),
        dict(bill_id='118-hr-4775', title='Helping Tobacco Users Quit Act')])
    registry_inputs = archive_model.registry_inputs

    def without_adjudication(directory, **kwargs):
        inputs = registry_inputs(directory, **kwargs)
        entry = next(i for i in inputs if i['name'] == 'bill_package_evidence')
        import gzip
        path = Path(entry['files'][0]['path'])
        with gzip.open(path, 'rt') as source:
            rows = [json.loads(line) for line in source]
        with gzip.open(path, 'wt') as target:
            for row in rows:
                if row['package_disposition'] == 'support':
                    target.write(json.dumps(row)+'\n')
        return inputs

    with monkeypatch.context() as baseline:
        baseline.setattr(archive_model, 'registry_inputs', without_adjudication)
        before = archive_model.build_release(**staged, engine=engine, output=tmp_path/'before', scratch=tmp_path/'baseline-model')
    old = pq.read_table(tmp_path/'before/detail.parquet').to_pylist()
    assert len(old) == 1
    assert old[0]['package_id'] == 'BILLS-118hr4775ih'
    assert old[0]['measure_keys'] == ['118-hr-4775']
    assert _cover_issues(old[0]) == ['direct bill differs from the numbered cover', 'package edition has no independent evidence']

    # Exercise the real final normalization with an adversarial recovered-copy
    # fill. The exact current public body has no actual recovery occurrences.
    sql_steps = archive_model._sql_steps

    def with_wrong_fill(names, **kwargs):
        steps = sql_steps(names, **kwargs)
        for step in steps:
            if step['name'] == 'recovered_copy_fills':
                step['sql'] = '''SELECT component,cast(NULL AS VARCHAR) AS filename,cast(NULL AS VARCHAR) AS title,
                    arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS document_kind,
                    arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS document_family,
                    cast(NULL AS BIGINT) AS congress,cast(NULL AS DATE) AS filename_date,
                    'BILLS-118hr4775ih' AS package_id,
                    array_slice(make_array(named_struct('field',cast(NULL AS VARCHAR),'value',cast(NULL AS VARCHAR))),1,0) AS facts
                    FROM document_bill_decisions'''
        return steps

    after = archive_model.build_release(**staged, engine=engine, output=tmp_path/'after', scratch=tmp_path/'candidate-model')
    with monkeypatch.context() as candidate:
        candidate.setattr(archive_model, '_sql_steps', with_wrong_fill)
        adversarial = archive_model.build_release(**staged, engine=engine, output=tmp_path/'adversarial', scratch=tmp_path/'refill-model')
    assert adversarial['release_id'] == after['release_id']
    new = pq.read_table(tmp_path/'after/detail.parquet').to_pylist()
    assert len(new) == 1
    assert not _cover_issues(new[0])
    assert new[0]['saved_body'].hex() == SHA
    assert new[0]['filename'] == 'BILLS-118HR4775ih.pdf'
    assert new[0]['saved_bytes'] == 66128 and new[0]['saved_kind'] == 'original'
    assert not new[0]['hidden']
    assert {k: v for k, v in old[0].items() if k not in ('package_id', 'measure_keys')} == {
        k: v for k, v in new[0].items() if k not in ('package_id', 'measure_keys')}
    for name in ('sources', 'links', 'urls', 'recoveries'):
        assert pq.read_table(tmp_path/f'before/{name}.parquet').equals(pq.read_table(tmp_path/f'after/{name}.parquet'))
    assert {r['url'] for r in pq.read_table(tmp_path/'after/sources.parquet').to_pylist()} == set(URLS)
    for name in ('source_annotations', 'source_filename_readings', 'source_members'):
        assert pq.read_table(tmp_path/f'baseline-model/evidence/{name}.parquet').equals(
            pq.read_table(tmp_path/f'candidate-model/evidence/{name}.parquet'))
    annotations = pq.read_table(tmp_path/'candidate-model/evidence/source_annotations.parquet').to_pylist()
    assert {r['package_id'] for r in annotations} == {'BILLS-118hr4775ih'}
    assert all(r['measure_keys'] == ['118-hr-4775'] for r in annotations)
    decisions = pq.read_table(tmp_path/'candidate-model/evidence/document_bill_decisions.parquet').to_pylist()
    assert len(decisions) == 1 and decisions[0]['pdf_sha'] == SHA
    assert decisions[0]['source_urls'] == URLS
    meeting = next(r for r in pq.read_table(tmp_path/'after/meetings.parquet').to_pylist() if r['event_id'] == 115732)
    assert set(meeting['subject_keys']) == {'118-hr-4755', '118-hr-4775'}
    queries = {q['name']: q['data'] for q in json.loads((tmp_path/'candidate-model/result.json').read_text())['queries']}
    for name in ('invariants', 'model_invariants', 'url_state_invariants', 'profile_completeness',
                 'entity_profile_completeness', 'relationship_invariants'):
        assert not any(queries[name][0].values()), (name, queries[name])

    report = compare(tmp_path/'before', tmp_path/'after')
    assert report['link_rule']['ok']
    assert {(g['file'], g['group'], g['count']) for g in report['failing']} == {
        ('list.parquet', 'changed measure_keys', 1), ('detail.parquet', 'changed measure_keys', 1),
        ('detail.parquet', 'changed package_id', 1), ('meetings.parquet', 'changed subject_keys', 1)}
    assert verdict(report, None)[0]  # Changes need a stated, counted cause.
    evidence = [dict(path=str(p), **file_pin(p)) for p in
                (PDF, ROOT/'model/registries/bill-package-evidence.json',
                 tmp_path/'candidate-model/evidence/document_bill_decisions.parquet',
                 tmp_path/'candidate-model/evidence/document_rows.parquet', tmp_path/'baseline-model/evidence/document_rows.parquet')]
    causes = dict(version=1, base_release_id=before['release_id'], candidate_release_id=after['release_id'], groups=[
        dict(id=group_id(g), count=g['count'], disposition='explained',
             cause='Exact PDF cover adjudication '+decisions[0]['id']+' corrects direct bill metadata and its derived meeting subject; independent meeting context stays.',
             evidence=evidence, tickets=['ct-yci9']) for g in report['failing']])
    assert verdict(report, causes)[0] == []
    (tmp_path/'comparison.json').write_text(json.dumps(report, indent=2)+'\n')
    (tmp_path/'causes.json').write_text(json.dumps(causes, indent=2)+'\n')
    checked = load_causes(dict(path=str(tmp_path/'causes.json'), **file_pin(tmp_path/'causes.json')))
    gate = require_release_gates(tmp_path/'before', tmp_path/'after', checked, report_path=tmp_path/'release-gate.json')
    assert not gate['reasons']

    planted = []
    for field, wrong in [('package_id', 'BILLS-118hr4775ih'), ('measure_keys', ['118-hr-4775'])]:
        row = deepcopy(new[0]); row[field] = wrong
        assert _cover_issues(row)
        planted.append(field)
    (tmp_path/'independent-cover-check.json').write_text(json.dumps(dict(
        pdf_sha256=SHA, source_urls=URLS, corrected_issues=_cover_issues(new[0]), detected_plants=planted), indent=2)+'\n')


def test_body_and_source_binding_do_not_adjudicate_other_documents(tmp_path):
    inputs = archive_model.registry_inputs(tmp_path/'registries')
    rows = []
    for component, body, url, fmt in [
        ('exact', SHA, URLS[0], 'pdf'),
        ('same-bytes-unobserved-source', SHA, 'https://other.test/BILLS-118HR4775ih.pdf', 'pdf'),
        ('different-bytes', 'e'*64, URLS[0], 'pdf'),
        ('unnumbered-draft', 'd'*64, URLS[0], 'pdf'),
        ('other-bill-mention', 'c'*64, URLS[0], 'pdf'),
        ('other-congress-same-number', 'b'*64, URLS[0], 'pdf'),
        ('other-rendition', SHA, URLS[0], 'html'),
        ('different-selected-body', SHA, URLS[0], 'pdf'),
    ]:
        rows.append(dict(component=component, body_sha=body, source_url=url, format=fmt,
                         saved_rank=2 if component == 'different-selected-body' else 1))
    rows.append(dict(component='different-selected-body', body_sha='a'*64, source_url=URLS[0], format='pdf', saved_rank=1))
    inputs.append(json_input(tmp_path, 'saved_files', rows, component='Utf8', body_sha='Utf8', source_url='Utf8', format='Utf8', saved_rank='Int64'))
    inputs.append(json_input(tmp_path, 'document_members', [dict(component=r['component'], source_id=str(i),
        is_real_file=True, first_fetched=None, in_archive_since=None) for i, r in enumerate(rows)],
        component='Utf8', source_id='Utf8', is_real_file='Boolean', first_fetched='Utf8', in_archive_since='Utf8'))
    fields = ('document_kind', 'document_family', 'committee_keys', 'chambers', 'meeting_keys', 'measure_keys', 'bioguide_ids')
    inputs.append(json_input(tmp_path, 'source_annotations', [dict(source_id=str(i),
        **{f: (['118-hr-4775', '118-hr-9999'] if r['component'] == 'exact' else ['118-hr-4775'])
           if f == 'measure_keys' else [] for f in fields}) for i, r in enumerate(rows)],
        source_id='Utf8', **{f: list_of('Utf8') for f in fields}))
    result = run_job(tmp_path, NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), inputs=inputs,
                     steps=[dict(name=name.replace('-', '_'), sql=(ROOT/f'model/sql/{name}.sql').read_text(), materialize=True)
                            for name in ('document-bill-decisions', 'document-metadata')],
                     outputs=[], queries=[dict(name='selected', sql='SELECT component FROM document_bill_decisions ORDER BY component'),
                         dict(name='measures', sql='SELECT component,measure_keys FROM document_metadata ORDER BY component')])
    assert result['selected'] == [dict(component='exact')]
    assert all(r['measure_keys'] == (['118-hr-4755', '118-hr-9999'] if r['component'] == 'exact' else ['118-hr-4775'])
               for r in result['measures'])


def test_reviewed_bill_registry_refuses_ambiguous_or_incomplete_decisions():
    rows = json.loads((ROOT/'model/registries/bill-package-evidence.json').read_text())
    archive_model._validate_bill_evidence(rows)
    for mutate in (
        lambda r: r.append(deepcopy(r[-1])),
        lambda r: r[-1].update(package_disposition='guess'),
        lambda r: r[-1].update(source_urls=[]),
        lambda r: r[-1].update(package_id='BILLS-118hr4755ih'),
        lambda r: r[-1].update(supported_measure_keys=['118-hr-4775']),
    ):
        bad = deepcopy(rows); mutate(bad)
        with pytest.raises(ValueError, match='reviewed bill evidence'):
            archive_model._validate_bill_evidence(bad)

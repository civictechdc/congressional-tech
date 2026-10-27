"""Registry samples are authored before native policy lookup binds their files."""
import json
import os
from pathlib import Path

from docspec_client.client import NativeDatasets
from congress_api.retention.provenance import json_input,run_job

ROOT=Path(__file__).parents[3]


def test_phase1_registry_samples_run_through_native_policy_relations(tmp_path):
    from viewer_publication.archive_model import registry_inputs
    fixture=json.loads((ROOT/'model/fixtures/registry-samples.json').read_text())
    expected={row['id']:row for row in fixture['cases']}
    rows=[]
    for row in expected.values():
        value,wanted=row['value'],row['expected']
        rows.append(dict(id=row['id'],registry=row['registry'],entry=row['entry'],
            value=value if isinstance(value,str) else None,
            value_json=json.dumps(value) if isinstance(value,dict) else None))
    inputs=registry_inputs(tmp_path/'registries')
    inputs.append(json_input(tmp_path,'cases',rows,id='Utf8',registry='Utf8',entry='Utf8',value='Utf8',value_json='Utf8'))
    queries=[
      dict(name='file-shapes',sql="""SELECT c.id,coalesce(bool_or(regexp_like(c.value,r.pattern)),false) AS actual
        FROM cases c LEFT JOIN file_shapes r ON c.entry IS NULL OR c.entry=r.id
        WHERE c.registry='file-shapes' GROUP BY c.id ORDER BY c.id"""),
      dict(name='page-signals',sql="""SELECT c.id,regexp_like(c.value,r.pattern) AS actual_bool,r.number AS actual_number
        FROM cases c JOIN page_signals r ON c.entry=r.id
        WHERE c.registry='page-signals' ORDER BY c.id"""),
      dict(name='formats',sql="SELECT c.id,r.rank AS actual FROM cases c JOIN formats r ON c.entry=r.id WHERE c.registry='formats' ORDER BY c.id"),
      dict(name='publisher-kinds',sql="""SELECT c.id,min(r.document_kind) AS actual FROM cases c
        LEFT JOIN publisher_kinds r ON (c.entry IS NULL OR c.entry=r.id) AND regexp_like(c.value,r.pattern)
        WHERE c.registry='publisher-kinds' GROUP BY c.id ORDER BY c.id"""),
      dict(name='display-facts',sql="SELECT c.id,r.label AS actual FROM cases c JOIN display_facts r ON c.value=r.field WHERE c.registry='display-facts' ORDER BY c.id"),
      dict(name='committee-codes',sql="""SELECT c.id,min(r.system_code) AS actual FROM cases c
        LEFT JOIN committee_codes r ON c.value=r.code AND (c.entry IS NULL OR c.entry=r.id)
        WHERE c.registry='committee-codes' GROUP BY c.id ORDER BY c.id"""),
      dict(name='recheck-intervals',sql="""SELECT c.id,min(r.interval_seconds) AS actual FROM cases c
        LEFT JOIN recheck_intervals r ON json_get_str(c.value_json,'family')=r.family
          AND (r.min_age_days IS NULL OR json_get_int(c.value_json,'age')>=r.min_age_days)
          AND (r.max_age_days IS NULL OR json_get_int(c.value_json,'age')<r.max_age_days)
        WHERE c.registry='recheck-intervals' GROUP BY c.id ORDER BY c.id"""),
      dict(name='preference',sql="SELECT value FROM formats WHERE kind='preference' ORDER BY rank,value"),
      dict(name='band_conflicts',sql="""SELECT count(*) AS n FROM recheck_intervals a JOIN recheck_intervals b
        ON a.family=b.family AND a.id<b.id AND coalesce(a.max_age_days,2147483647)>coalesce(b.min_age_days,-2147483648)
          AND coalesce(b.max_age_days,2147483647)>coalesce(a.min_age_days,-2147483648)""")]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=inputs,steps=[],outputs=[],queries=queries)
    seen=set()
    for registry in ['file-shapes','page-signals','formats','publisher-kinds','display-facts','committee-codes','recheck-intervals']:
        for row in result[registry]:
            case=expected[row['id']];seen.add(row['id'])
            value=(row['actual_number'] if type(case['expected']) is int else row['actual_bool']) if registry=='page-signals' else row['actual']
            assert value==case['expected'],case['id']
    assert seen==set(expected)
    assert result['preference'][0]['value']=='pdf'
    assert result['band_conflicts']==[dict(n=0)]


def test_every_seed_entry_has_a_separate_sample_with_its_evidence():
    from viewer_publication.archive_model import REGISTRIES
    cases=json.loads((ROOT/'model/fixtures/registry-samples.json').read_text())['cases']
    by_id={x['id']:x for x in cases}
    assert len(by_id)==len(cases)
    for name in ['file-shapes','page-signals','formats','publisher-kinds','display-facts','committee-codes','recheck-intervals']:
        rows=json.loads((ROOT/'model/registries'/(name+'.json')).read_text())
        assert len({x['id'] for x in rows})==len(rows)
        assert name.replace('-','_') in REGISTRIES
        for row in rows:
            sample=by_id[row['sample_id']]
            assert sample['entry']==row['id'] and sample['registry']==name and sample['source']
            assert not sample['source'].startswith('Authored boundary')

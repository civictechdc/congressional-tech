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
      dict(name='title-rules',sql="""SELECT c.id,regexp_like(c.value,r.pattern) AS actual
        FROM cases c JOIN title_rules r ON c.entry=r.id WHERE c.registry='title-rules' ORDER BY c.id"""),
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
    queries.append(dict(name='archive-layouts',sql="""SELECT c.id,min(a.published_url) AS actual FROM cases c
        LEFT JOIN archive_member_addresses a ON a.source_id=c.id WHERE c.registry='archive-layouts' GROUP BY c.id ORDER BY c.id"""))
    steps=[dict(name='capture_source_contexts',sql="""SELECT id AS source_id,'00' AS body_sha,'stored' AS outcome,
            json_get_str(value_json,'container') AS context_url,json_get_str(value_json,'member') AS member_path
            FROM cases WHERE registry='archive-layouts'"""),
        dict(name='archive_member_addresses',sql=(ROOT/'model/sql/archive-member-addresses.sql').read_text())]
    result=run_job(tmp_path,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=inputs,steps=steps,outputs=[],queries=queries)
    seen=set()
    for registry in ['file-shapes','page-signals','title-rules','formats','publisher-kinds','display-facts','committee-codes','recheck-intervals','archive-layouts']:
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
    for name in ['file-shapes','page-signals','title-rules','formats','publisher-kinds','display-facts','committee-codes','recheck-intervals','archive-layouts']:
        rows=json.loads((ROOT/'model/registries'/(name+'.json')).read_text())
        assert len({x['id'] for x in rows})==len(rows)
        assert name.replace('-','_') in REGISTRIES
        for row in rows:
            sample=by_id[row['sample_id']]
            assert sample['entry']==row['id'] and sample['registry']==name and sample['source']
            assert not sample['source'].startswith('Authored boundary')


def test_recording_sources_resolves_malformed_youtube_embeds(tmp_path):
    """ct-6qgg: all seven malformed democrats-veterans embeds resolve through native recording_url_sources SQL."""
    from viewer_publication.archive_model import registry_inputs

    malformed = [
        ('https://www.youtube.com/embed/FySkoDtoxp8&list=PLnvOLdmKre5zdH1_72pvAsVptGY8d4Nbk?rel=0&wmode=opaque', 'youtube:FySkoDtoxp8'),
        ('https://www.youtube.com/embed/YzFFXeDonIg&t=346s?rel=0&wmode=opaque', 'youtube:YzFFXeDonIg'),
        ('https://www.youtube.com/embed/jJj2qoIj-sc&list=PLnvOLdmKre5zdH1_72pvAsVptGY8d4Nbk&index=2?rel=0&wmode=opaque', 'youtube:jJj2qoIj-sc'),
        ('https://www.youtube.com/embed/https://youtube.com/live/VCiH6kOEEEk?feature=share?rel=0&wmode=opaque', 'youtube:VCiH6kOEEEk'),
        ('https://www.youtube.com/embed/3v8I_Oxrwv8&list=PLnvOLdmKre5yMctfJ949ckoHz9BJ88h7f?rel=0&wmode=opaque', 'youtube:3v8I_Oxrwv8'),
        ('https://www.youtube.com/embed/xtkwFNmQuUc&t=214s?rel=0&wmode=opaque', 'youtube:xtkwFNmQuUc'),
        ('https://www.youtube.com/embed/UnAZvMF-b3g&list=PLnvOLdmKre5zdH1_72pvAsVptGY8d4Nbk?rel=0&wmode=opaque', 'youtube:UnAZvMF-b3g'),
    ]
    rejected = [
        'https://www.youtube.com/embed/1bxY6pFimYg021424?rel=0&wmode=opaque',
        'https://www.youtube.com/@VetAffairsDems',
    ]
    inputs = registry_inputs(tmp_path / 'registries')
    inputs.append(json_input(tmp_path, 'recording_link_candidates',
        [dict(page_body=f'{i:064x}', target_url=u) for i, (u, _) in enumerate(malformed)]
        + [dict(page_body=f'{100 + i:064x}', target_url=u) for i, u in enumerate(rejected)],
        page_body='Utf8', target_url='Utf8'))
    steps = [
        dict(name='recording_url_sources',
             sql="SELECT id,pattern,key_template,format,default_language,default_production FROM recording_sources WHERE kind='video_url'",
             materialize=True),
        dict(name='recording_video_links', sql="""SELECT DISTINCT l.target_url,
            regexp_replace((regexp_match(l.target_url,rs.pattern))[1],'^(.+)$',rs.key_template) AS extracted_key
            FROM recording_url_sources rs JOIN recording_link_candidates l ON regexp_like(l.target_url,rs.pattern)""",
             materialize=True),
    ]
    res = run_job(tmp_path / 'job', NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        inputs=inputs, steps=steps, outputs=[],
        queries=[dict(name='links', sql='SELECT target_url,extracted_key FROM recording_video_links ORDER BY target_url')])
    actual = {r['target_url']: r['extracted_key'] for r in res['links']}
    assert actual == dict(malformed)


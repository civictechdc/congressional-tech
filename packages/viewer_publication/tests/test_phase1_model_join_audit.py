"""Inspect every native model join without executing corpus-sized work."""
import json
import os

from archive_job_fixture import real_model_spec
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model_job import execute, validate_spec


def build_children(plan):
    lines = plan.splitlines()
    for index, line in enumerate(lines):
        if 'HashJoinExec:' not in line and 'NestedLoopJoinExec:' not in line:
            continue
        first = lines[index+1]
        indent = len(first)-len(first.lstrip())
        build = [first]
        for child in lines[index+2:]:
            if len(child)-len(child.lstrip()) <= indent:
                break
            build.append(child)
        yield '\n'.join(build)


def test_every_model_join_has_a_native_fixture_plan_and_wide_rows_stream(tmp_path):
    value, _digest, _html = real_model_spec(tmp_path)
    assert execute(validate_spec(value, base=tmp_path))['status'] == 'built'
    spec = json.loads((tmp_path/'model/job.json').read_text())
    for item in spec['inputs']:
        if item['name'] in {'captures', 'readings', 'filename_readings'}:
            item['path'] = value[item['name']]['path']
    # The audit retains fixture relations so every original reader can be
    # explained after registration. Only these tiny fixture rows execute.
    steps = [{key: value for key, value in step.items() if key != 'release_after'}
             for step in spec['steps']]
    readers = [(step['name'], step.get('sql', step.get('components', {}).get('sql')))
               for step in steps]
    readers += [(item['name'], item['sql']) for item in spec['outputs']+spec['queries']]
    audit = dict(inputs=spec['inputs'], steps=steps, outputs=[],
        scratch=str(tmp_path/'audit-native'), queries=[
            dict(name='reader_'+str(index), sql='EXPLAIN '+sql)
            for index, (_name, sql) in enumerate(readers)])
    path = tmp_path/'join-audit-job.json'; path.write_text(json.dumps(audit))
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        result = engine.run_job(path)
    plans = {name: next(row['plan'] for row in query['data'] if row['plan_type'] == 'physical_plan')
             for (name, _sql), query in zip(readers, result['queries'])}
    (tmp_path/'join-plans.json').write_text(json.dumps(plans, indent=2)+'\n')
    assert len(plans) == len(readers)
    assert not {name for name, plan in plans.items()
                if any(line.lstrip().startswith('WindowAggExec:') for line in plan.splitlines())}
    # Corpus captures have four million rows. Their receipt/outcome payload
    # must stream through the narrower flags and registry joins.
    for name, fields in {
        'record_roles': ['mode@', 'outcome@', 'http_status@', 'complete@', 'bytes@'],
        'capture_source_names': ['stored_suffix@', 'response_headers@', 'outcome@'],
        'source_annotations': ['filename_status@', 'listing_title@'],
        'saved_files': ['first_seen@', 'first_fetched@'],
    }.items():
        children = list(build_children(plans[name]))
        assert children, plans[name]
        for build in children:
            assert not any(field in build for field in fields), name+'\n'+build

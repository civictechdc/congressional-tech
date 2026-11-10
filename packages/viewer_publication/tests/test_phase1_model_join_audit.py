"""Inspect every native model join without executing corpus-sized work."""
import json
import os
import re

from archive_job_fixture import real_model_spec
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import LAKE_CAPTURES
from viewer_publication.archive_model_job import execute, validate_spec


def build_children(plan, join_types=None):
    """Each join's build (first) input, optionally for the named native join types only."""
    lines = plan.splitlines()
    for index, line in enumerate(lines):
        if 'HashJoinExec:' not in line and 'NestedLoopJoinExec:' not in line:
            continue
        if join_types and re.search(r'join_type=(\w+)', line).group(1) not in join_types:
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
    # The job's lake inputs name files held only while it ran; the job binds captures as LAKE_CAPTURES.
    lake = {LAKE_CAPTURES: 'captures', 'readings': 'readings', 'filename_readings': 'filename_readings'}
    for item in spec['inputs']:
        if item['name'] in lake:
            item['path'] = value[lake[item['name']]]['path']
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
        'source_annotations': [],
        'saved_files': ['first_seen@', 'first_fetched@'],
    }.items():
        children = list(build_children(plans[name]))
        assert children, plans[name]
        for build in children:
            assert not any(field in build for field in fields), name+'\n'+build
            if name != 'capture_source_names':
                assert 'HashJoinExec:' not in build and 'NestedLoopJoinExec:' not in build, name+'\n'+build

    # base_normalized ran out of query memory while four trailing LEFT JOINs built on the whole
    # document row (ct-n5ec). No outer join may build on it, recognized by either scan below.
    # The recovery half builds on its few recovered-only rows, whose scan also reads has_real.
    plan = plans['base_normalized']
    document_row = ['projection=[component, link_bodies]', 'projection=[component, document_id]']
    assert all(scan in plan for scan in document_row), plan
    outer = list(build_children(plan, join_types={'Left', 'Right', 'Full'}))
    assert outer, plan
    for build in outer:
        assert not any(scan in build for scan in document_row), 'base_normalized\n'+build

    registry_fields = {'id', 'kind', 'host_pattern', 'pattern', 'replacement', 'decoder',
                       'basis', 'document_kind'}
    for name in ['source_url_normalized', 'url_normalized', 'url_state_sanitized_normalized',
                 'link_literals', 'link_targets', 'source_annotation_publisher']:
        lines = plans[name].splitlines()
        for index, line in enumerate(lines):
            if 'NestedLoopJoinExec:' not in line:
                continue
            # Use the same native tree boundary as build_children, selecting
            # this individual non-equality rule join rather than other joins.
            children = next(build_children('\n'.join(lines[index:])))
            leaves = [leaf for leaf in children.splitlines() if 'StreamingTableExec:' in leaf]
            assert leaves, name+'\n'+children
            for leaf in leaves:
                columns = {field.strip() for field in leaf.partition('projection=[')[2].partition(']')[0].split(',')}
                assert columns <= registry_fields, name+'\n'+children

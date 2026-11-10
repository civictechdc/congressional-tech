"""Candidate SHA joins must filter captures below their aggregates in the native plan.

This reads the plan on empty inputs, so it checks join placement only. It sees neither
memory, Iceberg pruning, pool pressure, nor whether the expression key blocks pushdown.
The original memory failure needs a full job, and this gate does not claim to detect it.
"""
import json
import os
import re

import pyarrow.parquet as pq
import pytest

from archive_job_fixture import real_model_spec, spicy_input
from congress_api.lake import appearance_records, meeting_records
from congress_api.retention.provenance import run_job
from docspec_client.client import NativeDatasets
from viewer_publication import archive_format
from viewer_publication.archive_model import build_prepared_release, prepare_model_inputs

# Keyed by candidate clauses, so a step split or join direction cannot silently remove coverage.
CANDIDATE_JOINS = ('JOIN candidate_meeting_shas cms', 'JOIN candidate_app_shas cas', 'FROM candidate_appearance_shas cas')


@pytest.fixture(scope='module')
def planned(tmp_path_factory):
    """The real prepared steps over zero-row inputs with producer schemas."""
    root = tmp_path_factory.mktemp('candidate-joins')
    value, _digest, _html = real_model_spec(root)
    empty = {}
    for name in ('captures', 'readings', 'filename_readings'):
        empty[name] = root / f'empty-{name}.parquet'
        pq.write_table(pq.read_schema(value[name]['path']).empty_table(), empty[name])
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        prepared = prepare_model_inputs(**empty, parser_versions=dict(value['parser_versions'],
                meeting_records=meeting_records.current_versions(), appearance_records=appearance_records.current_versions()),
            catalog_version=value['catalog_version'], engine=engine, scratch=root / 'prepared',
            meeting_records=[], appearance_records=[], spicy_regs=spicy_input(), include_entities=True)
        class Stop(Exception):
            pass
        seen = []
        def stop(_inputs, steps, **_):
            # Planned over the prepared binding, where captures is a file: a retained step's scan
            # prints no relation name in a physical plan, so the gate could not find it.
            seen.extend(step for step in steps if step['name'] != 'captures')
            raise Stop
        patch = pytest.MonkeyPatch()
        patch.setattr(archive_format, '_execute', stop)
        try:
            with pytest.raises(Stop):
                build_prepared_release(prepared, engine=engine, output=root / 'release')
        finally:
            patch.undo()
        yield root, engine, prepared, seen


def closure(steps, names):
    """Steps the named ones depend on, by step-name tokens in their definitions, in original order."""
    by_name = {step['name']: step for step in steps}
    wanted, pending = set(), list(names)
    while pending:
        name = pending.pop()
        if name not in wanted:
            wanted.add(name)
            pending += [token for token in set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', json.dumps(by_name[name])))
                        if token in by_name and token != name]
    return [{key: item for key, item in step.items() if key != 'release_after'}
            for step in steps if step['name'] in wanted]


def physical(root, engine, prepared, steps, sql, work):
    result = run_job(root / work, engine, inputs=prepared['inputs'], steps=steps, outputs=[],
                     queries=[dict(name='plan', sql='EXPLAIN ' + sql)])
    [row] = [row for row in result['plan'] if row['plan_type'] == 'physical_plan']
    return row['plan']


def joined_step(seen, join):
    [step] = [step for step in seen if join in step.get('sql', '')]
    return step


def capture_scans_filtered(plan):
    """One verdict per captures scan: is the candidate join below the first aggregate?"""
    lines = plan.splitlines()
    verdicts = []
    for index, line in enumerate(lines):
        if 'DataSourceExec' not in line or 'captures.parquet' not in line:
            continue
        indent = len(line) - len(line.lstrip())
        verdict = False
        for ancestor in reversed(lines[:index]):
            depth = len(ancestor) - len(ancestor.lstrip())
            if depth >= indent:
                continue
            indent = depth
            if 'AggregateExec' in ancestor:
                break
            # The candidate join is on the hex expression key or, which prunes better, on the raw binary digest.
            if 'HashJoinExec' in ancestor and 'sha256' in ancestor and (
                    ('encode(' in ancestor and 'record_sha_hex' in ancestor) or ancestor.count('sha256') >= 2):
                verdict = True
                break
        verdicts.append(verdict)
    return verdicts


@pytest.mark.parametrize('join', CANDIDATE_JOINS)
def test_candidate_join_precedes_capture_aggregate(planned, join):
    root, engine, prepared, seen = planned
    step = joined_step(seen, join)
    plan = physical(root, engine, prepared, closure(seen, [step['name']]), step['sql'], f"plan-{step['name']}")
    verdicts = capture_scans_filtered(plan)
    assert verdicts, 'no captures scan in the plan, so this gate would pass vacuously'
    assert all(verdicts), verdicts


@pytest.mark.parametrize('join', CANDIDATE_JOINS)
def test_gate_fails_when_the_candidate_join_is_removed(planned, join):
    root, engine, prepared, seen = planned
    step = joined_step(seen, join)
    if join == 'FROM candidate_appearance_shas cas':
        candidate_join = join + '\n JOIN captures c ON c.sha256=cas.sha256'
        assert candidate_join in step['sql']
        stripped = step['sql'].replace(candidate_join, 'FROM captures c', 1)
    else:
        stripped = re.sub(re.escape(join) + r'[^\n]*\n', '\n', step['sql'])
    assert stripped != step['sql']
    plan = physical(root, engine, prepared, closure(seen, [step['name']]), stripped, f"negative-{step['name']}")
    verdicts = capture_scans_filtered(plan)
    assert verdicts and not all(verdicts), verdicts

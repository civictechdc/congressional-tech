"""Authored policy binds native preparation; this layer never evaluates rows."""
import base64
from copy import deepcopy
from hashlib import sha256
import json

import pyarrow as pa
import pytest

from viewer_publication.archive_model_profile import native_report_policy


def request():
    checks = dict(name='relationship_invariants', sql='SELECT * FROM "checks_é"')
    return dict(
        inputs=[dict(name='unopened', kind='parquet', path='/no-payload-is-read.parquet')],
        steps=[dict(name='checks_é', sql='SELECT 0 AS missing_parent')],
        outputs=[dict(name='private.parquet', sql='SELECT * FROM unopened')],
        queries=[dict(name='invariants', sql='SELECT 0 AS duplicate_rows'), checks,
                 dict(name='coverage', sql='SELECT * FROM coverage_rows')]), [checks]


def preparation(job, *, counter_schema=None):
    """Small native-shaped fixture, with no schema inference or input reads."""
    job_bytes = json.dumps(job, ensure_ascii=False).encode('utf-8')
    schema = counter_schema if counter_schema is not None else pa.schema([
        pa.field('missing_parent', pa.int64(), nullable=True,
                 metadata={b'domain': b'parent existence'})], metadata={b'owner': b'native'})
    raw = schema.serialize().to_pybytes()
    digest = sha256(raw).hexdigest()
    prepared = dict(profile='urn:docspec:job:schema-only:1', status='inferred',
                    job=dict(sha256=sha256(job_bytes).hexdigest()), job_size=len(job_bytes),
                    schemas={digest: base64.b64encode(raw).decode('ascii')})
    for group in ('inputs', 'steps', 'outputs', 'queries'):
        prepared[group] = [dict(name=item['name'], schema_sha256=digest) for item in job[group]]
    return job_bytes, prepared


def policy(job_bytes, diagnostics, prepared):
    return native_report_policy(job_bytes, diagnostics, prepared, policy_id='archive-counters-v1')


def test_exact_policy_preserves_sql_schema_bytes_and_complete_view_membership():
    job, diagnostics = request()
    job_bytes, prepared = preparation(job)
    before = deepcopy((job, diagnostics, prepared))
    result = policy(job_bytes, diagnostics, prepared)
    assert (job, diagnostics, prepared) == before
    assert result == dict(
        id='archive-counters-v1', profile='urn:docspec:quality:native-sql-zero-counters:1',
        evaluator=dict(id='urn:docspec:evaluator:native-job-reports', version='1'),
        semantics=dict(id='urn:docspec:semantics:complete-integer-zero-row', revision='1'),
        job_sha256=sha256(job_bytes).hexdigest(),
        view_names=dict(inputs=['unopened'], steps=['checks_é'], outputs=['private.parquet'],
                        reports=['invariants', 'relationship_invariants', 'coverage']),
        required_reports=[dict(name=query['name'],
                               sql_sha256=sha256(query['sql'].encode('utf-8')).hexdigest(),
                               schema_ipc_base64=next(iter(prepared['schemas'].values())))
                          for query in job['queries'][:2]])
    # SELECT * and declared nullable integer fields are valid. Native execution
    # rejects actual null values; the application must not repeat that query.
    assert [item['name'] for item in policy(job_bytes, [], prepared)['required_reports']] == ['invariants']


@pytest.mark.parametrize('identity', ['', ' ', None])
def test_explicit_policy_identity(identity):
    job, diagnostics = request()
    job_bytes, prepared = preparation(job)
    with pytest.raises(ValueError, match='explicit identity'):
        native_report_policy(job_bytes, diagnostics, prepared, policy_id=identity)


@pytest.mark.parametrize('defect', ['profile', 'status', 'sha256', 'size'])
def test_other_preparation_refused(defect):
    job, diagnostics = request()
    job_bytes, prepared = preparation(job)
    if defect == 'sha256':
        prepared['job']['sha256'] = '0' * 64
    elif defect == 'size':
        prepared['job_size'] += 1
    else:
        prepared[defect] = 'different'
    with pytest.raises(ValueError, match='exact captured JobSpec'):
        policy(job_bytes, diagnostics, prepared)


@pytest.mark.parametrize('group', ['inputs', 'steps', 'outputs', 'queries'])
@pytest.mark.parametrize('defect', ['missing', 'extra'])
def test_complete_membership_includes_nonblocking_and_private_views(group, defect):
    job, diagnostics = request()
    job_bytes, prepared = preparation(job)
    if defect == 'missing':
        prepared[group].pop()
    else:
        prepared[group].append(dict(prepared[group][0]))
    with pytest.raises(ValueError, match='complete ordered'):
        policy(job_bytes, diagnostics, prepared)


def test_native_view_order():
    job, diagnostics = request()
    job_bytes, prepared = preparation(job)
    prepared['queries'].reverse()
    with pytest.raises(ValueError, match='complete ordered queries'):
        policy(job_bytes, diagnostics, prepared)


@pytest.mark.parametrize('defect, message', [
    ('missing_invariants', 'lacks its required invariants'),
    ('duplicate_query', 'complete ordered queries'),
    ('duplicate_required', 'Blocking native report names must be unique'),
    ('missing_required', 'differs from the original native job query'),
    ('changed_sql', 'differs from the original native job query'),
])
def test_changed_required_queries_refused(defect, message):
    job, diagnostics = request()
    if defect == 'missing_invariants':
        job['queries'].pop(0)
    elif defect == 'duplicate_query':
        job['queries'].append(deepcopy(job['queries'][0]))
    elif defect == 'duplicate_required':
        diagnostics.append(deepcopy(diagnostics[0]))
    elif defect == 'missing_required':
        job['queries'].remove(diagnostics[0])
    else:
        diagnostics = [dict(diagnostics[0], sql='SELECT 0 AS missing_parent')]
    job_bytes, prepared = preparation(job)
    with pytest.raises(ValueError, match=message):
        policy(job_bytes, diagnostics, prepared)


@pytest.mark.parametrize('schema', [
    pa.schema([]), pa.schema([('', pa.int64())]),
    pa.schema([('duplicate', pa.int64()), ('duplicate', pa.int64())]),
    pa.schema([('count', pa.float64())]), pa.schema([('count', pa.decimal128(12, 0))]),
    pa.schema([('count', pa.string())]),
])
def test_non_counter_schemas_refused(schema):
    job, diagnostics = request()
    job_bytes, prepared = preparation(job, counter_schema=schema)
    with pytest.raises(ValueError, match='unique integer counter columns'):
        policy(job_bytes, diagnostics, prepared)


@pytest.mark.parametrize('defect', ['missing', 'changed', 'invalid_base64'])
def test_missing_or_changed_schema_bytes_refused(defect):
    job, diagnostics = request()
    job_bytes, prepared = preparation(job)
    digest = next(iter(prepared['schemas']))
    if defect == 'missing':
        del prepared['schemas'][digest]
    elif defect == 'changed':
        prepared['schemas'][digest] = base64.b64encode(b'other schema bytes').decode('ascii')
    else:
        prepared['schemas'][digest] = 'not base64!'
    with pytest.raises((KeyError, ValueError)):
        policy(job_bytes, diagnostics, prepared)

"""Application metadata boundaries; shared native cases own proof acceptance."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pytest


def pin_json(path, value):
    raw = (json.dumps(value, indent='\t') + '\n').encode()
    path.write_bytes(raw)
    return dict(path=str(path), sha256=sha256(raw).hexdigest(), size=len(raw))


@pytest.mark.parametrize('change', ['sha256', 'size', 'too_large'])
def test_proof_pin_refuses_before_evidence_verification(tmp_path, monkeypatch, change):
    import ddk.docspec_job_evidence as evidence
    from ddk.adapters.docspec import DEFAULT_CAPTURE_BYTES
    from viewer_publication.archive_model_proof import read_producer_proof

    pin = pin_json(tmp_path/'proof.json', {'original': 'native result'})
    if change == 'sha256':
        pin['sha256'] = '0'*64
    elif change == 'size':
        pin['size'] += 1
    else:
        pin['size'] = DEFAULT_CAPTURE_BYTES + 1
    def must_not_verify(*args, **kwargs):
        pytest.fail('An invalid original byte pin reached evidence verification')
    monkeypatch.setattr(evidence, 'verify_completed_job', must_not_verify)
    with pytest.raises(ValueError, match='receipt|identity'):
        read_producer_proof(pin)


def test_receipt_loading_requires_native_acceptance(tmp_path, monkeypatch):
    import ddk.docspec_job_evidence as evidence
    from viewer_publication import archive_model_proof as application

    original = {'original': 'native result'}
    pin = pin_json(tmp_path/'proof.json', original)
    verified = object()
    calls = []
    def verify(result, *, require_accepted):
        assert result == original and require_accepted is True
        calls.append('verified')
        return verified
    monkeypatch.setattr(evidence, 'verify_completed_job', verify)
    monkeypatch.setattr(application, 'require_producer_proof', lambda result: calls.append(result))
    assert application.read_producer_proof(pin) is verified
    assert calls == ['verified', verified]


def test_adopted_definition_preserves_order_and_refuses_other_bytes(tmp_path, monkeypatch):
    from viewer_publication import archive_model_proof as application

    definition = {'inputs': [{'name': 'second'}, {'name': 'first'}]}
    pin = pin_json(tmp_path/'definition.json', definition)
    proof = SimpleNamespace(manifest={'producer_evidence': {'adoption': {'definition_sha256': pin['sha256']}}})
    monkeypatch.setattr(application, 'require_producer_proof', lambda proof: None)
    assert application.read_producer_definition(pin, proof) == definition
    other = pin_json(tmp_path/'other.json', {'inputs': list(reversed(definition['inputs']))})
    with pytest.raises(ValueError, match='accepted proof adoption'):
        application.read_producer_definition(other, proof)


@pytest.fixture
def retained(tmp_path):
    from viewer_publication.archive_model_profile import native_report_policy

    payload = tmp_path/'payload.parquet'
    payload.write_bytes(b'File bytes are retained; this metadata test must not read them.')
    inputs = [dict(name='captured', kind='native_table', metadata_location='file:///original/metadata.json',
                   table_uuid='00000000-0000-4000-8000-000000000001', snapshot=7, schema_id=3),
              dict(name='lookup', kind='parquet', path=str(payload))]
    job = dict(inputs=inputs, steps=[], outputs=[], queries=[dict(name='invariants', sql='SELECT 0::BIGINT AS invalid')])
    job_pin = pin_json(tmp_path/'original-job.json', job)
    native_schema = pa.schema([pa.field('key', pa.int64(), nullable=False, metadata={b'PARQUET:field_id': b'117'})])
    counter_schema = pa.schema([pa.field('invalid', pa.int64(), nullable=True)])
    schemas = {}
    def encoded(schema):
        raw = schema.serialize().to_pybytes()
        digest = sha256(raw).hexdigest()
        schemas[digest] = base64.b64encode(raw).decode()
        return digest
    native_digest = encoded(native_schema)
    counter_digest = encoded(counter_schema)
    inferred = dict(profile='urn:docspec:job:schema-only:1', status='inferred',
        job={key: job_pin[key] for key in ('path', 'sha256')}, job_size=job_pin['size'],
        input_admission='not_run', execution='not_run', schemas=schemas,
        inputs=[dict(name=item['name'], schema_sha256=native_digest) for item in inputs], steps=[], outputs=[],
        queries=[dict(name='invariants', schema_sha256=counter_digest)])
    runtime = dict(distributionSha256='a'*64, commit='b'*40)
    policy = native_report_policy(Path(job_pin['path']).read_bytes(), [], inferred, policy_id='required')
    preparation = dict(job=job_pin, result=pin_json(tmp_path/'original-inference.json', inferred),
        policy=pin_json(tmp_path/'original-policy.json', policy), runtime=runtime)
    return SimpleNamespace(job=job, preparation=preparation, inferred=inferred,
        runtime=runtime, native_schemas={'captured': schemas[native_digest]}, payload=payload)


def test_retained_preparation_preserves_original_bytes(retained):
    from viewer_publication.archive_format import _retained_preparation

    original = Path(retained.preparation['job']['path']).read_bytes()
    raw, inferred, schemas = _retained_preparation(retained.preparation, retained.job,
        retained.native_schemas, retained.runtime)
    assert raw == original and b'\t' in raw
    assert inferred == retained.inferred
    assert schemas['captured'] == retained.native_schemas['captured']


@pytest.mark.parametrize('change', ['runtime', 'job', 'job_pin', 'inference_pin', 'schema_id', 'native_nullability'])
def test_retained_preparation_refuses_changed_identity(retained, change):
    from viewer_publication.archive_format import _retained_preparation

    saved, job, schemas = deepcopy((retained.preparation, retained.job, retained.native_schemas))
    if change == 'runtime':
        saved['runtime']['commit'] = 'c'*40
    elif change == 'job':
        job['inputs'][0]['snapshot'] += 1
    elif change == 'job_pin':
        saved['job']['sha256'] = '0'*64
    elif change == 'inference_pin':
        saved['result']['size'] += 1
    else:
        field = pa.field('key', pa.int64(), nullable=change == 'native_nullability',
                         metadata={b'PARQUET:field_id': b'118' if change == 'schema_id' else b'117'})
        schemas['captured'] = base64.b64encode(pa.schema([field]).serialize().to_pybytes()).decode()
    with pytest.raises(ValueError, match='runtime|job|identity|schema'):
        _retained_preparation(saved, job, schemas, retained.runtime)


def test_retained_release_preparation_opens_no_payload_or_native_process(retained, tmp_path, monkeypatch):
    from viewer_publication import archive_catalog, archive_model_proof
    from viewer_publication.archive_format import prepare_native_release
    import ddk.catalog_managed_jobs as managed
    import ddk.catalog_native_rules as rules
    import pyarrow.parquet as pq

    request_dir = tmp_path/'request'
    request_dir.mkdir()
    project = request_dir/'definitions'
    project.mkdir()
    workspace = tmp_path/'native'
    workspace.mkdir()
    producer_definition = dict(definition='adopted', model=dict(
        job_sha256=retained.preparation['job']['sha256'], policy_id='required',
        policy_sha256=retained.preparation['policy']['sha256']))
    bindings = dict(producer_adoption={'original': 'adoption'}, snapshot_inputs=[{'original': 'custody'}],
                    prerequisites=[{'original': 'accepted proof'}])
    monkeypatch.setattr(archive_model_proof, 'require_producer_proof', lambda proof: None)
    monkeypatch.setattr(archive_model_proof, 'producer_proof_bindings',
        lambda *args, **kwargs: (bindings, retained.native_schemas))
    monkeypatch.setattr(archive_catalog, 'captured_catalog_options', lambda project: {'native_rule_profile': object()})
    monkeypatch.setattr(archive_catalog, 'native_catalog_mapping', lambda *args, **kwargs: {})
    monkeypatch.setattr(rules, 'native_rule_artifact', lambda *args, **kwargs: {'rules': 'captured'})
    monkeypatch.setattr(managed, 'managed_job_definition', lambda *args, **kwargs: 'adopted')
    def must_not_run(*args, **kwargs):
        pytest.fail('Retained metadata preparation reopened a payload or executed native inference')
    monkeypatch.setattr(pq, 'read_schema', must_not_run)
    original_open = Path.open
    def control_only(path, *args, **kwargs):
        if path == retained.payload:
            must_not_run()
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', control_only)
    request = prepare_native_release(retained.job, [],
        adapter=SimpleNamespace(tool=retained.runtime, prepare_job=must_not_run),
        project=project, catalog_result=object(), request_dir=request_dir, workspace=workspace,
        dataset='archive', operation='model', policy_id='required',
        file_pins={str(retained.payload): dict(sha256='d'*64, size=retained.payload.stat().st_size)},
        producer_proof=object(), producer_definition=producer_definition,
        expected_epoch=19, expected_selection=None, controls_dir=tmp_path/'release', private_outputs=[],
        origin={'kind': 'model'}, capture_scope=None, content_files={}, entity_digests=None,
        retained_preparation=retained.preparation)
    saved = json.loads(Path(request['path']).read_bytes())['native']
    for name in ('job', 'policy'):
        assert saved[name] == {key: retained.preparation[name][key] for key in ('path', 'sha256')}
    assert saved['expected_epoch'] == 19
    assert all(saved[name] == value for name, value in bindings.items())
    assert not (request_dir/'job.json').exists() and not (request_dir/'policy.json').exists()


@pytest.mark.parametrize('provide_source', [False, True])
def test_measurement_resumes_the_original_request(tmp_path, monkeypatch, provide_source):
    import importlib.util
    from viewer_publication import archive_model_job

    path = Path(__file__).parents[3]/'scripts/measure/documents_slice.py'
    specification = importlib.util.spec_from_file_location('document_slice_measurement', path)
    measurement = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(measurement)
    request = tmp_path/'request.json'
    request.write_text('{}')
    digest = sha256(request.read_bytes()).hexdigest()
    packages = tmp_path/'packages.parquet'
    packages.write_bytes(b'Package selection is outside this routing test.')
    runtime = tmp_path/'runtime.json'
    source = tmp_path/'private-source.json' if provide_source else None
    calls = []
    files = {'list.parquet': '/retained/original/list.parquet'}
    def resume(original, *, engine_config, snapshot_source):
        calls.append((original, engine_config, snapshot_source))
        return dict(release_id='checked-model', files=files)
    def observe(db, selected, live, population):
        assert selected is files and population == packages
        return {'list_rows': 3}
    monkeypatch.setattr(archive_model_job, 'resume_prepared', resume)
    monkeypatch.setattr(measurement, 'measure', observe)
    args = ['--prepared-request', str(request), '--request-sha256', digest,
        '--engine-config', str(runtime), '--packages', str(packages), '--live', str(tmp_path/'live'),
        '--work', str(tmp_path/'measurement')]
    if source is not None:
        args += ['--snapshot-source', str(source)]
    measurement.main(args)
    original = dict(path=str(request), sha256=digest)
    assert calls == [(original, runtime, source)]
    assert json.loads((tmp_path/'measurement/measure.json').read_bytes()) == dict(
        release_id='checked-model', prepared_request=original, list_rows=3)

"""Exact native reports, recovery and refusal under current DDK definitions."""
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest


def native_receipt(request_dir):
    metadata = json.loads((request_dir/'catalog-metadata.json').read_text())
    return json.loads(Path(metadata['managedExecutions'][0]['receipt']['path']).read_text())


def test_metadata_rows_do_not_change_data_or_become_zero_count_guards(tmp_path, build_native_fixture):
    original, original_files = build_native_fixture(name='original')
    repeated, repeated_files = build_native_fixture(name='repeated', metadata_queries=[
        dict(name='input_receipts', sql="SELECT 'receipts/fixture.jsonl.gz' AS receipt_key")])
    receipt = native_receipt(tmp_path/'repeated/request')
    reports = {query['name']: query['data'] for query in receipt['result']['result']['queries']}
    assert reports['input_receipts'] == [dict(receipt_key='receipts/fixture.jsonl.gz')]
    assert receipt['result']['accepted_qualification'] is not None
    first = {item['name']: item for item in original['files'] if item['name'].endswith('.parquet')}
    second = {item['name']: item for item in repeated['files'] if item['name'].endswith('.parquet')}
    assert first == second
    for name in first:
        assert original_files[name].read_bytes() == repeated_files[name].read_bytes()


def test_cold_retry_keeps_catalog_and_data_after_caller_payloads_and_adapter_records_go(
        tmp_path, build_native_fixture, release_adapter):
    from ddk.adapters.docspec import DocSpecAdapter
    from viewer_publication.archive_format import execute_native_release

    original, files = build_native_fixture()
    request_dir = tmp_path/'fixture/request'
    path = request_dir/'release-request.json'
    prepared = dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())
    job = json.loads((request_dir/'job.json').read_text())
    native_before = {name: (value.stat().st_ino, value.stat().st_mtime_ns, value.stat().st_ctime_ns)
                     for name, value in files.items() if name.endswith('.parquet')}
    bytes_before = {name: value.read_bytes() for name, value in files.items() if not name.endswith('.parquet')}
    for item in job['inputs']:
        for member in item['files']:
            Path(member['path']).unlink()
    (request_dir/'job.json').unlink()
    (request_dir/'policy.json').unlink()
    shutil.rmtree(release_adapter.evidence_dir)
    fresh = DocSpecAdapter(release_adapter.executable, release_adapter.limits, timeout=120,
        source_commit=release_adapter.tool.get('commit'), evidence_dir=tmp_path/'fresh-evidence')
    resumed, resumed_files = execute_native_release(prepared, adapter=fresh)
    assert resumed == original and resumed_files == files
    assert {name: value.read_bytes() for name, value in resumed_files.items()
            if not name.endswith('.parquet')} == bytes_before
    assert {name: (value.stat().st_ino, value.stat().st_mtime_ns, value.stat().st_ctime_ns)
            for name, value in resumed_files.items() if name.endswith('.parquet')} == native_before


def test_retry_after_receipt_retention_keeps_the_first_accepted_observation(
        tmp_path, build_native_fixture, release_adapter, monkeypatch):
    from ddk.adapters.docspec import DocSpecAdapter
    from viewer_publication import archive_format

    write = archive_format._request_artifact
    def interrupt(directory, name, value):
        if name == 'catalog-metadata.json':
            raise OSError('Injected interruption after accepted receipt retention')
        return write(directory, name, value)
    with monkeypatch.context() as patch:
        patch.setattr(archive_format, '_request_artifact', interrupt)
        with pytest.raises(OSError, match='Injected interruption'):
            build_native_fixture()
    request = tmp_path/'fixture/request'
    accepted = request/'native-accepted.json'
    original = accepted.read_bytes()
    custody = (accepted.stat().st_ino, accepted.stat().st_mtime_ns, accepted.stat().st_ctime_ns)
    assert not (request/'catalog-metadata.json').exists()
    assert not (tmp_path/'fixture/controls').exists()
    shutil.rmtree(release_adapter.evidence_dir)
    adapter = DocSpecAdapter(release_adapter.executable, release_adapter.limits, timeout=120,
        source_commit=release_adapter.tool.get('commit'), evidence_dir=tmp_path/'fresh-evidence')
    path = request/'release-request.json'
    manifest, files = archive_format.execute_native_release(
        dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest()), adapter=adapter)
    assert accepted.read_bytes() == original
    assert (accepted.stat().st_ino, accepted.stat().st_mtime_ns, accepted.stat().st_ctime_ns) == custody
    assert native_receipt(request) == json.loads(original)
    assert json.loads(files['manifest.json'].read_text()) == manifest


@pytest.mark.parametrize('table, field, counter', [
    ('witnesses', 'source_locator', 'null_witnesses_source_locator'),
    ('documents', 'filename', 'null_list_filename'),
])
def test_missing_required_value_refuses_selection_and_retains_native_result(
        tmp_path, build_native_fixture, table, field, counter):
    from viewer_publication.archive_format import NativeReleaseNotReady

    value = json.loads((Path(__file__).parents[3]/'model/fixtures/hand-release.json').read_text())
    value[table][0][field] = None
    fixture = tmp_path/'missing-required-value.json'
    fixture.write_text(json.dumps(value))
    with pytest.raises(NativeReleaseNotReady) as failure:
        build_native_fixture(fixture)
    observed = failure.value.response
    assert observed['result']['status'] == 'completed'
    assert observed['result']['accepted_qualification'] is None
    assert observed['result']['selection'] == 'pending'
    report = next(query for query in observed['result']['result']['queries']
                  if query['name'] == 'relationship_invariants')
    assert report['data'][0][counter] == 1
    assert not (tmp_path/'fixture/controls').exists()
    assert Path(observed['evidence']['path']).is_file()
    assert all(Path(item['path']).is_file() for item in observed['result']['completed_outputs'])

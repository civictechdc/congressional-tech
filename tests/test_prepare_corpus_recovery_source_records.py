"""Maintained source preparation binds bytes, source URLs and actual capture times."""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_corpus_recovery_source_records as module


@pytest.fixture
def fixture(tmp_path):
    batch = tmp_path/'batch'; batch.mkdir()
    raw = b'%PDF-1.4\nsource bytes'; body = tmp_path/'body.pdf'; body.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest(); key = f'bodies/sha256/{sha[:2]}/{sha}.gz'
    row = dict(original_url='https://original.test/file.pdf', recovered_url='https://archive.test/file.pdf',
        body_path=str(body), body_key=key, sha256=sha, bytes=len(raw), kind='pdf',
        recovery_basis='user_accepted_url_variant', reused_retained_body=True, validated=True)
    captures = tmp_path/'captures.parquet'
    def seal(rows=None, prior=None):
        (batch/'recoveries.json').write_text(json.dumps(rows if rows is not None else [row]))
        (batch/'manifest.json').write_text(json.dumps(dict(files={'recoveries.json': module.digest(batch/'recoveries.json')})))
        schema = pa.schema([('context_url',pa.string()),('body_key',pa.string()),('retrieved_at',pa.string()),
                            ('receipt_key',pa.string()),('receipt_line',pa.int64())])
        pq.write_table(pa.Table.from_pylist(prior or [], schema=schema), captures)
    seal()
    def outputs():
        return json.loads((batch/module.OUTPUTS[0]).read_text()), json.loads((batch/module.OUTPUTS[1]).read_text())
    return batch, row, captures, seal, outputs


def test_exact_url_and_body_choose_latest_documented_capture(fixture):
    batch,row,captures,seal,outputs = fixture
    def cap(url, key, at, receipt): return dict(context_url=url,body_key=key,retrieved_at=at,receipt_key=receipt,receipt_line=1)
    prior = [cap(row['recovered_url'],row['body_key'],'2020-01-01T12:00:00+00:00','first'),
             cap(row['recovered_url'],row['body_key'],'2020-01-01T09:00:00-04:00','latest'),
             cap('https://other.test/file.pdf',row['body_key'],'2026-01-01T00:00:00Z','wrong-url'),
             cap(row['recovered_url'],'wrong-body','2026-01-01T00:00:00Z','wrong-body')]
    seal(prior=prior); manifest = (batch/'manifest.json').read_bytes()
    module.prepare(batch,captures); records,report = outputs()
    record = records[0]['record']
    assert record['retrieved_at'] == '2020-01-01T09:00:00-04:00'
    assert record['recovery_evidence']['original_capture']['receipt_key'] == 'latest'
    assert records[0]['captures'][0]['body_key'] == row['body_key']
    assert records[0]['preserve_download_state'] is True
    assert report['batch_manifest_sha256'] == hashlib.sha256(manifest).hexdigest()
    assert (batch/'manifest.json').read_bytes() == manifest


def test_alias_requires_exact_body_and_explicit_package_basename(fixture, tmp_path):
    batch,row,captures,seal,outputs = fixture
    row['package_id'] = 'CHRG-123'; seal()
    aliases = tmp_path/'aliases.json'
    aliases.write_text(json.dumps([
        dict(body_key='wrong',context_url='https://gov.test/CHRG-123.pdf',retrieved_at='2021-01-01T00:00:00Z'),
        dict(body_key=row['body_key'],context_url='https://gov.test/OTHER.pdf',retrieved_at='2021-01-01T00:00:00Z'),
        dict(body_key=row['body_key'],context_url='https://gov.test/CHRG-123.PDF?download=1',retrieved_at='2020-01-01T00:00:00Z')]))
    module.prepare(batch,captures,aliases); records,report = outputs()
    assert records[0]['record']['url'] == 'https://gov.test/CHRG-123.PDF?download=1'
    assert records[0]['record']['retrieved_at'] == '2020-01-01T00:00:00Z'
    assert report['timestamp_alias_evidence_sha256'] == module.digest(aliases)


def test_direct_archive_timestamp_keeps_original_capture_semantics(fixture):
    batch,row,captures,seal,outputs = fixture
    row['candidate'] = {'timestamp':'20120102030405'}
    row['request_evidence'] = str(batch/'unused-transport.json')
    seal()
    module.prepare(batch,captures); records,_ = outputs()
    assert records[0]['record']['retrieved_at'] == '2012-01-02T03:04:05+00:00'
    assert records[0]['record']['recovery_evidence']['timestamp_basis'] == 'archive_index_capture_time'


def test_rendered_copy_keeps_render_time_and_original_snapshot_provenance(fixture):
    batch,row,captures,seal,outputs = fixture
    row.update(rendered_copy=True,retrieved_at='2026-10-16T12:00:00Z',candidate={'timestamp':'20120102030405'},
               matching_basis='Browser-rendered archive copy')
    seal(); module.prepare(batch,captures); records,_ = outputs(); record = records[0]['record']
    assert record['retrieved_at'] == '2026-10-16T12:00:00Z'
    assert record['rendered_copy'] is True
    assert record['recovery_evidence']['original_archive_response_bytes'] is False
    assert record['recovery_evidence']['acquisition']['candidate']['timestamp'] == '20120102030405'
    assert record['recovery_evidence']['acquisition']['matching_basis'] == 'Browser-rendered archive copy'


def test_missing_timestamp_is_unresolved_and_never_uses_now(fixture):
    batch,row,captures,seal,outputs = fixture
    row.update(rendered_copy=True,candidate={'timestamp':'20120102030405'}); seal()
    module.prepare(batch,captures); records,report = outputs()
    assert records == []
    assert report['unresolved'] == [dict(original_url=row['original_url'],reason='source_timestamp_not_established')]


def test_transport_time_is_explicit_and_evidence_is_pinned(fixture, tmp_path):
    batch,row,captures,seal,outputs = fixture
    evidence = tmp_path/'receipt.json'; evidence.write_text(json.dumps({'record':{'retrieved_at':'2024-01-01T00:00:00Z'}}))
    row['request_evidence'] = str(evidence); seal()
    module.prepare(batch,captures); records,report = outputs()
    assert records[0]['record']['retrieved_at'] == '2024-01-01T00:00:00Z'
    assert report['input_hashes'][str(evidence.resolve())] == module.digest(evidence)


def test_changed_body_refused_before_any_output(fixture):
    batch,row,captures,seal,outputs = fixture
    Path(row['body_path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='body changed'): module.prepare(batch,captures)
    assert not any((batch/name).exists() for name in module.OUTPUTS)


def test_existing_outputs_are_not_replaced_and_partial_output_is_diagnosed(fixture):
    batch,row,captures,seal,outputs = fixture
    row['candidate'] = {'timestamp':'20120102030405'}; seal()
    link = module.os.link
    def fail_report(source,destination):
        if Path(destination).name == module.OUTPUTS[1]: raise OSError('Injected report publish failure')
        return link(source,destination)
    with patch.object(module.os,'link',side_effect=fail_report):
        with pytest.raises(OSError,match='Injected'): module.prepare(batch,captures)
    assert (batch/module.OUTPUTS[0]).exists()
    assert not (batch/module.OUTPUTS[1]).exists()
    previous = (batch/module.OUTPUTS[0]).read_bytes()
    with pytest.raises(ValueError,match='diagnose partial'): module.prepare(batch,captures)
    assert (batch/module.OUTPUTS[0]).read_bytes() == previous


def test_changed_sealed_recovery_rows_are_refused(fixture):
    batch,row,captures,seal,outputs = fixture
    (batch/'recoveries.json').write_text('[]')
    with pytest.raises(ValueError,match='Sealed batch'): module.prepare(batch,captures)

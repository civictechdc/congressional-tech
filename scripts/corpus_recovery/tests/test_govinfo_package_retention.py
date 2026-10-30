"""Exercise the actual preparation and import path using one tiny full package."""
from copy import deepcopy
import base64
import gzip
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
from zipfile import ZipFile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/corpus_recovery'))
import prepare_corpus_recovery_batch as batch_module
import prepare_corpus_recovery_source_records as source_module
from corpus_recovery import govinfo
from corpus_recovery.inventory import sealed_inputs
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, prepare_capture_table


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def key(raw):
    digest = sha(raw)
    return f'bodies/sha256/{digest[:2]}/{digest}.gz'


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


@pytest.fixture
def package(tmp_path):
    package_id = 'BILLS-119hr1ih'
    files = {f'{package_id}/pdf/{package_id}.pdf': b'%PDF-1.4\nretained document',
             f'{package_id}/xml/{package_id}.xml': b'<bill>Official document</bill>',
             f'{package_id}/mods.xml': b'<mods>Package metadata</mods>'}
    zip_path = tmp_path / 'package.zip'
    with ZipFile(zip_path, 'w') as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    members = []
    for name, raw in files.items():
        body_path = tmp_path / sha(raw)
        body_path.write_bytes(raw)
        members.append(dict(name=name, status='completed', path=str(body_path), sha256=sha(raw), bytes=len(raw)))
    url = f'https://www.govinfo.gov/content/pkg/{package_id}.zip'
    receipt_path = tmp_path / 'receipt.json'
    receipt = dict(package_id=package_id, outcome='saved', members=members,
        record=dict(url=url, requested_url=url, retrieved_at='2026-10-16T03:04:05Z',
                    http_status=200, complete=True, local_body_path=str(zip_path),
                    body_sha256=sha(zip_path.read_bytes()), response_headers={'content-type': 'application/zip'},
                    content=dict(sha256=sha(zip_path.read_bytes()), body=None, media_type='application/zip')))
    write(receipt_path, receipt)
    rows = [dict(original_url=f'https://committee.test/target-{n}.pdf',
                 recovered_url='https://www.govinfo.gov/content/pkg/' + members[0]['name'],
                 package_id=package_id, archive_member=members[0]['name'], request_evidence=str(receipt_path),
                 body_path=members[0]['path'], body_key=key(files[members[0]['name']]),
                 sha256=members[0]['sha256'], bytes=members[0]['bytes'], kind='pdf',
                 recovery_basis='official_document_identifier', validated=True) for n in range(2)]
    accepted = dict(recoveries=deepcopy(rows), retained_policy='unchanged')
    for name, data in [('recovered-files.json', rows), ('prepared-accepted.json', accepted),
                       ('prepared-zip-receipts.json', []), ('zip-member-reconciliation.json', []),
                       ('deferred.json', [])]:
        write(tmp_path / name, data)
    return dict(root=tmp_path, rows=rows, files=files, receipt=receipt, receipt_path=receipt_path,
                zip_path=zip_path, accepted=accepted, destination=tmp_path / 'sealed')


def prepare(fixture):
    return batch_module.prepare(fixture['root'], fixture['root'] / 'deferred.json', fixture['destination'])


def test_complete_package_import_preserves_mappings_and_existing_data(package):
    with patch.object(govinfo, 'prepare_capture', wraps=govinfo.prepare_capture) as expand:
        manifest = prepare(package)
    assert expand.call_count == 1  # Two recovery targets share a single expansion.
    batch = package['destination']
    assert manifest['zip_parents'] == 1
    assert manifest['distinct_bodies'] == 4  # ZIP and three members; receipt stays receipt data.
    assert json.loads((batch / 'recoveries.json').read_text()) == package['rows']
    assert json.loads((batch / 'accepted.json').read_text()) == package['accepted']
    captured = package['root'] / 'captures.parquet'
    prior_body = b'untouched retained source'
    prior_stored = gzip.compress(prior_body, mtime=123)
    baseline_captures = prepare_capture_table([dict(context_url='https://untouched.test',
        sha256=sha(prior_body), bytes=len(prior_body), media_type='text/plain',
        stored_sha256=sha(prior_stored), stored_bytes=len(prior_stored),
        retrieved_at='2020-01-01T00:00:00Z', receipt_key='receipts/untouched.jsonl.gz', receipt_line=7)])
    assert baseline_captures.schema.equals(CAPTURE_SCHEMA) and 'body_key' not in baseline_captures.column_names
    pq.write_table(baseline_captures, captured)
    report = source_module.prepare(batch, captured)
    assert report['unresolved'] == []
    files, inventory, counts = sealed_inputs(batch)
    records = json.loads((batch / 'prepared-source-records.json').read_text())
    assert len(records) == 2
    for target, selected in zip(package['rows'], records, strict=True):
        assert selected['record']['url'] == target['recovered_url']
        assert selected['record']['source_associations'] == [dict(original_url=target['original_url'], basis=target['recovery_basis'])]
        assert len(selected['captures']) == 1
        assert selected['captures'][0]['body_key'] == target['body_key']
        assert selected['record']['retrieved_at'] == package['receipt']['record']['retrieved_at']
        assert selected['record']['recovery_evidence']['timestamp_basis'] == 'sealed_official_package_member_capture'
    package_record = json.loads((batch / 'zip-receipts.json').read_text())[0]
    assert all(c['pointer'] == ['content', 'body'] or c['pointer'][0] == 'archive_members'
               for c in package_record['captures'])
    for body_key, info in inventory.items():
        assert sha(Path(info['path']).read_bytes()) == info['sha256']
    evidence = package_record['record']['recovery_package']
    assert base64.b64decode(evidence['acquisition_receipt_base64'], validate=True) == package['receipt_path'].read_bytes()
    assert sha(package['receipt_path'].read_bytes()) == evidence['acquisition_receipt_sha256']
    assert json.loads((batch / 'accepted.json').read_text()) == package['accepted']


@pytest.mark.parametrize('damage', ['zip_bytes', 'member_bytes', 'missing_member', 'incomplete_receipt',
                                    'wrong_source', 'wrong_selected_member', 'omitted_member', 'missing_receipt'])
def test_damaged_package_fails_before_batch_is_sealed(package, damage):
    receipt, rows = package['receipt'], package['rows']
    if damage == 'zip_bytes':
        package['zip_path'].write_bytes(b'corrupt')
    elif damage == 'member_bytes':
        Path(receipt['members'][-1]['path']).write_bytes(b'corrupt')
    elif damage == 'missing_member':
        Path(receipt['members'][-1]['path']).unlink()
    elif damage == 'incomplete_receipt':
        receipt['record']['complete'] = False
    elif damage == 'wrong_source':
        receipt['record']['url'] = 'https://wrong.test/package.zip'
    elif damage == 'wrong_selected_member':
        rows[0]['archive_member'] = receipt['members'][1]['name']
    elif damage == 'omitted_member':
        receipt['members'].pop()
    elif damage == 'missing_receipt':
        del rows[0]['request_evidence']
    write(package['receipt_path'], receipt)
    write(package['root'] / 'recovered-files.json', rows)
    with pytest.raises((ValueError, FileNotFoundError)):
        prepare(package)
    assert not package['destination'].exists()


def test_archive_limit_refusal_is_not_silently_treated_as_full_retention(package):
    from congress_api.retention.archive_members import ZipLimits
    original = govinfo.prepare_capture
    def limited(*args, **kwargs):
        return original(*args, **kwargs, archive_limits=ZipLimits(max_members=1))
    with patch.object(govinfo, 'prepare_capture', side_effect=limited):
        with pytest.raises(ValueError, match='extraction is incomplete'):
            prepare(package)
    assert not package['destination'].exists()


def test_deferred_metadata_cannot_enter_as_an_unselected_sibling(package):
    member = package['receipt']['members'][-1]
    write(package['root'] / 'deferred.json', [dict(url='https://deferred.test', sha256=member['sha256'])])
    with pytest.raises(ValueError, match='Deferred body'):
        prepare(package)
    assert not package['destination'].exists()


def test_deferred_member_url_alone_prevents_its_import(package):
    name = package['receipt']['members'][-1]['name']
    write(package['root'] / 'deferred.json', [dict(url='https://www.govinfo.gov/content/pkg/' + name)])
    with pytest.raises(ValueError, match='Deferred GovInfo package member'):
        prepare(package)
    assert not package['destination'].exists()


def test_retained_body_without_local_package_does_not_trigger_download(package):
    for row in package['rows']:
        row.pop('archive_member')
        row.pop('request_evidence')
        row['reused_retained_body'] = True
    write(package['root'] / 'recovered-files.json', package['rows'])
    manifest = prepare(package)
    assert manifest['zip_parents'] == 0
    assert manifest['distinct_bodies'] == 1

"""Recovery preparation binds stable status to the exact native catalog."""
from copy import deepcopy
import hashlib
import json

import pytest

from test_filename_recoveries import publisher
from test_filename_native_recoveries import prepare, records
from congress_api.retention.viewer_inventory import verify_inventory


def selected():
    value, _ = prepare(records())
    manifest = dict(version=6, source_identity=value['source_identity'],
                    source_manifest=dict(version=2, selection={'key': 'exact'}),
                    info={name: value[name] for name in ('catalog_id', 'rows', 'entries')},
                    roots=dict(sources={'sha256': 'sources'}, components={'sha256': 'components'}), files={})
    return manifest, value


def proof(root):
    path = root / 'recovery-prepared.json'
    return verify_inventory(root, {path.name: dict(bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest())}, context={})


def test_native_preparation_binds_status_without_legacy_files(tmp_path, monkeypatch):
    manifest, status = selected()
    accepted = (None, None, None, None)
    monkeypatch.setattr(publisher, 'index_recoveries',
                        lambda *a, **k: pytest.fail('Native status scanned historical full tables'))
    prepared = publisher.prepare_recovery(tmp_path, manifest, accepted, index=status)
    assert prepared['value'] == status
    assert publisher.load_prepared_recovery(tmp_path, manifest, accepted, validation=proof(tmp_path)) == status
    assert list(tmp_path.iterdir()) == [tmp_path / 'recovery-prepared.json']


@pytest.mark.parametrize('change', ['identity', 'counts', 'version'])
def test_native_preparation_rejects_foreign_status_before_saving(tmp_path, change):
    manifest, status = selected()
    if change == 'identity':
        status = dict(status, source_identity={'selector_sha256': 'wrong'})
    elif change == 'counts':
        status = dict(status, rows=10000)
    else:
        status = dict(status, version=1)
    with pytest.raises(ValueError, match='identity|catalog'):
        publisher.prepare_recovery(tmp_path, manifest, (None,) * 4, index=status)
    assert not list(tmp_path.iterdir())


def test_native_preparation_requires_explicit_stable_index(tmp_path):
    manifest, _ = selected()
    with pytest.raises(ValueError, match='stable'):
        publisher.prepare_recovery(tmp_path, manifest, (None,) * 4)


def test_prepared_native_status_rejects_changed_root_or_acceptance(tmp_path):
    manifest, status = selected()
    publisher.prepare_recovery(tmp_path, manifest, (None,) * 4, index=status)
    validation = proof(tmp_path)
    changed = deepcopy(manifest)
    changed['roots']['sources']['sha256'] = 'other'
    for candidate, accepted in [(changed, (None,) * 4), (manifest, (None, None, None, 'changed'))]:
        with pytest.raises(ValueError, match='inputs changed'):
            publisher.load_prepared_recovery(tmp_path, candidate, accepted, validation=validation)


def test_reverified_custody_does_not_replace_selected_acceptance(tmp_path):
    manifest, status = selected()
    prepared = publisher.prepare_recovery(tmp_path, manifest, (None,) * 4, index=status)
    prepared['value']['accepted'] = [{'not': 'the selected accepted input'}]
    (tmp_path / 'recovery-prepared.json').write_text(json.dumps(prepared))
    with pytest.raises(ValueError, match='acceptance'):
        publisher.load_prepared_recovery(tmp_path, manifest, (None,) * 4, validation=proof(tmp_path))


def test_reuse_inputs_bind_native_catalog_and_roots():
    manifest, _ = selected()
    value = publisher.recovery_inputs('selector', 'viewer', manifest, None, release_identity={'local': True})
    assert value['version'] == 2 and value['source_identity'] == manifest['source_identity']
    changed = deepcopy(manifest)
    changed['roots']['components'] = {'sha256': 'changed'}
    assert publisher.recovery_inputs('selector', 'viewer', changed, None,
                                    release_identity={'local': True}) != value

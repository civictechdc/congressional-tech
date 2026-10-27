"""Local custody replaces hosted artifact metadata, never output admission."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from test_viewer_publication_attempt import source, configured_native_fixture, ready
from viewer_publication import attempt

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('local_preparation_publisher',
    ROOT / 'scripts/publication/publish_local_preparation.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


@pytest.fixture(autouse=True)
def no_github(monkeypatch):
    monkeypatch.setattr(attempt, 'github_json', lambda *args: pytest.fail('Local publication contacted GitHub'))


def publish(ready, **kwargs):
    remote, root, _ = ready
    return local.publish_local(remote, root, probe=lambda *args: None, **kwargs)


def test_local_preparation_publishes_and_explicitly_resumes_without_artifact_service(ready):
    remote, root, prepared = ready
    assert publish(ready)['status'] == 'published'
    custody = json.loads((root / local.RECEIPT).read_bytes())
    assert custody['kind'] == 'local_preparation' and custody['run_id'] == '123'
    assert custody['preparation_sha256'] == prepared['preparation_sha256']
    assert custody['directory'] == str(root.resolve()) and 'id' not in custody
    started = next(json.loads(raw) for key, raw in remote.objects.items()
        if key.startswith('viewer-publications/attempts/') and key.endswith('/00000000.json'))
    authority = started['value']['binding']['artifact']
    assert authority['local_receipt_sha256'] == hashlib.sha256((root / local.RECEIPT).read_bytes()).hexdigest()
    before = [write for write in remote.puts if not write[0].startswith('viewer-publications/attempts/')]
    with pytest.raises(ValueError, match='explicit --resume'):
        publish(ready)
    assert publish(ready, resume=True)['status'] == 'published'
    assert [write for write in remote.puts if not write[0].startswith('viewer-publications/attempts/')] == before


def test_local_resume_can_recover_failure_before_first_remote_journal(ready):
    remote, root, _ = ready
    remote.reject_journal = True
    with pytest.raises(RuntimeError, match='outcome is uncertain') as error:
        publish(ready)
    assert isinstance(error.value.request_error, OSError)
    assert (root / local.RECEIPT).is_file()
    remote.reject_journal = False
    assert publish(ready, resume=True)['status'] == 'published'


@pytest.mark.parametrize('change', ['same-size-output', 'extra-output', 'missing-output'])
def test_local_custody_cannot_bypass_full_prepared_inventory(ready, change):
    remote, root, _ = ready
    receipt = json.loads((root / 'preparation.json').read_bytes())
    path = next(root / name for name in receipt['files'] if name.endswith('.parquet'))
    if change == 'same-size-output':
        raw = bytearray(path.read_bytes()); raw[5] ^= 1; path.write_bytes(raw)
    elif change == 'extra-output':
        (root / 'publication' / 'unexpected').write_bytes(b'extra')
    else:
        path.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        publish(ready)
    assert not remote.puts and not (root / local.RECEIPT).exists()


@pytest.mark.parametrize('change', ['receipt', 'move', 'adapter'])
def test_local_receipt_refuses_changed_custody_before_resume_write(ready, tmp_path, monkeypatch, change):
    remote, root, _ = ready
    assert publish(ready)['status'] == 'published'
    before = len(remote.puts)
    if change == 'receipt':
        p = root / local.RECEIPT
        value = json.loads(p.read_bytes()); value['run_id'] = 'another'
        p.write_text(json.dumps(value))
    elif change == 'move':
        moved = tmp_path / 'moved'; shutil.copytree(root, moved)
        ready = remote, moved, ready[2]
    else:
        script = tmp_path / 'changed-adapter.py'; script.write_bytes(b'changed')
        monkeypatch.setattr(local, '__file__', str(script))
    with pytest.raises(ValueError, match='custody changed'):
        publish(ready, resume=True)
    assert len(remote.puts) == before


def test_local_publish_rechecks_current_selectors(ready):
    remote, root, _ = ready
    remote.versions['indexes/catalog.json'] = 'changed'
    assert publish(ready)['status'] == 'superseded'
    assert not remote.puts


def test_local_resume_requires_receipt(ready):
    with pytest.raises(FileNotFoundError):
        publish(ready, resume=True)
    assert not ready[0].puts


def test_local_publish_excludes_a_second_owner(ready):
    remote, root, _ = ready
    with (root / '.local-publication.lock').open('ab') as held:
        local.fcntl.flock(held, local.fcntl.LOCK_EX | local.fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='already being published'):
            publish(ready)
    assert not remote.puts and not (root / local.RECEIPT).exists()

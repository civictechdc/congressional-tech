"""Body reconciliation uses fresh versions and falls back to exact bytes."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from reconcile_corpus_recovery_bodies import reconcile, sealed_inputs, run


class Client:
    def __init__(self, raw):
        self.data = gzip.compress(raw, mtime=0)
        self.gets = self.heads = 0

    def head_object(self, **kwargs):
        self.heads += 1
        return dict(ETag=hashlib.md5(self.data).hexdigest(), ContentLength=len(self.data))

    def get_object(self, **kwargs):
        self.gets += 1
        return dict(self.head_object(**kwargs), Body=io.BytesIO(self.data))


def setup(raw=b'current exact body'):
    sha = hashlib.sha256(raw).hexdigest()
    key = f'bodies/sha256/{sha[:2]}/{sha}.gz'
    client = Client(raw)
    return SimpleNamespace(client=client, bucket='test'), {key: dict(sha256=sha, bytes=len(raw))}, key


def test_full_then_prior_reuses_only_fresh_matching_version():
    store, inventory, key = setup()
    first = reconcile(store, inventory)
    assert first['results'][key]['status'] == 'verified_exact_body'
    assert store.client.gets == 1
    assert reconcile(store, inventory, prior=first)['results'][key]['verification'].startswith('prior_full')
    assert store.client.gets == 1
    store.client.data = gzip.compress(b'current exact body', compresslevel=1, mtime=23)
    assert reconcile(store, inventory, prior=first)['results'][key]['verification'] == 'full_body_sha256'
    assert store.client.gets == 2


@pytest.mark.parametrize('change', [dict(sha256='wrong'), dict(raw_bytes=1), dict(stored_sha256='broken'), dict(stored_bytes=True)])
def test_corrupt_prior_falls_back_to_full_bytes(change):
    store, inventory, key = setup()
    prior = reconcile(store, inventory)
    prior['results'][key].update(change)
    assert reconcile(store, inventory, prior=prior)['results'][key]['status'] == 'verified_exact_body'
    assert store.client.gets == 2


def test_current_wrong_body_is_conflict():
    store, inventory, key = setup()
    store.client.data = gzip.compress(b'wrong retained body', mtime=0)
    assert reconcile(store, inventory)['results'][key]['status'] == 'conflict'


def test_unknown_read_failure_stays_unresolved():
    store, inventory, key = setup()
    store.client.get_object = Mock(side_effect=TimeoutError('uncertain'))
    assert reconcile(store, inventory)['results'][key]['status'] == 'unresolved'


def test_pinned_prior_rejects_changed_file_before_network(tmp_path):
    prior = tmp_path / 'prior.json'
    prior.write_text('{}')
    args = SimpleNamespace(batch=tmp_path, prior=prior, prior_sha256='wrong')
    with patch('reconcile_corpus_recovery_bodies.sealed_inputs', return_value=({}, {}, {})):
        with pytest.raises(ValueError, match='Prior evidence digest mismatch'):
            run(args)

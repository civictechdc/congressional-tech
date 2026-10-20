"""Large retained source admissions keep metadata pages finite."""
import pytest
from congress_api.retention import document_index as index
from congress_api.retention import source_update_proof as proof
from test_raw_storage import SelectorStore
from native_memory_helpers import MemoryNative


def basis():
    return dict(base=dict(selector_sha256=None, selected_ref=None), before=None,
                after=dict(root=None, namespace='source-proof', max_rows=4, max_bytes=4096),
                schema=index.SOURCE_SCHEMA, replacements=[])


def test_large_source_removal_uses_finite_pages_and_exact_membership():
    store = SelectorStore()
    deletions = [f'source-{i:064x}' for i in range(20000)]
    reference = proof.retain_source_update(store, deletions=iter(deletions), **basis())
    body = proof.read_source_update(store, reference)
    assert reference['bytes'] < 4096
    assert body['deletions']['count'] == len(deletions)
    assert sorted(proof.iterator_source_update_deletions(store, body)) == deletions
    assert max(map(len, store.objects.values())) <= 1 << 20
    result = proof.verify_source_update(store, reference, native=MemoryNative(),
        base=basis()['base'], before=None, rows=[], deletions=iter(deletions))
    assert result == basis()['after']
    with pytest.raises(ValueError, match='basis/deletions'):
        proof.verify_source_update(store, reference, native=MemoryNative(),
            base=basis()['base'], before=None, rows=[], deletions=iter(deletions[:-1]))


def test_source_removal_proof_refuses_duplicate_membership():
    with pytest.raises(ValueError, match='Repeated.*deletion'):
        proof.retain_source_update(SelectorStore(), deletions=['same', 'same'], **basis())

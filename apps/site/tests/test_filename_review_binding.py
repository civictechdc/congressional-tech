"""Reviews survive catalog versions only while their identity is unchanged."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.compute as pc
import pytest

SPEC = importlib.util.spec_from_file_location(
    'filename_review_binding', Path(__file__).resolve().parents[3] / 'apps/site/scripts/filename_review_binding.py')
binding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(binding)


def catalog(documents, sources, catalog_id='next'):
    """documents: [(document_id, body_key, filename)]; sources: [(source_id, document index)]."""
    table = pa.table({'document_id': [d[0] for d in documents], 'body_key': [d[1] for d in documents],
                      'filename': [d[2] for d in documents]})
    members = [[] for _ in documents]
    for row, (_, entry) in enumerate(sources):
        members[entry].append(row)
    return SimpleNamespace(documents=table, table=pa.table({'source_id': [s[0] for s in sources]}), members=members,
                           order=pc.sort_indices(table, sort_keys=[('filename', 'ascending')]), info={'catalog_id': catalog_id})


IDENTITIES = {'version': 1, 'catalog_id': 'pair', 'review_sha256': 'a' * 64, 'rows': [
    {'index': 0, 'document_id': 'reviewed', 'body_key': 'bodies/a', 'source_ids': ['s1', 's2']}]}


def test_positions_are_recomputed_when_documents_move():
    old = catalog([('reviewed', 'bodies/a', 'b.pdf'), ('other', 'bodies/x', 'c.pdf')], [('s1', 0), ('s2', 0), ('s9', 1)])
    new = catalog([('added', 'bodies/n', 'a.pdf'), ('other', 'bodies/x', 'c.pdf'), ('reviewed', 'bodies/a', 'b.pdf')],
                  [('s0', 0), ('s9', 1), ('s1', 2), ('s2', 2)])
    assert binding.bind(old, IDENTITIES)['rows'] == [{'index': 0, 'group': 0, 'sources': [0, 1]}]
    placed = binding.bind(new, IDENTITIES)
    assert placed == {'version': 1, 'review_sha256': 'a' * 64, 'catalog_id': 'next',
                      'rows': [{'index': 0, 'group': 1, 'sources': [2, 3]}], 'withdrawn': []}


@pytest.mark.parametrize('documents, sources, reason', [
    ([('other', 'bodies/x', 'c.pdf')], [('s1', 0), ('s2', 0)], 'document_missing'),
    ([('reviewed', 'bodies/a', 'b.pdf')], [('s1', 0), ('s2', 0), ('s3', 0)], 'sources_changed'),
    ([('reviewed', 'bodies/a', 'b.pdf')], [('s1', 0)], 'sources_changed'),
    ([('reviewed', 'bodies/changed', 'b.pdf')], [('s1', 0), ('s2', 0)], 'body_changed'),
])
def test_changed_reviews_are_withdrawn_with_a_reason(documents, sources, reason):
    placed = binding.bind(catalog(documents, sources), IDENTITIES)
    assert placed['rows'] == []
    assert placed['withdrawn'] == [{'index': 0, 'document_id': 'reviewed', 'reason': reason}]


def test_identities_round_trip_from_a_review_publication_and_refuse_mismatches():
    pinned = catalog([('reviewed', 'bodies/a', 'b.pdf'), ('other', 'bodies/x', 'c.pdf')], [('s2', 0), ('s1', 0), ('s9', 1)], 'pair')
    reviews = {'catalog_id': 'pair', 'review_sha256': 'a' * 64, 'rows': [{'group': 0, 'sources': [0, 1], 'document_id': 'reviewed'}]}
    identities = binding.identities_from(pinned, reviews)
    assert identities['rows'] == IDENTITIES['rows']
    assert binding.bind(pinned, identities)['rows'] == [{'index': 0, 'group': 0, 'sources': [0, 1]}]
    with pytest.raises(ValueError, match='different catalog'):
        binding.identities_from(pinned, {**reviews, 'catalog_id': 'other'})
    with pytest.raises(ValueError, match='does not match'):
        binding.identities_from(pinned, {**reviews, 'rows': [{**reviews['rows'][0], 'document_id': 'other'}]})


def test_committed_identities_name_the_published_review_pin():
    identities = binding.load_identities()
    descriptor = __import__('json').loads((Path(__file__).resolve().parents[3] / 'apps/site/document-review-publication.json').read_text())
    assert identities['review_sha256'] == descriptor['review_sha256']
    assert len(identities['rows']) == descriptor['groups']
    assert len({row['document_id'] for row in identities['rows']}) == len(identities['rows'])


def test_loaded_identities_require_pins_unique_rows_and_required_file(tmp_path):
    import json
    from copy import deepcopy
    path = tmp_path / 'identities.json'
    with pytest.raises(ValueError, match='missing'):
        binding.load_identities(path, descriptor=None)
    for damage in ('pin', 'index', 'document', 'sources'):
        value = deepcopy(IDENTITIES)
        if damage == 'pin': value.pop('review_sha256')
        elif damage == 'index': value['rows'] *= 2
        elif damage == 'document': value['rows'].append({**value['rows'][0], 'index': 1})
        else: value['rows'][0]['source_ids'] = ['s1', 's1']
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            binding.load_identities(path, descriptor=None)
    path.write_text(json.dumps(IDENTITIES))
    descriptor = tmp_path / 'descriptor.json'
    descriptor.write_text(json.dumps(dict(review_sha256='b' * 64, catalog_id='pair', groups=1)))
    with pytest.raises(ValueError, match='pins'):
        binding.load_identities(path, descriptor=descriptor)


def test_identity_generation_requires_exact_pinned_review_bytes(tmp_path):
    import hashlib
    import json
    value = dict(version=1, catalog_id='pair', review_sha256='a' * 64, rows=[])
    data = json.dumps(value).encode()
    path = tmp_path / 'reviews.json'; path.write_bytes(data)
    descriptor = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), groups=0,
                      catalog_id='pair', review_sha256='a' * 64)
    assert binding.pinned_reviews(path, descriptor) == value
    with pytest.raises(ValueError, match='pins'):
        binding.pinned_reviews(path, {**descriptor, 'catalog_id': 'other'})
    path.write_bytes(data + b' ')
    with pytest.raises(ValueError, match='bytes'):
        binding.pinned_reviews(path, descriptor)


def test_stable_withdrawal_survives_disappearance_and_return():
    from congress_api.retention.catalog_validation import catalog_source_ids_digest
    missing = binding.bind_selected('missing', IDENTITIES, lambda _: None)
    component = dict(source_ids_sha256=catalog_source_ids_digest(iter(['s1','s2'])), body_key='bodies/a')
    returned = binding.bind_selected('returned', IDENTITIES, lambda _: component, previous=missing)
    assert returned['rows'] == [] and returned['withdrawn'] == missing['withdrawn']
    assert returned['withdrawn'][0]['reason'] == 'document_missing'
    with pytest.raises(ValueError, match='explicit new review policy'):
        binding.bind_selected('returned', {**IDENTITIES, 'review_sha256': 'b' * 64}, lambda _: component, previous=missing)

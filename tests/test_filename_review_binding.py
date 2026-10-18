"""Reviews survive catalog versions only while their identity is unchanged."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.compute as pc
import pytest

SPEC = importlib.util.spec_from_file_location(
    'filename_review_binding', Path(__file__).resolve().parents[1] / 'apps/site/scripts/filename_review_binding.py')
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


IDENTITIES = {'version': 1, 'review_sha256': 'pin', 'rows': [
    {'index': 0, 'document_id': 'reviewed', 'body_key': 'bodies/a', 'source_ids': ['s1', 's2']}]}


def test_positions_are_recomputed_when_documents_move():
    old = catalog([('reviewed', 'bodies/a', 'b.pdf'), ('other', 'bodies/x', 'c.pdf')], [('s1', 0), ('s2', 0), ('s9', 1)])
    new = catalog([('added', 'bodies/n', 'a.pdf'), ('other', 'bodies/x', 'c.pdf'), ('reviewed', 'bodies/a', 'b.pdf')],
                  [('s0', 0), ('s9', 1), ('s1', 2), ('s2', 2)])
    assert binding.bind(old, IDENTITIES)['rows'] == [{'index': 0, 'group': 0, 'sources': [0, 1]}]
    placed = binding.bind(new, IDENTITIES)
    assert placed == {'version': 1, 'review_sha256': 'pin', 'catalog_id': 'next',
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
    reviews = {'catalog_id': 'pair', 'review_sha256': 'pin', 'rows': [{'group': 0, 'sources': [0, 1], 'document_id': 'reviewed'}]}
    identities = binding.identities_from(pinned, reviews)
    assert identities['rows'] == IDENTITIES['rows']
    assert binding.bind(pinned, identities)['rows'] == [{'index': 0, 'group': 0, 'sources': [0, 1]}]
    with pytest.raises(ValueError, match='different catalog'):
        binding.identities_from(pinned, {**reviews, 'catalog_id': 'other'})
    with pytest.raises(ValueError, match='does not match'):
        binding.identities_from(pinned, {**reviews, 'rows': [{**reviews['rows'][0], 'document_id': 'other'}]})


def test_committed_identities_name_the_published_review_pin():
    identities = binding.load_identities()
    descriptor = __import__('json').loads((Path(__file__).resolve().parents[1] / 'apps/site/document-review-publication.json').read_text())
    assert identities['review_sha256'] == descriptor['review_sha256']
    assert len(identities['rows']) == descriptor['groups']
    assert len({row['document_id'] for row in identities['rows']}) == len(identities['rows'])

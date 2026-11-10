"""ct-isnv: kind words a release's schema lists as one kind are filtered as one.

A release published before synonyms were keeps each reader's earlier behaviour.
"""
from contextlib import closing
import json
import shutil

import pytest

from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import prepare
from conftest import manifest, replace_rows

KINDS = [['witness-statement'], ['testimony'], ['statement'], ['witness-testimony']]


def release(tmp_path, phase2, published):
    root = tmp_path / 'release'
    shutil.copytree(phase2.parent, root)
    def kinds(rows):
        for row, kind in zip(rows, KINDS):
            row.update(document_kind=kind, hidden=False, meeting_keys=['118001'])
    replace_rows(root, 'list', kinds)
    schema = json.loads((root / 'schema.json').read_text())
    listed = next(t for t in schema['files'] if t['name'] == 'list.parquet')
    assert listed['synonyms'] == {'document_kind[]': [['witness-statement', 'testimony']]}
    if not published:
        del listed['synonyms']
    (root / 'schema.json').write_text(json.dumps(schema))
    return prepare(tmp_path / 'selected', manifest(root), archive_origin='https://archive.example')


@pytest.mark.parametrize('published,expected', [
    (True, {'testimony': [['witness-statement'], ['testimony']], 'witness-statement': [['witness-statement'], ['testimony']],
            'statement': [['statement']], 'witness-testimony': [['witness-testimony']]}),
    (False, {'testimony': [['testimony']], 'witness-statement': [['witness-statement']],
             'statement': [['statement']], 'witness-testimony': [['witness-testimony']]}),
])
def test_search_documents_filters_published_synonyms_as_one_kind(tmp_path, phase2, published, expected):
    with closing(Reader(release(tmp_path, phase2, published))) as reader:
        for kind, kinds in expected.items():
            assert [r['document_kind'] for r in reader.search_documents(dict(document_kind=kind))['rows']] == kinds, kind


@pytest.mark.parametrize('published,expected', [
    (True, [['witness-statement'], ['testimony']]),
    # The hearing reader's earlier fixed set, kept for releases that list no synonyms.
    (False, [['witness-statement'], ['testimony'], ['witness-testimony']]),
])
def test_hearing_bundle_prepared_testimony_reads_published_synonyms(tmp_path, phase2, published, expected):
    with closing(Reader(release(tmp_path, phase2, published))) as reader:
        bundle = reader.get_hearing_bundle(dict(event_id=118001, include=['prepared_testimony']))
        assert [r['document_kind'] for r in bundle['sections']['prepared_testimony']['rows']] == expected

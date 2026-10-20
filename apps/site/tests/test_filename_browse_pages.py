"""Stable browse pages retain unaffected records across ordering changes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from filename_native import BrowsePages, ViewerAssets


def row(number):
    return dict(document_id=f'{number:064x}', source_id=f'{number + 1000:064x}', filename=f'{number:05}.pdf')


def test_insert_delete_before_page_reuses_unrelated_assets_and_saved_identity(tmp_path):
    assets = ViewerAssets(tmp_path)
    pages = BrowsePages(assets, leaf_rows=4, branch_children=4)
    root = pages.build(row(i) for i in range(1, 41))
    before = dict(assets.identities)
    changed = pages.change(root, remove=[row(1)], add=[row(0)])
    assert [r['document_id'] for r in pages.page(changed, offset=0, limit=5)] == [row(i)['document_id'] for i in [0,2,3,4,5]]
    assert pages.find(changed, row(20)['filename'], row(20)['document_id']) == row(20)
    assert pages.find(root, row(1)['filename'], row(1)['document_id']) == row(1)
    assert pages.find(changed, row(1)['filename'], row(1)['document_id']) is None
    assert len(set(assets.identities) - set(before)) <= 8
    assert all((tmp_path / key).read_bytes() for key in before)
    assert pages.page(root, offset=39, limit=10) == [row(40)]


def test_browse_splits_match_ordered_reference_after_insertions_and_deletions(tmp_path):
    import random
    assets = ViewerAssets(tmp_path)
    pages = BrowsePages(assets, leaf_rows=4, branch_children=4)
    # This seed fills a final branch during bulk carry into a new root.
    selected = {number: row(number) for number in range(65)}
    root = pages.build(selected.values())
    original = root
    for position in random.Random(42).sample(range(65), 20):
        old = selected.pop(position)
        new = row(position + 100)
        selected[position + 100] = new
        root = pages.change(root, remove=[old], add=[new])
        expected = [selected[number] for number in sorted(selected)]
        assert pages.page(root, offset=0, limit=100) == expected
        assert pages.page(root, offset=17, limit=7) == expected[17:24]
    assert pages.page(original, offset=0, limit=100) == [row(number) for number in range(65)]


def test_missing_or_tampered_browse_page_refuses_before_emitting_rows(tmp_path):
    import pytest
    assets = ViewerAssets(tmp_path)
    pages = BrowsePages(assets, leaf_rows=4, branch_children=4)
    root = pages.build(row(number) for number in range(10))
    with pytest.raises(ValueError, match='count or bounds'):
        pages.page({**root, 'rows': 100}, offset=0, limit=1)
    (tmp_path / root['path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='identity differs'):
        BrowsePages(ViewerAssets(tmp_path), leaf_rows=4, branch_children=4).page(root, offset=0, limit=1)

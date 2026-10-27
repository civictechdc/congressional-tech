"""Component entry lookups keep their values and seek by component."""
import json
from pathlib import Path
import sqlite3
import sys

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY
from viewer_publication.filename_native import BrowsePages, NativeComponents, ViewerAssets

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'congress_api/tests')]
from test_catalog_coalesced_batches import Native
from test_native_catalog_selection import seed


def test_component_entries_preserve_results_and_seek_by_component(tmp_path):
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    assets = ViewerAssets(tmp_path / 'assets')
    with sqlite3.connect(':memory:', cached_statements=0) as db:
        options = dict(policy=DEFAULT_DECODED_POLICY, metrics={})
        renderer = NativeComponents(selected, assets, BrowsePages(assets), db, **options)
        renderer.plan(selected.selection['components'])
        renderer._register_chunks()
        for row in db.execute('SELECT * FROM chunks ORDER BY label,name'):
            renderer._prepare_chunk(*row)
        # Unrelated membership makes the repeated scan visible in the query plan.
        db.executemany('INSERT INTO views VALUES (?,?,?)',
            ((f'unrelated-{i // 64}', f'unrelated-{i}', 1) for i in range(4096)))
        original_records = list(db.execute('SELECT record,id FROM components'))
        db.execute('DROP INDEX views_by_component')
        statements = []
        db.set_trace_callback(statements.append)
        renderer._prepare_entries()
        db.set_trace_callback(None)
        baseline = list(db.execute('SELECT id,entry,record FROM components ORDER BY id'))
        queries = [sql for sql in statements if sql.startswith(
            'SELECT reference FROM chunk_assets JOIN views USING(name) WHERE component=')]
        assert len(queries) == len(baseline) == 2
        # Also cover no matching document and multiple matching document assets.
        queries += [queries[0].split('WHERE component=')[0] + "WHERE component='absent'",
            "SELECT reference FROM chunk_assets JOIN views USING(name) WHERE component='duplicate'"]
        for name, reference in list(db.execute('SELECT name,reference FROM chunk_assets')):
            db.execute('INSERT INTO chunk_assets VALUES (?,?)', (name + '-duplicate', reference))
            db.executemany('INSERT INTO views VALUES (?,?,1)',
                [(name, 'duplicate'), (name + '-duplicate', 'duplicate')])
        expected = [db.execute(sql).fetchall() for sql in queries]
        assert expected[-2] == [] and len(expected[-1]) == 2
        assert all(any('SCAN views' in row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + sql))
            for sql in queries)

        # Reopening a populated staging database adds the index idempotently.
        for _ in range(2):
            NativeComponents(selected, assets, BrowsePages(assets), db, **options)
        assert [row[2] for row in db.execute('PRAGMA index_info(views_by_component)')] == ['component', 'name']
        assert [db.execute(sql).fetchall() for sql in queries] == expected
        for sql in queries:
            details = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + sql)]
            assert any('SEARCH views' in detail and 'views_by_component' in detail for detail in details)
            assert not any('SCAN views' in detail for detail in details)
        db.executemany('UPDATE components SET record=? WHERE id=?', original_records)
        renderer._prepare_entries()
        assert list(db.execute('SELECT id,entry,record FROM components ORDER BY id')) == baseline
        assert all(json.loads(entry)['document_file'] for _, entry, _ in baseline)

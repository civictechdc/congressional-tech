"""The live recovery writer applies the same privacy rule as capture."""
import gzip
import json


def test_recovery_import_retains_public_receipts_and_original_inputs():
    from test_import_corpus_recovery_batch import ImportTests, Store
    fixture = ImportTests()
    fixture.setUp()
    try:
        record = fixture.prepared[0]['record']
        record['response_headers'] = {'Set-Cookie': 'private', 'Content-Type': 'application/zip'}
        record['source_path'] = '/tmp/private/source.json'
        store = Store()
        result = fixture.run_import(store)
        assert result['complete']
        [key] = [key for key in store.data if key.startswith('receipts/')]
        [line] = [json.loads(row) for row in gzip.decompress(store.data[key]).splitlines()]
        assert line['record']['response_headers'] == {'Content-Type': 'application/zip'}
        assert line['record']['source_path'] == 'source.json'
        assert record['source_path'] == '/tmp/private/source.json'
        assert len(line['captures']) == 2
    finally:
        fixture.doCleanups()

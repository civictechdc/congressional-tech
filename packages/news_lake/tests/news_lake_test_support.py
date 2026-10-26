"""Shared news-lake test data paths and content-level state comparison."""
import json
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / 'docs'
DOCS_SCHEMA = DOCS / 'schema' / 'news-lake.schema.json'
DOCS_FIXTURES = DOCS / 'examples' / 'records.jsonl'


def logical_state(lake, control, release_ids):
    """Content-level final state: records per table, releases (ignoring volatile
    snapshot ids but keeping table uuids), cursor, availability."""
    from news_lake.contract.records import CONTENT_TABLES

    state = {}
    for table in CONTENT_TABLES:
        state[table] = sorted((json.dumps(r, sort_keys=True) for r in lake.read_all(table)))
    releases = []
    for record in lake.read_all('news.releases'):
        if record['id'] in release_ids:
            # Snapshot ids and table UUIDs are warehouse-scoped; convergence is
            # about content, which read_release verifies within the warehouse.
            releases.append(json.dumps(
                {k: v for k, v in record.items() if k != 'snapshots'}, sort_keys=True
            ))
    state['news.releases'] = sorted(releases)
    state['cursor'] = control.active_cursor()
    state['availability'] = {rid: control.availability(rid) for rid in release_ids}
    return state

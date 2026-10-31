"""An exact lookup must not round an ID or lose its related documents."""
import pytest

from congressional_explorer_mcp.models import EntityQuery, EntitySearch, ExplorerError
from congressional_explorer_mcp.reader import Reader
from congressional_explorer_mcp.release import prepare


@pytest.mark.parametrize('value', ['118000.9', '118001.0', '1.18001e5', True, False, 118001.0, 2**63, -(2**63)-1])
def test_integer_entity_rejects_lossy_inputs(reader, value):
    for section in ('record', 'documents'):
        with pytest.raises(ValueError, match='integer|Input should'):
            reader.get_entity(dict(table='meetings', id=value, section=section))


@pytest.mark.parametrize('value', ['118.9', '119.0', '1.19e2', True, False, 119.0, 2**15, -(2**15)-1])
def test_integer_filter_rejects_lossy_inputs(reader, value):
    with pytest.raises(ValueError, match='integer|Input should'):
        reader.search_entities(dict(table='rosters', filters={'congress': value}))


def test_models_preserve_values_before_column_validation():
    for value in (True, False, 118001.0):
        with pytest.raises(ValueError):
            EntityQuery(table='meetings', id=value)
    with pytest.raises(ValueError):
        EntitySearch(table='rosters', filters={'congress': 119.0})
    assert EntitySearch(table='witnesses', filters={'testified': True}).filters['testified'] is True


def test_integer_spellings_share_records_documents_and_cursors(tmp_path, linked_transcripts):
    reader = Reader(prepare(tmp_path, linked_transcripts))
    try:
        expected = reader.get_entity(dict(table='meetings', id=118001, section='documents'))['rows']
        query = dict(table='meetings', section='documents', limit=1)
        page = reader.get_entity(dict(query, id='0118001'))
        rows = page['rows']
        while page['has_more']:
            page = reader.get_entity(dict(query, id='118001 ', cursor=page['next_cursor']))
            rows += page['rows']
        assert rows == expected and len(rows) == 3
        for value in (118001, '118001', '0118001', ' 118001 '):
            assert reader.get_entity(dict(table='meetings', id=value))['rows'][0]['event_id'] == 118001
            assert reader.get_entity(dict(table='meetings', id=value, section='documents'))['rows'] == expected
            assert reader.search_entities(dict(table='meetings', filters={'event_id': value}))['rows'][0]['event_id'] == 118001
        with pytest.raises(ExplorerError, match='another release or query'):
            first = reader.get_entity(dict(query, id=118001))
            reader.get_entity(dict(query, id=118002, cursor=first['next_cursor']))
    finally:
        reader.close()


def test_text_keys_booleans_absence_and_raw_sql_keep_their_meaning(reader):
    assert reader.get_entity(dict(table='bills', id='119-hr-1'))['rows'][0]['bill_id'] == '119-hr-1'
    assert len(reader.search_entities(dict(table='witnesses', filters={'testified': True}))['rows']) == 2
    assert reader.search_entities(dict(table='witnesses', filters={'testified': False}))['rows'] == []
    with pytest.raises(ExplorerError, match='requires text'):
        reader.get_entity(dict(table='witnesses', id=1))
    with pytest.raises(ExplorerError, match='requires a boolean'):
        reader.search_entities(dict(table='witnesses', filters={'testified': 'true'}))
    with pytest.raises(ExplorerError, match='absent'):
        reader.get_entity(dict(table='meetings', id='000999'))
    # Convenience-tool validation must not change general SQL parameter semantics.
    assert reader.query_sql(dict(sql='SELECT ? = 119::SMALLINT AS same', parameters=['118.9']))['rows'] == [{'same': True}]


def test_integer_filter_cursor_uses_canonical_value(reader):
    first = reader.search_entities(dict(table='witnesses', filters={'panel_order': '01'}, limit=1))
    assert first['has_more']
    second = reader.search_entities(dict(table='witnesses', filters={'panel_order': 1}, limit=1, cursor=first['next_cursor']))
    assert second['rows'][0]['witness_key'] == 'appearance-2'
    assert not second['has_more']

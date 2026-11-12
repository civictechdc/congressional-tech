"""An exact lookup must not round an ID or lose its related documents."""
import pytest

from congressional_explorer_mcp.models import DocumentQuery, DocumentSearch, EntityQuery, EntitySearch, ExplorerError, Page, SqlQuery
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


@pytest.mark.parametrize('value', [True, False, 10.0, '10.0', '1e1', 0, 101])
def test_page_and_sql_limit_reject_booleans_decimals_and_out_of_range(reader, value):
    with pytest.raises(ValueError):
        Page(limit=value)
    with pytest.raises(ValueError):
        reader.search_documents(dict(limit=value))
    if value != 101:
        with pytest.raises(ValueError):
            SqlQuery(sql='SELECT 1', limit=value)
        with pytest.raises(ValueError):
            reader.query_sql(dict(sql='SELECT 1', limit=value))


@pytest.mark.parametrize('value', [True, False, 119.0, '118.9', '119.0', '1.19e2', 0, 1000])
def test_document_search_congress_and_meeting_key_reject_lossy_inputs(reader, value):
    with pytest.raises(ValueError):
        DocumentSearch(congress=value)
    with pytest.raises(ValueError):
        reader.search_documents(dict(congress=value))
    if value not in (0, 1000):
        with pytest.raises(ValueError):
            DocumentSearch(meeting_key=value)
        with pytest.raises(ValueError):
            reader.search_documents(dict(meeting_key=value))


@pytest.mark.parametrize('value', [1, 0, 'true', 'false', '1'])
def test_document_search_include_hidden_requires_strict_boolean(reader, value):
    with pytest.raises(ValueError, match='boolean'):
        DocumentSearch(include_hidden=value)
    with pytest.raises(ValueError, match='boolean'):
        reader.search_documents(dict(include_hidden=value))


def test_document_search_meeting_key_and_case_variants_normalize_and_share_cursors(tmp_path, linked_transcripts):
    reader = Reader(prepare(tmp_path, linked_transcripts))
    try:
        expected = reader.search_documents(dict(meeting_key='118001'))['rows']
        assert len(expected) == 3
        for spelling in (118001, '118001', '0118001', ' 118001 '):
            assert reader.search_documents(dict(meeting_key=spelling))['rows'] == expected
        first = reader.search_documents(dict(meeting_key=118001, limit=1))
        second = reader.search_documents(dict(meeting_key='0118001', limit=1, cursor=first['next_cursor']))
        assert second['rows'] == expected[1:2]
    finally:
        reader.close()


def test_legislative_identifier_case_normalization_and_mixed_case_preservation(reader):
    # Case-insensitive legislative identifiers normalize across search_documents, get_entity, and search_entities.
    expected_doc = reader.search_documents(dict(committee_key='hsif00'))['rows']
    assert len(expected_doc) == 1
    assert reader.search_documents(dict(committee_key='HSIF00', measure_key='119-HR-1', bioguide_id='a000001'))['rows'] == expected_doc
    first = reader.search_documents(dict(committee_key='HSIF00', limit=1))
    assert DocumentSearch(committee_key='HSIF00', measure_key='119-HR-1', bioguide_id='a000001').model_dump() == \
        DocumentSearch(committee_key='hsif00', measure_key='119-hr-1', bioguide_id='A000001').model_dump()
    assert reader.get_entity(dict(table='committees', id='HSIF00'))['rows'][0]['system_code'] == 'hsif00'
    assert reader.get_entity(dict(table='members', id='a000001'))['rows'][0]['bioguide_id'] == 'A000001'
    assert reader.get_entity(dict(table='bills', id='119-HR-1'))['rows'][0]['bill_id'] == '119-hr-1'
    assert reader.get_entity(dict(table='nominations', id='119-PN-730-2'))['rows'][0]['nomination_id'] == '119-pn-730-2'
    assert reader.search_entities(dict(table='rosters', filters={'system_code': 'HSIF00', 'bioguide_id': 'a000001'}))['rows'][0]['bioguide_id'] == 'A000001'
    assert reader.search_entities(dict(table='bills', filters={'sponsor_bioguide_id': 'a000001'}))['rows'][0]['sponsor_bioguide_id'] == 'A000001'
    # Case-sensitive identifiers (video_key, handle, record_key) preserve exact case.
    assert reader.get_entity(dict(table='videos', id='youtube:free'))['rows'][0]['video_key'] == 'youtube:free'
    assert reader.get_entity(dict(table='channels', id='@AgRepublicans'))['rows'][0]['handle'] == '@AgRepublicans'
    with pytest.raises(ExplorerError, match='absent'):
        reader.get_entity(dict(table='channels', id='@agrepublicans'))


def test_uppercase_document_query_link_key_normalizes_for_lookup_and_cursor_binding(reader):
    ref = reader.search_documents(dict(text='agenda'))['rows'][0]['reference']
    upper_key = ref['link_key'].upper()
    assert DocumentQuery(release_id=ref['release_id'], link_key=upper_key).link_key == ref['link_key']
    summary = reader.get_document(dict(release_id=ref['release_id'], link_key=upper_key))
    assert summary['rows'][0]['reference']['link_key'] == ref['link_key']
    sources_upper = reader.get_document(dict(release_id=ref['release_id'], link_key=upper_key, section='sources', limit=1))
    sources_lower = reader.get_document(dict(release_id=ref['release_id'], link_key=ref['link_key'], section='sources', limit=1))
    assert sources_upper == sources_lower


def test_witness_rank_and_credentials_are_searchable_and_returned(reader):
    lt_gen = reader.search_entities(dict(table='witnesses', text='Lt. Gen.'))['rows']
    assert [r['witness_key'] for r in lt_gen] == ['appearance-1', 'mods-appearance-1']
    assert lt_gen[0]['rank'] == 'Lt. Gen.'
    assert lt_gen[0]['credentials'] == 'USAF'

    phd = reader.search_entities(dict(table='witnesses', text='Ph.D.'))['rows']
    assert {r['witness_key'] for r in phd} == {'0001497931f99cd1', '0000b43c099edbc2'}
    assert all(r['credentials'] == 'Ph.D.' and r['rank'] is None for r in phd)


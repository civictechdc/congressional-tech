"""Source document types fill gaps without replacing filename evidence."""
import pyarrow.parquet as pq
import pytest

from congress_api.retention import document_index as index


@pytest.mark.parametrize(('source_type', 'kind'), [
    ('Witness Statement', 'witness-statement'), ('WS', 'witness-statement'),
    ('Witness Truth in Testimony', 'testimony-disclosure'), ('WT', 'testimony-disclosure'),
    ('Witness Biography', 'witness-biography'), ('WB', 'witness-biography'),
    ('Witness Support Document', 'witness-support'), ('WD', 'witness-support'),
    ('Member Statements', 'member-statement'), ('MS', 'member-statement'),
    ('Committee Amendment', 'committee-amendment'), ('CA', 'committee-amendment'),
    ('House or Senate Amendment', 'interchamber-amendment'), ('HA', 'interchamber-amendment'),
    ('Floor Amendment', 'floor-amendment'), ('FA', 'floor-amendment'),
    ('Committee Recorded Vote', 'committee-vote'), ('CV', 'committee-vote'),
    ('Committee Report', 'committee-report'), ('CR', 'committee-report'),
    ('Conference Report', 'conference-report'), ('FR', 'conference-report'),
    ('Bills and Resolutions', 'legislative-text'), ('BR', 'legislative-text'),
    ('Support Document', 'support-document'), ('SD', 'support-document'),
    ('Hearing: Transcript', 'transcript'), ('HT', 'transcript'),
    ('Hearing: Witness List', 'witness-list'), ('HW', 'witness-list'),
    ('Hearing: Questions for the Record', 'questions-for-record'), ('HQ', 'questions-for-record'),
    ('Hearing: Member Roster', 'member-roster'), ('HM', 'member-roster'),
    ('Hearing: Cover Page', 'cover-page'), ('HC', 'cover-page'),
    ('Hearing: Table of Contents', 'table-of-contents'), ('TC', 'table-of-contents'),
    ('questions for the record', 'questions-for-record'), ('questionnaire', 'questionnaire'),
    ('  witness   statement ', 'witness-statement'), ('member statement', 'member-statement'),
    ('transcript', 'transcript'),
])
def test_native_types_fill_empty_kind_in_both_tables(tmp_path, source_type, kind):
    (tmp_path / 'indexes').mkdir()
    source = dict(filename='JaneDoe.pdf', source_url='https://x.test/JaneDoe.pdf',
                  body_key=None, source_document_type=[source_type])
    index.write_filename_metadata(tmp_path, [source], workers=1)
    for name in ('document-filenames.parquet', 'documents.parquet'):
        row, = pq.read_table(tmp_path / 'indexes' / name).to_pylist()
        assert row['document_kind'] == [kind]
        assert row['document_kind_source'] == ['source_document_type']
        assert row['source_document_type'] == [source_type]
    assert not index.Engine().extract('JaneDoe.pdf')['metadata'].get('document_kind')


def test_filename_genre_wins_across_aliases_and_source_types(tmp_path):
    (tmp_path / 'indexes').mkdir()
    shared = dict(body_key='same-pdf', media_type=['application/pdf'], http_status=['200'])
    sources = [dict(shared, filename='JaneDoe.pdf', source_url='https://x.test/jane',
                    source_document_type=['other', 'Witness Statement']),
               dict(shared, filename='JaneDoe Transcript.pdf', source_url='https://x.test/transcript',
                    source_document_type=['Witness Statement'])]
    index.write_filename_metadata(tmp_path, sources, workers=1)
    rows = pq.read_table(tmp_path / 'indexes/document-filenames.parquet').to_pylist()
    assert rows[0]['document_kind'] == ['witness-statement']
    assert rows[0]['document_kind_source'] == ['source_document_type']
    assert rows[1]['document_kind'] == ['transcript']
    assert rows[1]['document_kind_source'] == ['filename']
    doc, = pq.read_table(tmp_path / 'indexes/documents.parquet').to_pylist()
    assert doc['document_kind'] == ['transcript']
    assert doc['document_kind_source'] == ['filename']
    assert doc['source_document_type'] == ['Witness Statement', 'other']


def test_multiple_source_types_survive_without_other_hiding_them(tmp_path):
    (tmp_path / 'indexes').mkdir()
    source = dict(body_key=None, filename='JaneDoe.pdf', source_url=None,
                  source_document_type=['other', 'Witness Statement', 'WS', 'transcript'])
    index.write_filename_metadata(tmp_path, [source], workers=1)
    doc, = pq.read_table(tmp_path / 'indexes/documents.parquet').to_pylist()
    assert doc['document_kind'] == ['transcript', 'witness-statement']
    assert sorted(doc['source_document_type']) == sorted(source['source_document_type'])


@pytest.mark.parametrize('source_types', [None, [], [''], ['other'], [' OTHER '], ['not-a-recognized-type']])
def test_missing_or_unrecognized_type_stays_empty(tmp_path, source_types):
    (tmp_path / 'indexes').mkdir()
    source = dict(body_key=None, filename='JaneDoe.pdf', source_url=None,
                  source_document_type=source_types)
    index.write_filename_metadata(tmp_path, [source], workers=1)
    row, = pq.read_table(tmp_path / 'indexes/documents.parquet').to_pylist()
    assert row['document_kind'] is None
    assert row['document_kind_source'] is None


def test_cached_filename_results_do_not_retain_source_fallback(tmp_path):
    (tmp_path / 'indexes').mkdir()
    source = dict(body_key=None, filename='JaneDoe.pdf', source_url='https://x.test/jane',
                  source_document_type=['Witness Statement'])
    index.write_filename_metadata(tmp_path, [source], workers=1)
    path = tmp_path / 'indexes/document-filenames.parquet'
    for source_types, expected in [(['transcript'], ['transcript']), (None, None)]:
        previous = pq.read_table(path)
        source['source_document_type'] = source_types
        stats = index.write_filename_metadata(tmp_path, [source], workers=1, previous=previous)
        assert stats['parsed_inputs'] == 0
        row, = pq.read_table(path).to_pylist()
        assert row['document_kind'] == expected
        assert row['document_kind_source'] == (['source_document_type'] if expected else None)


def test_source_refresh_and_regroup_recompute_fallback_without_parsing(tmp_path, monkeypatch):
    (tmp_path / 'indexes').mkdir()
    source = dict(body_key=None, filename='JaneDoe.pdf', source_url='https://x.test/jane',
                  source_document_type=['Witness Statement'])
    index.write_filename_metadata(tmp_path, [source], workers=1)
    path = tmp_path / 'indexes/document-filenames.parquet'
    original, = pq.read_table(path).to_pylist()
    def no_parsing(_):
        raise AssertionError('Source refresh must not reparse filenames')
    monkeypatch.setattr(index, 'extract', no_parsing)
    class Context:
        def for_url(self, url):
            return {'source_document_type': ['transcript']}
    index.refresh_source_metadata(tmp_path, Context())
    index.reindex_documents(tmp_path)
    row, = pq.read_table(path).to_pylist()
    assert row['document_kind'] == ['transcript']
    assert row['document_kind_source'] == ['source_document_type']
    assert row['source_id'] == original['source_id']
    assert row['document_id'] == original['document_id']


def test_missing_filename_can_use_a_source_type(tmp_path):
    (tmp_path / 'indexes').mkdir()
    index.write_filename_metadata(tmp_path, [dict(body_key='body', filename=None, source_url=None,
                                                  source_document_type=['transcript'])], workers=1)
    row, = pq.read_table(tmp_path / 'indexes/documents.parquet').to_pylist()
    assert row['filename'] is None
    assert row['document_kind'] == ['transcript']
    assert row['document_kind_source'] == ['source_document_type']
